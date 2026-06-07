"""
signals.plugins.capabilities
=============================

Прибор сам говорит, что он умеет, а тот, кому это нужно (сервис измерения,
GUI), просто спрашивает — вместо того чтобы где-то в коде держать список
моделей и проверять «это случайно не Hantek?». Например, GUI рисует панель
генератора только если `scope.supports(Cap.GENERATOR)` — добавится новый
прибор с генератором, и панель появится сама, без правок в GUI.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class Cap:
    """Строковые константы возможностей (чтобы не плодить опечатки)."""
    # осциллограф
    READ_WAVEFORM = "read_waveform"
    SET_TIMEBASE = "set_timebase"        # управление развёрткой (TODO #4)
    SET_ACQ_MODE = "set_acquisition_mode"
    SET_POINTS = "set_record_length"     # число точек (TODO #4)
    READ_LABEL = "read_channel_label"    # LABEL из меню прибора (TODO #1)
    # генератор / источник
    GENERATOR = "generator"
    SWEEP = "sweep"
    BURST = "burst"


@runtime_checkable
class Capable(Protocol):
    """Любой объект, умеющий перечислить свои возможности."""
    def capabilities(self) -> frozenset[str]: ...


def supports(obj: object, capability: str) -> bool:
    """Спросить у объекта, поддерживает ли он возможность."""
    if isinstance(obj, Capable):
        return capability in obj.capabilities()
    # запасной путь: класс может объявить CAPABILITIES как атрибут
    caps = getattr(obj, "CAPABILITIES", None)
    return bool(caps) and capability in caps


def describe_capabilities(obj: object) -> list[str]:
    if isinstance(obj, Capable):
        return sorted(obj.capabilities())
    return sorted(getattr(obj, "CAPABILITIES", ()) or ())
