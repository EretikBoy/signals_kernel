"""
signals.instruments
====================

Контракты приборов. Любой прибор реализует один или оба протокола и объявляет
свои возможности через `capabilities()`. Сервис измерения и GUI работают только
с этими контрактами и со списком возможностей — поэтому добавление нового прибора
(включая Hantek со встроенным генератором) не требует правок нигде, кроме одного
нового модуля-плагина.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain import Channel
from .plugins.capabilities import Cap


@runtime_checkable
class Oscilloscope(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def capabilities(self) -> frozenset[str]: ...
    @property
    def channel_count(self) -> int: ...
    def read_channel(self, n: int) -> Channel | None: ...
    def read_all(self) -> dict[str, Channel]: ...
    # опциональны — наличие объявляется через capabilities():
    def set_timebase(self, seconds_per_div: float) -> None: ...
    def set_acquisition_mode(self, mode: str) -> None: ...
    def set_record_length(self, points: int) -> None: ...
    # опциональны — сценарий измерения проверяет их через hasattr() перед вызовом
    # (есть только у приборов, которые умеют сами подгонять развёртку под свип
    # и копить один длинный кадр пик-детектором, как Hantek):
    def set_timebase_for_window(self, seconds: float) -> None: ...
    def set_peak_detect(self, on: bool) -> None: ...
    def start_acquisition(self) -> None: ...
    def read_captured(self) -> dict[str, Channel]: ...


@runtime_checkable
class Generator(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def capabilities(self) -> frozenset[str]: ...
    def configure_sweep(
        self, *, start: float, stop: float, seconds: float,
        amplitude: float, offset: float, function: str = "SIN",
    ) -> None: ...
    def set_output(self, on: bool) -> None: ...


class InstrumentBase:
    """Базовый класс с введением возможностей.

    Наследник объявляет `CAPABILITIES = frozenset({...})`; метод `capabilities()`
    отдаёт их наружу. Так потребитель спрашивает прибор «что ты умеешь».
    """
    CAPABILITIES: frozenset[str] = frozenset()

    # connect/disconnect реализует каждый наследник по-своему (открыть VISA-сессию,
    # загрузить DLL и т.п.) — здесь только объявление контракта, чтобы __enter__/
    # __exit__ ниже типизировались корректно
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...

    def capabilities(self) -> frozenset[str]:
        return self.CAPABILITIES

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()


__all__ = ["Oscilloscope", "Generator", "InstrumentBase", "Cap"]
