"""
signals.services.measurement
============================

Сценарий измерения АЧХ: генератор гонит свип за заданное время развёртки
(`sweep_time`), осциллограф снимает отклик. Свип задаётся именно временем, а не
числом точек — так было в оригинале, и менять это незачем. Осциллограф и
генератор передаются как два отдельных прибора — для Hantek, где это один и тот
же физический прибор, в оба параметра просто попадает одна и та же ссылка.

Для USB-приборов частота внутри меняется небольшими шагами в пределах
`sweep_time` (аппаратный линейный свип HTHardDll проверить без железа было
нельзя — пользователю число шагов не видно, и если что-то не так, это можно
поправить незаметно для остального кода). Результат — `Channel`, где ось
времени идёт от 0 до `sweep_time`; движок сам линейно растягивает её в
частоту, так что весь остальной конвейер обработки не замечает разницы.
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


ProgressFn = Callable[[int, str], None]


class MeasurementService:
    def __init__(self, scope, generator=None) -> None:
        self.scope: Oscilloscope = scope
        self.generator: Generator = generator if generator is not None else scope

    def run(self, cfg: SweepConfig, *, progress=None, log=None,
            should_stop=None) -> dict[str, Channel]:
        """Снять АЧХ: генератор «качает» частоту start→stop за sweep_time, а осциллограф
        в режиме пик-детектора пишет всё это одним длинным кадром (с окном захвата
        не меньше sweep_time) — отдельные кадры под каждую частоту тут не нужны.

        Возвращает сырые осциллограммы CH1..CH4 (CH1 — сигнал генератора для
        определения фронта, CH2 — отклик). АЧХ из них строит движок analyze().
        """
        prog = progress or (lambda p: None)
        say = log or (lambda m: None)
        stop = should_stop or (lambda: False)
        if not supports(self.generator, Cap.GENERATOR):
            raise RuntimeError("Прибор не поддерживает генератор — измерение свипом невозможно")

        # 1) осциллограф: развёртка под окно ≈ время свипа + пик-детектор
        if hasattr(self.scope, "set_timebase_for_window"):
            self.scope.set_timebase_for_window(cfg.sweep_time)
        if hasattr(self.scope, "set_peak_detect"):
            self.scope.set_peak_detect(True)
        say(f"Свип {cfg.start_freq:.0f}→{cfg.end_freq:.0f} Гц за {cfg.sweep_time:g} c "
            f"(пик-детектор, один кадр)")

        # 2) генератор: задаём параметры сигнала, выход пока выключен — включим
        #    его сразу с запуском захвата, чтобы кадр и чирп шли синхронно
        self.generator.configure_sweep(
            start=cfg.start_freq, stop=cfg.end_freq, seconds=cfg.sweep_time,
            amplitude=cfg.amplitude, offset=cfg.offset, function=cfg.function)
        self.generator.set_output(False)
        set_freq = getattr(self.generator, "set_frequency", None)

        stopped = False
        try:
            # 3) запуск захвата и генератора — одним моментом, без рассинхрона
            if hasattr(self.scope, "start_acquisition"):
                self.scope.start_acquisition()
            self.generator.set_output(True)
            window = getattr(self.scope, "window_seconds", None) or cfg.sweep_time
            window = max(window, cfg.sweep_time)
            t0 = time.time()
            while True:
                if stop():
                    stopped = True
                    say("Измерение остановлено")
                    break
                elapsed = time.time() - t0
                if elapsed >= window:
                    break
                sf = min(elapsed / cfg.sweep_time, 1.0) if cfg.sweep_time > 0 else 1.0
                if callable(set_freq):
                    set_freq(cfg.start_freq + (cfg.end_freq - cfg.start_freq) * sf)
                prog(int(min(elapsed / window, 1.0) * 100))
                time.sleep(0.05)
            if stopped:
                # пользователь нажал «Остановить» — не ждём оставшееся окно и не
                # читаем кадр (read_captured может блокировать на десятки секунд),
                # пустой словарь worker отбросит сам, увидев флаг остановки
                return {}
            # 4) читаем один кадр целиком
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
