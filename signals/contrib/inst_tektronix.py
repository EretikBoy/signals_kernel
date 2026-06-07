"""
Регистрация существующих приборов (Tektronix-осциллограф, Rigol-генератор) как
плагинов. Тяжёлые зависимости (pyvisa / tm_devices) импортируются лениво внутри
connect(), чтобы модуль грузился где угодно.

Набор взаимодействий перенесён из старого приложения (app/modules/tektronixprovider.py
и app/modules/rigolprovider.py — см. github.com/EretikBoy/signals) и сверен с
официальной документацией:
* Tektronix — пакет tm_devices (DeviceManager.add_scope, дерево SCPI-команд
  scope.commands.*, низкоуровневые write/read_raw для бинарной передачи кривой);
* Rigol DG — Programming Guide серии DG1000Z/DG2000 (подсистема SOURce:*,
  по интерфейсу VISA «как есть», без обёрток — у генератора нет команд для
  чтения осциллограмм, только настройка и запуск).
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..domain import Channel, ChannelMetadata
from ..extpoints import INSTRUMENTS
from ..instruments import InstrumentBase
from ..plugins.capabilities import Cap


@INSTRUMENTS.register(
    "tektronix",
    label="Tektronix MDO/DPO/MSO",
    kind="oscilloscope",
    caps={Cap.READ_WAVEFORM, Cap.SET_TIMEBASE, Cap.SET_ACQ_MODE, Cap.SET_POINTS, Cap.READ_LABEL},
)
class TektronixScope(InstrumentBase):
    """Осциллограф Tektronix через tm_devices (PyVISA под капотом).

    Чтение осциллограммы — по тому же протоколу, что и в старом провайдере:
    канал переключается в двоичную выдачу (RIBINARY, 2 байта/отсчёт),
    `CURVe?` отдаёт IEEE-блок `#<n><len><байты>`, а параметры WFMOutpre
    (ymult/yzero/yoff/xincr) переводят коды АЦП в вольты и секунды.
    """

    CAPABILITIES = frozenset(
        {Cap.READ_WAVEFORM, Cap.SET_TIMEBASE, Cap.SET_ACQ_MODE, Cap.SET_POINTS, Cap.READ_LABEL}
    )
    USES_VISA = True
    IDN_KEYWORDS = ("TEKTRONIX", "TEKTRONIK", "TEK ")

    # Имена режимов сбора (ACQuire:MODe) — пользователь может писать как в меню
    # прибора (Sample, Peak Detect, Hi Res, Average, Envelope) или сокращённо.
    _ACQ_MODES = {
        "SAMPLE": "SAMPLE", "SAM": "SAMPLE",
        "PEAK": "PEAKDETECT", "PEAKDETECT": "PEAKDETECT", "PEAKDET": "PEAKDETECT",
        "HIRES": "HIRES", "HI RES": "HIRES",
        "AVERAGE": "AVERAGE", "AVE": "AVERAGE",
        "ENVELOPE": "ENVELOPE", "ENV": "ENVELOPE",
    }

    @classmethod
    def matches_idn(cls, idn: str) -> bool:
        up = (idn or "").upper()
        return any(k in up for k in cls.IDN_KEYWORDS)

    def __init__(self, resource: str) -> None:
        self.resource = resource
        self._dm: Any = None
        self._scope: Any = None
        self.log = lambda *a: None        # журнал шагов (ставит worker)

    # ---- соединение --------------------------------------------------------
    def connect(self) -> None:
        from tm_devices import DeviceManager        # ленивый импорт тяжёлой зависимости
        self._dm = DeviceManager(verbose=False)
        self._scope = self._dm.add_scope(self.resource)
        self.log(f"Tektronix: подключен — {self._scope.model} "
                 f"({self._scope.total_channels} канал(ов))")

    def disconnect(self) -> None:
        if self._dm is not None:
            self._dm.remove_all_devices()
            self._dm.close()
        self._dm = None
        self._scope = None

    @property
    def channel_count(self) -> int:
        return int(self._scope.total_channels) if self._scope is not None else 0

    # ---- чтение осциллограммы -----------------------------------------------
    def _channel_on(self, n: int) -> bool:
        resp = self._scope.commands.select.ch[n].query().strip().upper()
        return resp in ("1", "ON")

    def read_channel_label(self, n: int) -> str:
        """LABEL канала из меню прибора (CH<n>:LABel) — пользовательское имя сигнала."""
        if self._scope is None:
            return ""
        try:
            return self._scope.commands.ch[n].label.query().strip().strip('"')
        except Exception:                            # noqa: BLE001 — нет такого канала/команды
            return ""

    def read_channel(self, n: int) -> Channel | None:
        if self._scope is None or not (1 <= n <= self.channel_count):
            return None
        if not self._channel_on(n):
            return None
        sc = self._scope

        # двоичная выдача: знаковые 16-битные отсчёты, big-endian (как в IEEE 488.2)
        sc.commands.data.source.write(f"CH{n}")
        sc.commands.data.encdg.write("RIBINARY")
        sc.commands.data.width.write(2)
        sc.commands.data.start.write(1)
        record_length = int(sc.commands.horizontal.recordlength.query())
        sc.commands.data.stop.write(record_length)

        ymult = float(sc.commands.wfmoutpre.ymult.query())
        yzero = float(sc.commands.wfmoutpre.yzero.query())
        yoff = float(sc.commands.wfmoutpre.yoff.query())
        xincr = float(sc.commands.wfmoutpre.xincr.query())

        sc.write("CURVe?")
        raw = sc.read_raw()
        if not raw.startswith(b"#"):
            self.log(f"Tektronix: CH{n} — неожиданный ответ на CURVe? (нет заголовка '#')")
            return None
        n_digits = int(raw[1:2])
        data_length = int(raw[2:2 + n_digits])
        header = 2 + n_digits
        codes = np.frombuffer(raw[header:header + data_length], dtype=">i2").astype(np.float64)

        amplitude = (codes - yoff) * ymult + yzero
        t = np.arange(codes.size) * xincr
        name = f"CH{n}"
        label = self.read_channel_label(n)
        return Channel(
            name=name, time=t, amplitude=amplitude,
            metadata=ChannelMetadata(record_length=codes.size, sample_interval=xincr,
                                     vertical_scale=ymult, source_label=label or name))

    def read_all(self) -> dict[str, Channel]:
        out: dict[str, Channel] = {}
        for n in range(1, self.channel_count + 1):
            ch = self.read_channel(n)
            if ch is not None:
                out[ch.name] = ch
        return out

    # ---- управление разврёрткой и сбором ------------------------------------
    def set_timebase(self, seconds_per_div: float) -> None:
        self._scope.commands.horizontal.scale.write(seconds_per_div)
        self.log(f"Tektronix: развёртка {seconds_per_div:g} с/дел")

    def set_acquisition_mode(self, mode: str) -> None:
        scpi = self._ACQ_MODES.get(mode.strip().upper(), mode.strip().upper())
        self._scope.commands.acquire.mode.write(scpi)
        self.log(f"Tektronix: режим сбора {scpi}")

    def set_record_length(self, points: int) -> None:
        self._scope.commands.horizontal.recordlength.write(points)
        self.log(f"Tektronix: длина записи {points} точек")


@INSTRUMENTS.register(
    "rigol",
    label="Rigol DG (генератор)",
    kind="generator",
    caps={Cap.GENERATOR, Cap.SWEEP},
)
class RigolGenerator(InstrumentBase):
    """Генератор Rigol DG (серии DG1000Z/DG2000/DG800) — настройка через SCPI.

    Аппаратный линейный свип ведёт сам прибор (SOURce:SWEep): задаём границы,
    время и тип развёртки один раз, а дальше только включаем/выключаем выход —
    в отличие от Hantek с его DDS, здесь не нужен пошаговый set_frequency.
    """

    CAPABILITIES = frozenset({Cap.GENERATOR, Cap.SWEEP})
    USES_VISA = True
    IDN_KEYWORDS = ("RIGOL",)

    _FUNCTIONS = ("SIN", "SQUARE", "RAMP", "PULSE", "NOISE", "ARB", "DC")

    @classmethod
    def matches_idn(cls, idn: str) -> bool:
        return any(k in (idn or "").upper() for k in cls.IDN_KEYWORDS)

    def __init__(self, resource: str) -> None:
        self.resource = resource
        self._inst: Any = None
        self.log = lambda *a: None        # журнал шагов (ставит worker)

    # ---- соединение --------------------------------------------------------
    def connect(self) -> None:
        import pyvisa                                # ленивый импорт
        self._inst = pyvisa.ResourceManager().open_resource(self.resource)
        idn = self._inst.query("*IDN?").strip()
        self.log(f"Rigol: подключен — {idn}")

    def disconnect(self) -> None:
        if self._inst is not None:
            self._inst.close()
        self._inst = None

    def _write(self, cmd: str) -> None:
        self._inst.write(cmd)
        time.sleep(0.05)         # приборам Rigol нужна пауза между командами SCPI

    # ---- настройка и запуск свипа -------------------------------------------
    def configure_sweep(self, *, start: float, stop: float, seconds: float,
                        amplitude: float, offset: float, function: str = "SIN") -> None:
        # Порядок команд — как в проверенном на железе старом провайдере:
        # сначала форма сигнала и амплитуда/смещение, затем параметры развёртки,
        # и в конце — включение режима свипа (SWEep:STATe ON), которое запускает
        # генерацию по границам, заданным FREQuency:STARt/STOP и SWEep:TIME.
        fn = function.strip().upper()
        if fn not in self._FUNCTIONS:
            fn = "SIN"
        self._write(f"FUNC {fn}")
        self._write(f"VOLT {amplitude:g}")
        self._write(f"VOLT:OFFS {offset:g}")
        self._write("SWE:SPAC LIN")
        self._write(f"FREQ:STAR {start:g}")
        self._write(f"FREQ:STOP {stop:g}")
        self._write(f"SWE:TIME {seconds:g}")
        self._write("TRIG:SOUR IMM")
        self._write("SWE:STAT ON")
        self.log(f"Rigol: свип {start:g}→{stop:g} Гц за {seconds:g} c "
                 f"({fn}, {amplitude:g} В, смещение {offset:g} В)")

    def set_output(self, on: bool) -> None:
        self._write(f"OUTP {'ON' if on else 'OFF'}")
        self.log(f"Rigol: выход {'ВКЛ' if on else 'выкл'}")
