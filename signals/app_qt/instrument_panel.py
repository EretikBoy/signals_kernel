"""
signals.app_qt.instrument_panel
==============================

Управление приборами — три отдельные группы (Генератор / Осциллограф /
Управление). Списки приборов заполняются РЕАЛЬНЫМ сканированием системы
(VISA *IDN? + USB-поиск Hantek) — вручную ресурс вводить не нужно. «Обновить
список приборов» пишет в журнал всё найденное и его ответы (для фингерпринтов).

Кнопки цветные и динамические. Параметры генератора запоминаются между запусками.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ..domain import MeasurementParams
from ..plugins.capabilities import Cap
from ..services import SweepConfig
from . import theme
from .workers import DetectWorker, MeasureWorker, ReadWorker

BTN_MEASURE = """
QPushButton { background-color: rgba(70,130,180,200); color: white; font-weight: bold;
  font-size: 14px; padding: 8px; border: 2px solid rgba(50,110,160,220); border-radius: 5px; }
QPushButton:hover { background-color: rgba(80,140,190,230); }
QPushButton:pressed { background-color: rgba(60,120,170,255); }
QPushButton:disabled { background-color: rgba(120,120,120,120); border-color: rgba(100,100,100,120); }
"""
BTN_STOP = """
QPushButton { background-color: rgba(180,60,60,200); color: white; font-weight: bold;
  padding: 8px; border: 2px solid rgba(150,50,50,220); border-radius: 5px; }
QPushButton:hover { background-color: rgba(200,70,70,230); }
QPushButton:disabled { background-color: rgba(120,120,120,120); border-color: rgba(100,100,100,120); }
"""
BTN_RECORD = """
QPushButton { background-color: #2E8B57; color: white; font-weight: bold; padding: 8px;
  border: 2px solid #1E6B47; border-radius: 5px; }
QPushButton:checked { background-color: #DC143C; border: 2px solid #B22222; }
QPushButton:hover { background-color: #3CB371; }
QPushButton:checked:hover { background-color: #FF4500; }
"""


def _spin(value, lo, hi, decimals=2):
    s = QDoubleSpinBox(); s.setRange(lo, hi); s.setDecimals(decimals); s.setValue(value)
    return s


class InstrumentPanel(QWidget):
    captured = pyqtSignal(object, object)      # (channels: dict, SweepConfig | None)
    log = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker = None
        self._is_busy = False
        self._devices: list[dict] = []
        self._gen_prefs = theme.load_settings().get("generator", {})
        self._periodic = QTimer(self); self._periodic.timeout.connect(self._periodic_tick)
        self._build_ui()
        QTimer.singleShot(0, self.detect)          # авто-скан при старте (в потоке)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        cols = QHBoxLayout(); root.addLayout(cols)
        cols.addWidget(self._generator_group(), 3)
        cols.addWidget(self._oscilloscope_group(), 3)
        cols.addWidget(self._control_group(), 2)
        cols.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.progress = QProgressBar(); root.addWidget(self.progress)

    def _generator_group(self) -> QGroupBox:
        g = QGroupBox("Генератор сигналов"); lay = QVBoxLayout(g)
        sel = QHBoxLayout(); sel.addWidget(QLabel("Генератор:"))
        self.generator_combo = QComboBox(); self.generator_combo.setMinimumWidth(220)
        sel.addWidget(self.generator_combo, 1); lay.addLayout(sel)
        p = self._gen_prefs; d = MeasurementParams()
        self.start_freq = _spin(p.get("start_freq", d.start_freq), 0, 1e9)
        self.end_freq = _spin(p.get("end_freq", d.end_freq), 0, 1e9)
        self.amplitude = _spin(p.get("amplitude", d.amplitude), 0, 100)
        self.offset = QDoubleSpinBox(); self.offset.setRange(-100, 100); self.offset.setDecimals(2)
        self.offset.setValue(p.get("offset", d.offset))
        self.sweep_time = _spin(p.get("sweep_time", d.sweep_time), 0.01, 1e6)
        form = QFormLayout()
        form.addRow("Начальная частота (Гц):", self.start_freq)
        form.addRow("Конечная частота (Гц):", self.end_freq)
        form.addRow("Амплитуда (В):", self.amplitude)
        form.addRow("Смещение (В):", self.offset)
        form.addRow("Время развёртки (сек):", self.sweep_time)
        lay.addLayout(form); lay.addStretch(1)
        return g

    def _oscilloscope_group(self) -> QGroupBox:
        g = QGroupBox("Осциллограф"); lay = QVBoxLayout(g)
        sel = QHBoxLayout(); sel.addWidget(QLabel("Осциллограф:"))
        self.oscilloscope_combo = QComboBox(); self.oscilloscope_combo.setMinimumWidth(220)
        sel.addWidget(self.oscilloscope_combo, 1); lay.addLayout(sel)
        self.read_btn = QPushButton("Прочитать данные с осциллографа")
        self.read_btn.clicked.connect(self.read); lay.addWidget(self.read_btn)

        rec = QGroupBox("Периодическая запись"); rl = QFormLayout(rec)
        self.poll_interval = _spin(5, 1, 3600, 0)
        rl.addRow("Период опроса (сек):", self.poll_interval)
        self.record_btn = QPushButton("⚫ Запуск периодической записи")
        self.record_btn.setCheckable(True); self.record_btn.setStyleSheet(BTN_RECORD)
        self.record_btn.toggled.connect(self._toggle_periodic)
        rl.addRow(self.record_btn)
        lay.addWidget(rec); lay.addStretch(1)
        return g

    def _control_group(self) -> QGroupBox:
        g = QGroupBox("Управление"); lay = QVBoxLayout(g)
        self.refresh_btn = QPushButton("Обновить список приборов")
        self.refresh_btn.clicked.connect(self.detect); lay.addWidget(self.refresh_btn)
        self.measure_btn = QPushButton("НАЧАТЬ ЗАПИСЬ")
        self.measure_btn.setStyleSheet(BTN_MEASURE); self.measure_btn.setMinimumHeight(46)
        self.measure_btn.clicked.connect(self.measure); lay.addWidget(self.measure_btn)
        self.stop_btn = QPushButton("ОСТАНОВИТЬ"); self.stop_btn.setStyleSheet(BTN_STOP)
        self.stop_btn.setEnabled(False); self.stop_btn.clicked.connect(self.stop)
        lay.addWidget(self.stop_btn)
        self.status = QLabel("Приборы: поиск…"); self.status.setWordWrap(True)
        lay.addWidget(self.status); lay.addStretch(1)
        return g

    # ---- обнаружение -------------------------------------------------------
    def detect(self) -> None:
        if self._is_busy:
            return
        self.refresh_btn.setEnabled(False); self.status.setText("Приборы: поиск…")
        self._worker = DetectWorker()
        self._worker.log.connect(self.log.emit)
        self._worker.found.connect(self._on_found)
        self._worker.start()

    def _on_found(self, devices: list) -> None:
        self._devices = devices
        self.refresh_btn.setEnabled(True)
        gens = [d for d in devices if Cap.GENERATOR in d.get("caps", set())]
        oscs = [d for d in devices if Cap.READ_WAVEFORM in d.get("caps", set())]
        self._fill_combo(self.generator_combo, gens)
        self._fill_combo(self.oscilloscope_combo, oscs)
        self.status.setText(f"Найдено: осциллографов {len(oscs)}, генераторов {len(gens)}")

    @staticmethod
    def _fill_combo(combo: QComboBox, devices: list) -> None:
        prev = combo.currentData()
        combo.clear()
        for d in devices:
            title = d.get("idn") or d.get("label") or d["kind"]
            combo.addItem(title, (d["kind"], d["resource"]))
        if prev is not None:                       # сохранить выбор, если остался
            idx = combo.findData(prev)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _osc(self):
        return self.oscilloscope_combo.currentData() or (None, None)

    def _gen(self):
        return self.generator_combo.currentData() or (None, None)

    def _sweep_cfg(self) -> SweepConfig:
        return SweepConfig(start_freq=self.start_freq.value(), end_freq=self.end_freq.value(),
                           sweep_time=self.sweep_time.value(), amplitude=self.amplitude.value(),
                           offset=self.offset.value())

    def _remember_generator(self) -> None:
        theme.save_settings({"generator": {
            "start_freq": self.start_freq.value(), "end_freq": self.end_freq.value(),
            "amplitude": self.amplitude.value(), "offset": self.offset.value(),
            "sweep_time": self.sweep_time.value()}})

    # ---- состояния кнопок (динамически) ------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._is_busy = busy
        self.measure_btn.setEnabled(not busy)
        self.read_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)
        self.record_btn.setEnabled(not busy or self.record_btn.isChecked())
        self.stop_btn.setEnabled(busy)

    # ---- действия ----------------------------------------------------------
    def measure(self) -> None:
        osc_kind, osc_res = self._osc(); gen_kind, gen_res = self._gen()
        if not osc_kind:
            self.log.emit("Осциллограф не выбран — обновите список приборов"); return
        if not gen_kind:
            self.log.emit("Генератор не выбран — обновите список приборов"); return
        cfg = self._sweep_cfg()
        if cfg.end_freq <= cfg.start_freq or cfg.sweep_time <= 0:
            self.log.emit("Неверные параметры: конечная частота и время развёртки"); return
        self._remember_generator()
        self._worker = MeasureWorker(osc_kind, osc_res, gen_kind, gen_res, cfg)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.log.connect(self.log.emit)
        self._worker.finished_ok.connect(lambda ch: self._done(ch, cfg))
        self._worker.failed.connect(self._failed)
        self._set_busy(True); self._worker.start()

    def read(self) -> None:
        osc_kind, osc_res = self._osc()
        if not osc_kind:
            self.log.emit("Осциллограф не выбран — обновите список приборов"); return
        self._worker = ReadWorker(osc_kind, osc_res)
        self._worker.log.connect(self.log.emit)
        self._worker.finished_ok.connect(lambda ch: self._done(ch, None))
        self._worker.failed.connect(self._failed)
        self._set_busy(True); self._worker.start()

    def stop(self) -> None:
        if isinstance(self._worker, MeasureWorker):
            self._worker.stop(); self.log.emit("Останавливаю измерение…")

    def _toggle_periodic(self, on: bool) -> None:
        self.record_btn.setText("⏹ Остановить запись" if on else "⚫ Запуск периодической записи")
        if on:
            self._periodic.start(int(self.poll_interval.value() * 1000))
            self.log.emit(f"Периодическая запись: период {self.poll_interval.value():.0f} с")
        else:
            self._periodic.stop(); self.log.emit("Периодическая запись остановлена")

    def _periodic_tick(self) -> None:
        if not self._is_busy:
            self.read()

    def _done(self, channels, cfg) -> None:
        self._set_busy(False); self.progress.setValue(0)
        if channels:
            self.captured.emit(channels, cfg)

    def _failed(self, msg: str) -> None:
        self._set_busy(False); self.progress.setValue(0)
        self.log.emit(f"Ошибка: {msg}")
