"""
signals.app_qt.workers
======================

Тонкие обёртки QThread над сервисом измерения. Вся логика прибора — в
signals.services.measurement и в плагине прибора; здесь только увод работы с
UI-потока и сигналы. Каждая операция самодостаточна: подключение → работа →
отключение (одна точка, без дублирования из старого instrumenthandler).
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from ..extpoints import INSTRUMENTS
from ..services import MeasurementService, SweepConfig


def _build(kind: str, resource: str):
    return INSTRUMENTS.target(kind)(resource)


def scan_instruments(log) -> list[dict]:
    """Просканировать систему на ВСЁ подключённое оборудование и опознать приборы.

    * VISA-приборы: перечисляем ресурсы, опрашиваем *IDN?, сопоставляем с плагинами
      по их отпечатку (matches_idn). В журнал пишем КАЖДЫЙ ресурс и его ответ —
      удобно снимать фингерпринты нового оборудования.
    * не-VISA приборы (Hantek): спрашиваем у плагина discover() (скан USB).

    Возвращает список dict(kind, label, resource, idn, caps).
    """
    found: list[dict] = []
    visa_plugins = [e for e in INSTRUMENTS if getattr(e.target, "USES_VISA", False)]

    # 1) VISA-сканирование
    try:
        import pyvisa
        rm = pyvisa.ResourceManager()
        resources = list(rm.list_resources())
        log(f"VISA: ресурсов найдено — {len(resources)}")
        for res in resources:
            idn = None
            try:
                inst = rm.open_resource(res)
                try:
                    inst.timeout = 2500
                except Exception:
                    pass
                idn = (inst.query("*IDN?") or "").strip()
                inst.close()
                log(f"  {res} → {idn or '(пустой ответ)'}")
            except Exception as exc:                   # noqa: BLE001
                log(f"  {res} → нет ответа ({exc})")
            for e in visa_plugins:
                try:
                    if idn and e.target.matches_idn(idn):
                        found.append({"kind": e.key, "label": e.meta.get("label", e.key),
                                      "resource": res, "idn": idn,
                                      "caps": e.meta.get("caps", set())})
                        log(f"    ↳ опознан как «{e.meta.get('label', e.key)}»")
                except Exception:                      # noqa: BLE001
                    pass
    except ImportError:
        log("VISA: PyVISA не установлен — VISA-приборы не сканируются (pip install pyvisa)")
    except Exception as exc:                           # noqa: BLE001
        log(f"VISA: ошибка сканирования — {exc}")

    # 2) не-VISA приборы (Hantek и подобные)
    for e in INSTRUMENTS:
        if getattr(e.target, "USES_VISA", False):
            continue
        disc = getattr(e.target, "discover", None)
        if not callable(disc):
            continue
        label = e.meta.get("label", e.key)
        used_log = False
        try:
            try:
                devices = disc(log=log) or []; used_log = True   # плагин пишет в журнал сам
            except TypeError:
                devices = disc() or []
        except Exception as exc:                       # noqa: BLE001
            log(f"«{label}»: ошибка поиска — {exc}"); continue
        if not devices and not used_log:
            log(f"«{label}»: устройств не найдено")
        for d in devices:
            found.append({"kind": e.key, "label": label,
                          "resource": str(d.get("resource", "0")),
                          "idn": d.get("idn", ""), "caps": e.meta.get("caps", set())})
            if not used_log:
                log(f"«{label}»: {d.get('idn', 'устройство')} [{d.get('resource', '0')}]")

    log(f"Итого опознано приборов: {len(found)}")
    return found


class DetectWorker(QThread):
    found = pyqtSignal(list)              # list[dict(kind,label,resource,idn,caps)]
    log = pyqtSignal(str)

    def run(self) -> None:
        self.log.emit("Сканирование подключённого оборудования…")
        try:
            devices = scan_instruments(self.log.emit)
        except Exception as exc:                       # noqa: BLE001
            self.log.emit(f"Ошибка обнаружения: {exc}"); devices = []
        self.found.emit(devices)


class ReadWorker(QThread):
    finished_ok = pyqtSignal(dict)        # {channel_name: Channel}
    failed = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, kind: str, resource: str) -> None:
        super().__init__()
        self.kind, self.resource = kind, resource

    def run(self) -> None:
        try:
            self.log.emit("Подключение к осциллографу…")
            inst = _build(self.kind, self.resource)
            if hasattr(inst, "log"):
                inst.log = self.log.emit
            inst.connect()
            self.log.emit("Чтение осциллограммы…")
            channels = MeasurementService(inst).capture_now()
            inst.disconnect()
            self.finished_ok.emit(channels)
        except Exception as exc:                       # noqa: BLE001
            self.failed.emit(str(exc))


class MeasureWorker(QThread):
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int)
    log = pyqtSignal(str)

    def __init__(self, osc_kind: str, osc_res: str, gen_kind: str, gen_res: str,
                 cfg: SweepConfig) -> None:
        super().__init__()
        self.osc_kind, self.osc_res = osc_kind, osc_res
        self.gen_kind, self.gen_res = gen_kind, gen_res
        self.cfg = cfg
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        scope = generator = None
        try:
            self.log.emit("Подключение к осциллографу…")
            scope = _build(self.osc_kind, self.osc_res)
            if hasattr(scope, "log"):
                scope.log = self.log.emit
            scope.connect()
            if (self.gen_kind, self.gen_res) == (self.osc_kind, self.osc_res):
                generator = scope                      # Hantek: один прибор на оба
            else:
                self.log.emit("Подключение к генератору…")
                generator = _build(self.gen_kind, self.gen_res)
                if hasattr(generator, "log"):
                    generator.log = self.log.emit
                generator.connect()
            channels = MeasurementService(scope, generator).run(
                self.cfg,
                progress=self.progress.emit,
                log=self.log.emit,
                should_stop=lambda: self._stop)
            if not self._stop:
                self.finished_ok.emit(channels)
        except Exception as exc:                       # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            try:
                if scope is not None:
                    scope.disconnect()
                if generator is not None and generator is not scope:
                    generator.disconnect()
            except Exception:                          # noqa: BLE001
                pass
