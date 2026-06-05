"""
signals.services.measurement
============================

Сценарий измерения АЧХ: генератор делает свип за ВРЕМЯ РАЗВЁРТКИ (sweep_time),
осциллограф снимает отклик. Как в оригинале — свип задаётся временем, а не числом
точек. Осциллограф и генератор — РАЗДЕЛЬНЫЕ приборы (у Hantek это один прибор,
тогда оба ссылаются на него же).

Внутри для PC-USB прибора частота меняется небольшими шагами в пределах sweep_time
(аппаратный линейный свип HTHardDll не выверен без железа); число шагов скрыто от
пользователя. Результат — Channel с осью времени 0..sweep_time, которую движок
линейно отображает в частоту, поэтому весь конвейер работает без изменений.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..domain import Channel, ChannelMetadata
from ..instruments import Generator, Oscilloscope
from ..plugins.capabilities import Cap, supports


@dataclass
class SweepConfig:
    start_freq: float = 100.0
    end_freq: float = 1000.0
    sweep_time: float = 30.0          # время развёртки генератора, с
    amplitude: float = 1.0
    offset: float = 0.0
    function: str = "SIN"
    points: int = 300                 # внутреннее разрешение свипа (в UI не показывается)
    pre_roll: float = 1.0             # запись ~1 c ДО подачи сигнала (виден фронт)


ProgressFn = Callable[[int, str], None]


class MeasurementService:
    def __init__(self, scope, generator=None) -> None:
        self.scope: Oscilloscope = scope
        self.generator: Generator = generator if generator is not None else scope

    def run(self, cfg: SweepConfig, *, progress=None, log=None,
            should_stop=None) -> dict[str, Channel]:
        """Снять АЧХ: генератор «качает» частоту start→stop за sweep_time, осциллограф
        в режиме пик-детектора снимает ОДИН длинный кадр (окно ≥ sweep_time).

        Возвращает сырые осциллограммы CH1..CH4 (CH1 — сигнал генератора для
        определения фронта, CH2 — отклик). АЧХ из них строит движок analyze().
        """
        prog = progress or (lambda p: None)
        say = log or (lambda m: None)
        stop = should_stop or (lambda: False)
        if not supports(self.generator, Cap.GENERATOR):
            raise RuntimeError("Прибор не поддерживает генератор — измерение свипом невозможно")

        # 1) осциллограф: развёртка под окно ≥ (предзапись + время свипа) + пик-детектор
        total = cfg.sweep_time + max(cfg.pre_roll, 0.0)
        if hasattr(self.scope, "set_timebase_for_window"):
            self.scope.set_timebase_for_window(total)
        if hasattr(self.scope, "set_peak_detect"):
            self.scope.set_peak_detect(True)
        say(f"Свип {cfg.start_freq:.0f}→{cfg.end_freq:.0f} Гц за {cfg.sweep_time:g} c "
            f"(предзапись {cfg.pre_roll:g} c, пик-детектор, один кадр)")

        # 2) генератор: параметры сигнала (выход пока ВЫКЛ — пишем базовый уровень)
        self.generator.configure_sweep(
            start=cfg.start_freq, stop=cfg.end_freq, seconds=cfg.sweep_time,
            amplitude=cfg.amplitude, offset=cfg.offset, function=cfg.function)
        self.generator.set_output(False)
        set_freq = getattr(self.generator, "set_frequency", None)

        output_on = False
        try:
            # 3) запускаем ОДНО длинное измерение (захват начинается ДО сигнала)
            if hasattr(self.scope, "start_acquisition"):
                self.scope.start_acquisition()
            # 4) предзапись (генератор молчит) → включаем генератор → чирп → удержание
            window = getattr(self.scope, "window_seconds", None) or total
            window = max(window, total)
            t0 = time.time()
            while True:
                if stop():
                    say("Измерение остановлено"); break
                elapsed = time.time() - t0
                if elapsed >= window:
                    break
                if elapsed >= cfg.pre_roll:
                    if not output_on:
                        self.generator.set_output(True); output_on = True   # фронт здесь
                    sw = elapsed - cfg.pre_roll
                    sf = min(sw / cfg.sweep_time, 1.0) if cfg.sweep_time > 0 else 1.0
                    if callable(set_freq):
                        set_freq(cfg.start_freq + (cfg.end_freq - cfg.start_freq) * sf)
                prog(int(min(elapsed / window, 1.0) * 100))
                time.sleep(0.05)
            # 5) читаем один кадр целиком
            if hasattr(self.scope, "read_captured"):
                channels = self.scope.read_captured()
            else:
                channels = self.scope.read_all()
        finally:
            self.generator.set_output(False)
            if hasattr(self.scope, "set_peak_detect"):
                self.scope.set_peak_detect(False)

        prog(100); say(f"Измерение завершено ({len(channels)} каналов)")
        return channels

    def capture_now(self) -> dict[str, Channel]:
        """Прочитать текущую осциллограмму (чтение осциллографа)."""
        return self.scope.read_all()
