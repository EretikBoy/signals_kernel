"""
signals.contrib.inst_hantek
===========================

Драйвер осциллографа Hantek со встроенным DDS-генератором, и то и другое — в
одном файле-плагине, потому что в реальном приборе это один и тот же физический
блок. Биндинг написан по заголовкам SDK, которые лежат тут же в проекте:
HTHardDll.h / HTSoftDll.h / MeasDll.h / DefMacro.h, и по PDF-описаниям к ним
(таблицы развёрток и напряжений, формула пересчёта отсчётов в вольты, примеры
работы с DDS).

Важно про окружение:
* SDK Hantek — это Windows-DLL (`HTHardDll.dll`, вызовы `__stdcall`). На Linux
  такие DLL не запустить, а сайт Hantek недоступен из песочницы, так что
  поставить сюда «настоящий железный SDK» просто нельзя. И не нужно: бинарник
  требуется только в момент реальной работы с прибором, а сам биндинг написан
  по сигнатурам функций и подгружает DLL уже на машине пользователя — под
  Windows, через ctypes. Поэтому модуль спокойно импортируется на любой ОС;
  загрузка DLL отложена до вызова connect().
* Прибор объявляет capability GENERATOR — поэтому GUI сам покажет панель
  генератора, без правок в интерфейсе.

Прогнано на реальном приборе (USB DSO-6104BD): подключение, чтение каналов,
свип-захват с генератором — данные приходят в разумном виде, упаковка структур
(`_pack_`) оказалась верной как есть. Единственное, что осталось непроверенным —
пересчёт частоты дискретизации на быстрых развёртках (там, где деления идут в
микро- и наносекундах, — по документации нужна интерполяция из HTSoftDll). До
этого случая руки пока не дошли: в задачах калибровки антенн нужен только
звуковой диапазон, быстрые развёртки там просто не используются.
"""
from __future__ import annotations

import ctypes
import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..domain import Channel, ChannelMetadata
from ..extpoints import INSTRUMENTS
from ..instruments import InstrumentBase
from ..plugins.capabilities import Cap

DLL_NAME = "HTHardDll.dll"
MAX_CH_NUM = 4
_RECORD_LEN = 8192        # точек на канал (2 кан.×8192=16K ≤ 64K памяти) — лучше форма
_MAX_POINTS_PER_CH = 65536 // 2   # общая память прибора 64K делится между CH1 и CH2

# Таблица 1 (DefMacro/PDF): индекс развёртки → секунд/деление.
TIMEBASE_SECONDS = [
    2e-9, 5e-9, 10e-9, 20e-9, 50e-9, 100e-9, 200e-9, 500e-9,
    1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6, 100e-6, 200e-6, 500e-6,
    1e-3, 2e-3, 5e-3, 10e-3, 20e-3, 50e-3, 100e-3, 200e-3, 500e-3,
    1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0,
]
# Таблица 3: индекс напряжения → вольт/деление (1:1 пробник).
VOLT_PER_DIV = [
    2e-3, 5e-3, 10e-3, 20e-3, 50e-3, 100e-3,
    200e-3, 500e-3, 1.0, 2.0, 5.0, 10.0,
]

# Константы из DefMacro.h
RISE, FALL = 0, 1
EDGE = 0
DC, AC, GND = 0, 1, 2
YT_NORMAL = 0


class RELAYCONTROL(ctypes.Structure):
    # Соответствует _HT_RELAY_CONTROL; упаковка по умолчанию (_pack_ не задан) —
    # проверено на реальном приборе, DLL принимает структуру как есть.
    _fields_ = [
        ("bCHEnable", ctypes.c_uint32 * MAX_CH_NUM),
        ("nCHVoltDIV", ctypes.c_uint16 * MAX_CH_NUM),
        ("nCHCoupling", ctypes.c_uint16 * MAX_CH_NUM),
        ("bCHBWLimit", ctypes.c_uint32 * MAX_CH_NUM),
        ("nTrigSource", ctypes.c_uint16),
        ("bTrigFilt", ctypes.c_uint32),
        ("nALT", ctypes.c_uint16),
    ]


class CONTROLDATA(ctypes.Structure):
    _fields_ = [
        ("nCHSet", ctypes.c_uint16),
        ("nTimeDIV", ctypes.c_uint16),
        ("nTriggerSource", ctypes.c_uint16),
        ("nHTriggerPos", ctypes.c_uint16),
        ("nVTriggerPos", ctypes.c_uint16),
        ("nTriggerSlope", ctypes.c_uint16),
        ("nBufferLen", ctypes.c_uint32),
        ("nReadDataLen", ctypes.c_uint32),
        ("nAlreadyReadLen", ctypes.c_uint32),
        ("nALT", ctypes.c_uint16),
        ("nETSOpen", ctypes.c_uint16),
        ("nDriverCode", ctypes.c_uint16),
        ("nLastAddress", ctypes.c_uint32),
        ("nFPGAVersion", ctypes.c_uint16),
    ]


def _bitness() -> int:
    return struct.calcsize("P") * 8          # 32 или 64


def _arch_dir() -> str:
    return "x64" if _bitness() == 64 else "x86"


def _settings_dll_dir() -> list[Path]:
    try:
        data = json.loads((Path.home() / ".signals" / "settings.json").read_text("utf-8"))
        d = data.get("hantek_dll_dir")
        return [Path(d)] if d else []
    except Exception:
        return []


def _candidate_dll_dirs() -> list[Path]:
    """Где ищем HTHardDll.dll, по приоритету (учёт разрядности Python)."""
    arch = _arch_dir()
    dirs: list[Path] = []
    env = os.environ.get("HANTEK_DLL_DIR")
    if env:
        dirs += [Path(env), Path(env) / arch]
    dirs += _settings_dll_dir()
    exe_dir = Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else Path.cwd()
    pkg = Path(__file__).resolve().parent / "hantek_dll"
    dirs += [
        pkg / arch, pkg,                                  # в составе пакета
        exe_dir / "drivers" / arch, exe_dir / "drivers",  # рядом с приложением
        exe_dir, Path.cwd(),                              # просто рядом / в CWD
    ]
    seen, out = set(), []
    for d in dirs:
        if d and str(d) not in seen:
            seen.add(str(d)); out.append(d)
    return out


def _find_dll() -> Path | None:
    for d in _candidate_dll_dirs():
        p = d / DLL_NAME
        if p.exists():
            return p
    return None


def _load_dll() -> ctypes.CDLL:
    """Ленивая загрузка DLL (с учётом разрядности) и объявление прототипов.

    Бросает понятную ошибку, если DLL не найдена или её разрядность не совпадает с
    Python — чтобы пользователь сразу понял, что делать (см. journal/README).
    """
    if sys.platform != "win32":
        raise RuntimeError(
            "Hantek SDK (HTHardDll.dll) работает только под Windows. "
            "Модуль импортируется на любой ОС, но connect()/поиск требуют Windows + DLL."
        )
    path = _find_dll()
    if path is None:
        searched = "; ".join(str(d) for d in _candidate_dll_dirs())
        raise RuntimeError(
            f"{DLL_NAME} не найдена для {_bitness()}-битного Python. "
            f"Положите {_bitness()}-битные DLL Hantek (HT*.dll) в папку "
            f"hantek_dll/{_arch_dir()} (или укажите папку через меню «Приборы»). "
            f"Искал в: {searched}"
        )
    try:
        os.add_dll_directory(str(path.parent))   # чтобы подтянулись зависимые DLL
    except Exception:
        pass
    try:
        dll = ctypes.WinDLL(str(path))
    except OSError as exc:
        if getattr(exc, "winerror", None) == 193:     # ERROR_BAD_EXE_FORMAT
            raise RuntimeError(
                f"{DLL_NAME} найдена ({path}), но её разрядность не совпадает с Python "
                f"({_bitness()}-bit). Нужна {_bitness()}-битная DLL, либо запустите Python "
                f"другой разрядности (SDK Hantek часто 32-битный → 32-битный Python)."
            ) from exc
        raise

    W, S, F = ctypes.c_uint16, ctypes.c_int16, ctypes.c_float
    UL, US = ctypes.c_uint32, ctypes.c_uint16
    PW = ctypes.POINTER(W)

    dll.dsoHTSearchDevice.argtypes = [ctypes.POINTER(S)]; dll.dsoHTSearchDevice.restype = W
    dll.dsoHTDeviceConnect.argtypes = [W]; dll.dsoHTDeviceConnect.restype = W
    dll.dsoInitHard.argtypes = [W]; dll.dsoInitHard.restype = W
    dll.dsoHTADCCHModGain.argtypes = [W, W]; dll.dsoHTADCCHModGain.restype = W
    dll.dsoHTSetSampleRate.argtypes = [W, W, ctypes.POINTER(RELAYCONTROL), ctypes.POINTER(CONTROLDATA)]
    dll.dsoHTSetSampleRate.restype = W
    dll.dsoHTSetCHAndTrigger.argtypes = [W, ctypes.POINTER(RELAYCONTROL), W]; dll.dsoHTSetCHAndTrigger.restype = W
    dll.dsoHTSetRamAndTrigerControl.argtypes = [W, W, W, W, W]; dll.dsoHTSetRamAndTrigerControl.restype = W
    dll.dsoHTSetTrigerMode.argtypes = [W, W, W, W]; dll.dsoHTSetTrigerMode.restype = W
    dll.dsoHTSetCHPos.argtypes = [W, W, W, W, W]; dll.dsoHTSetCHPos.restype = W
    dll.dsoHTSetVTriggerLevel.argtypes = [W, W, W]; dll.dsoHTSetVTriggerLevel.restype = W
    dll.dsoHTStartCollectData.argtypes = [W, W]; dll.dsoHTStartCollectData.restype = W
    dll.dsoHTGetState.argtypes = [W]; dll.dsoHTGetState.restype = W
    dll.dsoHTSetHTriggerLength.argtypes = [W, ctypes.POINTER(CONTROLDATA), W]; dll.dsoHTSetHTriggerLength.restype = W
    dll.dsoHTGetData.argtypes = [W, PW, PW, PW, PW, ctypes.POINTER(CONTROLDATA)]; dll.dsoHTGetData.restype = W
    dll.dsoHTSetPeakDetect.argtypes = [W, W, W]; dll.dsoHTSetPeakDetect.restype = W
    dll.dsoHTClosePeakDetect.argtypes = [W]; dll.dsoHTClosePeakDetect.restype = W
    # DDS / встроенный генератор
    dll.ddsSetCmd.argtypes = [W, US]; dll.ddsSetCmd.restype = UL
    dll.ddsSetOnOff.argtypes = [W, S]; dll.ddsSetOnOff.restype = UL
    dll.ddsEmitSingle.argtypes = [W]; dll.ddsEmitSingle.restype = UL
    dll.ddsSDKSetFre.argtypes = [W, F]; dll.ddsSDKSetFre.restype = F
    dll.ddsSDKSetAmp.argtypes = [W, W]; dll.ddsSDKSetAmp.restype = W
    dll.ddsSDKSetOffset.argtypes = [W, S]; dll.ddsSDKSetOffset.restype = S
    dll.ddsSDKSetWaveType.argtypes = [W, W]; dll.ddsSDKSetWaveType.restype = W
    dll.ddsSDKSetBurstNum.argtypes = [W, W]; dll.ddsSDKSetBurstNum.restype = W
    return dll


_WAVE_TYPES = {"SIN": 0, "RAMP": 1, "SQUARE": 2, "DC": 4, "NOISE": 8}


@INSTRUMENTS.register(
    "hantek",
    label="Hantek (HTHardDll, со встроенным генератором)",
    kind="oscilloscope+generator",
    caps={Cap.READ_WAVEFORM, Cap.SET_TIMEBASE, Cap.SET_POINTS, Cap.GENERATOR, Cap.BURST},
)
class HantekScope(InstrumentBase):
    """Осциллограф Hantek + DDS. Реализует протоколы Oscilloscope и Generator."""

    CAPABILITIES = frozenset(
        {Cap.READ_WAVEFORM, Cap.SET_TIMEBASE, Cap.SET_POINTS, Cap.GENERATOR, Cap.BURST}
    )
    USES_VISA = False                      # ищется не через VISA, а по USB-индексам

    @staticmethod
    def discover(log=None) -> list[dict]:
        """Просканировать USB-индексы 0..31 и вернуть найденные приборы Hantek.

        Пишет в журнал (log) причину: не Windows / DLL не найдена / разрядность /
        устройства не отвечают — чтобы было видно, почему прибор не обнаружен.
        """
        emit = log or (lambda *_: None)
        if sys.platform != "win32":
            emit("Hantek: не Windows — поиск пропущен"); return []
        try:
            dll = _load_dll()
        except Exception as exc:                       # noqa: BLE001
            emit(f"Hantek: {exc}"); return []          # понятная причина в журнал
        path = _find_dll()
        emit(f"Hantek: DLL загружена ({_bitness()}-bit): {path}; опрос USB 0..31")

        def _text(fn_name: str, index: int) -> str:
            try:
                fn = getattr(dll, fn_name)
                fn.argtypes = [ctypes.c_uint16, ctypes.POINTER(ctypes.c_ubyte)]
                fn.restype = ctypes.c_int
                buf = (ctypes.c_ubyte * 64)()
                fn(index, buf)
                return bytes(buf).split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
            except Exception:
                return ""

        devices: list[dict] = []
        for i in range(32):
            try:
                if dll.dsoHTDeviceConnect(i):
                    name = _text("dsoGetDeviceName", i) or "Hantek"
                    sn = _text("dsoGetDeviceSN", i)
                    idn = f"{name} {('SN:' + sn) if sn else ''} (USB#{i})".strip()
                    emit(f"Hantek: найден прибор {idn}")
                    devices.append({"resource": str(i), "idn": idn})
            except Exception:                          # noqa: BLE001
                continue
        if not devices:
            emit("Hantek: устройства не ответили на dsoHTDeviceConnect "
                 "(проверьте подключение, питание и USB-драйвер прибора)")
        return devices

    def __init__(self, resource: str = "0") -> None:
        # resource — индекс устройства (0..31); строкой для единообразия с VISA.
        self._index = int(resource) if str(resource).isdigit() else 0
        self._dll: Any = None
        self._timebase_index = 9          # 2 мкс/дел по умолчанию
        self._ch_count = 2                # строим/возвращаем CH1, CH2 (драйв + отклик)
        self._ch_mode = 4                 # режим каналов прибора (как в оригинале Hard.cpp)
        self._positions = [128] * MAX_CH_NUM
        self._volt_index = [7, 7, 7, 7]   # 500 мВ/дел (как в рабочем наборе пользователя)
        self._relay = RELAYCONTROL()
        self._control = CONTROLDATA()
        self.window_seconds: float | None = None
        self.log = lambda *a: None        # журнал шагов (ставит worker)

    # ---- соединение --------------------------------------------------------
    def connect(self) -> None:
        self._dll = _load_dll()

        # Поиск устройства (как в исходном Hard::FindeDev)
        info = (ctypes.c_int16 * 32)()
        self._dll.dsoHTSearchDevice(info)
        found = next((i for i in range(32) if info[i] == 1), None)
        if found is None:
            # запасной перебор через DeviceConnect
            found = next((i for i in range(32) if self._dll.dsoHTDeviceConnect(i)), None)
        if found is None:
            raise RuntimeError("Hantek: устройство не найдено")
        self._index = found
        self.log(f"Hantek: устройство #{found}, инициализация прибора…")

        self._init_relay_and_control()
        self._dll.dsoInitHard(self._index)
        self._dll.dsoHTADCCHModGain(self._index, self._ch_mode)
        self._dll.dsoHTSetSampleRate(self._index, YT_NORMAL, ctypes.byref(self._relay), ctypes.byref(self._control))
        self._dll.dsoHTSetCHAndTrigger(self._index, ctypes.byref(self._relay), self._timebase_index)
        try:                                  # глубина захвата (8192) в железо
            self._dll.dsoHTSetHTriggerLength(self._index, ctypes.byref(self._control), self._ch_mode)
        except Exception as exc:              # noqa: BLE001
            self.log(f"Hantek: глубину захвата задать не удалось ({exc}) — длина по умолчанию")
        self._dll.dsoHTSetRamAndTrigerControl(self._index, self._timebase_index, self._control.nCHSet, 0, 0)
        for ch in range(MAX_CH_NUM):
            self._dll.dsoHTSetCHPos(self._index, self._volt_index[ch], self._positions[ch], ch, self._ch_mode)
        self._dll.dsoHTSetVTriggerLevel(self._index, self._positions[0], 4)
        self._dll.dsoHTSetTrigerMode(self._index, EDGE, RISE, DC)
        self.log(f"Hantek: готов (каналов {self._ch_count}, развёртка idx={self._timebase_index}, "
                 f"длина {self._control.nReadDataLen})")

    def disconnect(self) -> None:
        self._dll = None

    def _init_relay_and_control(self) -> None:
        for ch in range(MAX_CH_NUM):
            self._relay.bCHEnable[ch] = 1 if ch < self._ch_count else 0   # CH1,CH2 вкл
            self._relay.nCHVoltDIV[ch] = self._volt_index[ch]
            self._relay.nCHCoupling[ch] = AC
            self._relay.bCHBWLimit[ch] = 0
        self._relay.nTrigSource = 0
        self._relay.bTrigFilt = 0
        self._relay.nALT = 0
        self._control.nCHSet = 0x03        # включены CH1 и CH2
        self._control.nTimeDIV = self._timebase_index
        self._control.nTriggerSource = 0
        self._control.nHTriggerPos = 50
        self._control.nVTriggerPos = 64
        self._control.nTriggerSlope = RISE
        self._control.nBufferLen = _RECORD_LEN
        self._control.nReadDataLen = _RECORD_LEN
        self._control.nAlreadyReadLen = _RECORD_LEN
        self._control.nFPGAVersion = 0xA000

    @property
    def channel_count(self) -> int:
        return self._ch_count

    # ---- чтение осциллограммы ---------------------------------------------
    def start_acquisition(self) -> None:
        self.log("Hantek: запуск сбора (AUTO)…")
        self._dll.dsoHTStartCollectData(self._index, 1)

    def _wait_done(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._dll.dsoHTGetState(self._index) & 0x02:   # бит 1 — сбор завершён
                return True
            time.sleep(0.02)
        return False

    def _read_buffers(self) -> dict[str, Channel]:
        n = self._control.nReadDataLen
        buffers = [(ctypes.c_uint16 * n)() for _ in range(MAX_CH_NUM)]
        self._dll.dsoHTGetData(
            self._index, buffers[0], buffers[1], buffers[2], buffers[3],
            ctypes.byref(self._control))
        dt = TIMEBASE_SECONDS[self._timebase_index] / 250.0
        channels: dict[str, Channel] = {}
        for ch in range(self._ch_count):
            raw = np.frombuffer(buffers[ch], dtype=np.uint16, count=n).astype(np.float64)
            if ch < 2:
                self.log(f"Hantek: CH{ch + 1} сырые отсчёты min={raw.min():.0f} "
                         f"max={raw.max():.0f} (норма 1..254)")
            volts = (raw - self._positions[ch]) / 32.0 * VOLT_PER_DIV[self._volt_index[ch]]
            t = np.arange(n) * dt
            name = f"CH{ch + 1}"
            channels[name] = Channel(
                name=name, time=t, amplitude=volts,
                metadata=ChannelMetadata(
                    record_length=n, sample_interval=dt,
                    vertical_scale=VOLT_PER_DIV[self._volt_index[ch]], source_label=name))
        return channels

    def read_all(self) -> dict[str, Channel]:
        """Однократное чтение (кнопка «Прочитать данные»): запуск+ожидание+чтение."""
        self.start_acquisition()
        if not self._wait_done():
            self.log("Hantek: таймаут готовности (нет триггера?) — читаю как есть")
        return self._read_buffers()

    def read_captured(self) -> dict[str, Channel]:
        """Прочитать уже запущенный кадр (после свипа): ждём ВСЁ окно и читаем."""
        timeout = (self.window_seconds or 5.0) + 3.0
        if not self._wait_done(timeout=timeout):
            self.log("Hantek: кадр ещё не готов — читаю как есть")
        return self._read_buffers()

    # ---- пик-детектор и окно развёртки ------------------------------------
    def set_peak_detect(self, on: bool) -> None:
        if not self._dll:
            return
        if on:
            self._dll.dsoHTSetPeakDetect(self._index, self._timebase_index, YT_NORMAL)
            self.log("Hantek: пик-детектор ВКЛ")
        else:
            self._dll.dsoHTClosePeakDetect(self._index)

    def set_timebase_for_window(self, seconds: float) -> None:
        """Подобрать развёртку и длину записи так, чтобы окно совпало со временем свипа.

        Раньше длина записи была зафиксирована (8192 точек), и под неё подбиралась
        ближайшая подходящая развёртка — а соседние развёртки отличаются по
        длительности окна почти вдвое, так что окно могло почти вдвое превысить
        нужное время (свип на 34 с превращался в запись на 66 с). Вместо этого
        перебираем развёртки от самой быстрой к медленной и для каждой считаем
        минимальную длину записи, при которой окно (n×dt) уже не меньше нужного —
        и берём первую, что укладывается в память прибора (на канал ≤ 32768 точек
        при двух включённых каналах). У неё и шаг времени мельче (точек больше —
        кривая подробнее), и окно ближе всего к запрошенному: превышение не
        больше одного шага дискретизации, а не половины развёртки.
        """
        seconds = max(seconds, 0.0)
        for idx, tb in enumerate(TIMEBASE_SECONDS):
            dt = tb / 250.0
            n = max(int(np.ceil(seconds / dt)), 1)
            # выровнять ВВЕРХ до кратного 512 — аппаратное требование к nBufferLen
            # (см. докстринг set_record_length); вниз нельзя — тогда реальный кадр
            # окажется короче запрошенного окна (29.7 c вместо 30 c и т.п.), а
            # round-трип через _MAX_POINTS_PER_CH ниже гарантирует, что выровненная
            # длина ещё умещается в память прибора, прежде чем мы её зафиксируем
            n = (n + 511) // 512 * 512
            if n <= _MAX_POINTS_PER_CH:
                actual_n = self.set_record_length(n)
                self.set_timebase(tb)
                self.window_seconds = actual_n * dt
                self.log(f"Hantek: развёртка под окно {seconds:.0f} c → idx={idx} "
                         f"({tb:g} с/дел, {actual_n} точек, окно ≈ {self.window_seconds:.1f} c)")
                return
        # нужное окно больше, чем прибор способен записать одним кадром даже на
        # самой медленной развёртке — берём предельный вариант как есть
        idx = len(TIMEBASE_SECONDS) - 1
        tb = TIMEBASE_SECONDS[idx]
        dt = tb / 250.0
        actual_n = self.set_record_length(_MAX_POINTS_PER_CH)
        self.set_timebase(tb)
        self.window_seconds = actual_n * dt
        self.log(f"Hantek: окно {seconds:.0f} c больше предела прибора — записываю "
                 f"{self.window_seconds:.0f} c ({tb:g} с/дел, {actual_n} точек)")

    def read_channel(self, n: int) -> Channel | None:
        return self.read_all().get(f"CH{n}")

    # ---- управление развёрткой (TODO #4) ----------------------------------
    def set_timebase(self, seconds_per_div: float) -> None:
        self._timebase_index = int(np.argmin([abs(v - seconds_per_div) for v in TIMEBASE_SECONDS]))
        self._control.nTimeDIV = self._timebase_index
        if self._dll:
            self._dll.dsoHTSetSampleRate(self._index, YT_NORMAL, ctypes.byref(self._relay), ctypes.byref(self._control))
            # Перепрограммировать глубину захвата в железе под текущие nBufferLen/
            # nReadDataLen — иначе прибор продолжает писать кадры старой длины
            # (см. set_record_length) и dsoHTGetData читает за пределы буфера DLL.
            try:
                self._dll.dsoHTSetHTriggerLength(self._index, ctypes.byref(self._control), self._ch_mode)
            except Exception as exc:                       # noqa: BLE001
                self.log(f"Hantek: глубину захвата перепрограммировать не удалось ({exc})")
            self._dll.dsoHTSetRamAndTrigerControl(self._index, self._timebase_index, self._control.nCHSet, 0, 0)

    def set_record_length(self, points: int) -> int:
        """Задать длину записи (точек на канал) в структуре управления.

        По SDK (HTHardDll.h, комментарий к dsoHTSetHTriggerLength) nBufferLen —
        это глубина захвата в самом приборе и должна быть кратна 512 (и не более
        16М). Округляем ВВЕРХ до ближайшего кратного 512 (вниз нельзя — кадр
        получится короче запрошенного окна), а затем подрезаем до памяти прибора.
        Без выравнивания прибор получает «сырое» значение, аппаратно захватывает
        кадр другой длины, а dsoHTGetData копирует nReadDataLen точек из буфера
        другого размера — выход за границы памяти DLL и аварийное завершение
        процесса без traceback. Реальное перепрограммирование глубины
        (dsoHTSetHTriggerLength) выполняется в set_timebase — его обязательно
        вызывают сразу после смены длины записи (см. set_timebase_for_window и
        эталонный SDK Hantek6104BDPYLib/hantek_control.py: nBufferLen/
        nReadDataLen/nAlreadyReadLen всегда обновляются синхронно перед
        dsoHTSetSampleRate + dsoHTSetHTriggerLength).
        """
        points = max(1, int(points))
        points = (points + 511) // 512 * 512
        points = min(points, _MAX_POINTS_PER_CH)
        self._control.nBufferLen = points
        self._control.nReadDataLen = points
        self._control.nAlreadyReadLen = points
        return points

    # ---- встроенный генератор (DDS) ---------------------------------------
    def configure_sweep(self, *, start: float, stop: float, seconds: float,
                        amplitude: float, offset: float, function: str = "SIN") -> None:
        # Порядок как в примере SDK: сначала режим (непрерывный), затем частота,
        # амплитуда (мВ), смещение (мВ), тип волны. Свип ведёт сервис (set_frequency).
        self._dll.ddsSetCmd(self._index, 0)                            # 0 — непрерывный
        self._dll.ddsSDKSetFre(self._index, ctypes.c_float(start))
        self._dll.ddsSDKSetAmp(self._index, int(amplitude * 1000))     # мВ (1 В → 1000)
        self._dll.ddsSDKSetOffset(self._index, int(offset * 1000))     # мВ
        self._dll.ddsSDKSetWaveType(self._index, _WAVE_TYPES.get(function.upper(), 0))
        self.log(f"Hantek DDS: {function}, {amplitude:g} В, старт {start:.0f} Гц")

    def set_frequency(self, freq: float) -> None:
        """Шаг свипа: вызывается сервисом измерения для программной развёртки."""
        self._dll.ddsSDKSetFre(self._index, ctypes.c_float(freq))

    def set_output(self, on: bool) -> None:
        # В примере кода из SDK выход включается вызовом ddsSetOnOff(index, 1);
        # текстовое описание в PDF утверждает обратное, но это ошибка в документе —
        # рабочему примеру тут стоит доверять больше, чем описанию рядом с ним.
        self._dll.ddsSetOnOff(self._index, 1 if on else 0)
        self.log(f"Hantek DDS: выход {'ВКЛ' if on else 'выкл'}")
