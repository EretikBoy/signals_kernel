"""
signals.services.analysis
=========================

Связывает чистый движок (`engine.analyze`) с реестром колонок (`COLUMNS`).
GUI вызывает один метод и получает АЧХ + значения всех колонок (встроенных,
drop-in и пользовательских) для каждого канала. Добавление метрики/колонки
нигде в GUI не правится — она появляется из реестра автоматически.
"""
from __future__ import annotations

from ..domain import Analysis
from ..engine import AnalysisResult, analyze
from ..extpoints import COLUMNS


def column_values(result: AnalysisResult, channel: str) -> dict[str, float]:
    """Посчитать все зарегистрированные колонки для одного канала."""
    values: dict[str, float] = {}
    for entry in COLUMNS:
        try:
            values[entry.key] = entry.target(result, channel)
        except Exception:
            values[entry.key] = float("nan")
    return values


def analyze_full(analysis: Analysis) -> AnalysisResult:
    """Полный расчёт: АЧХ + метрики по всем каналам."""
    result = analyze(analysis)
    for channel in result.amplitude:
        result.metrics[channel] = column_values(result, channel)
    return result
