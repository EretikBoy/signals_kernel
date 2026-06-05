"""
signals.services.columns
========================

Стандартные столбцы, как в оригинале: значения берутся из процессора (параметры,
параметры канала, сырые данные, время начала анализа). Плюс пользовательские
столбцы-формулы из реестра COLUMNS (source='formula').

`AVAILABLE_COLUMNS` — список доступных столбцов для диалога настройки.
`DEFAULT_COLUMN_KEYS` — что показывается по умолчанию.
`column_value(...)` — единый резолвер значения столбца для анализа.
"""
from __future__ import annotations

import math

from ..domain import Analysis
from ..engine import AnalysisResult, channel_metrics
from ..extpoints import COLUMNS

STANDARD_COLUMNS = [
    {"key": "start_freq", "title": "Начальная частота (Гц)", "source": "params"},
    {"key": "end_freq", "title": "Конечная частота (Гц)", "source": "params"},
    {"key": "record_time", "title": "Время записи (сек)", "source": "params"},
    {"key": "cut_second", "title": "Обрезка (сек)", "source": "params"},
    {"key": "gain", "title": "Усиление", "source": "params"},
    {"key": "fixedlevel", "title": "Фиксированный уровень", "source": "params"},
    {"key": "max_amplitude", "title": "Макс. амплитуда (В)", "source": "channel"},
    {"key": "resonance_frequency", "title": "Резонансная частота (Гц)", "source": "channel"},
    {"key": "bandwidth_707", "title": "Полоса −3 дБ (Гц)", "source": "channel"},
    {"key": "bandwidth_fixed", "title": "Полоса фикс. уровня (Гц)", "source": "channel"},
    {"key": "q_factor", "title": "Добротность", "source": "channel"},
    {"key": "raw_max_amp", "title": "Макс. амплитуда (сырая)", "source": "raw_max"},
    {"key": "raw_min_amp", "title": "Мин. амплитуда (сырая)", "source": "raw_min"},
    {"key": "analysis_start_time", "title": "Время начала анализа", "source": "processor"},
]

DEFAULT_COLUMN_KEYS = ["start_freq", "end_freq", "record_time"]


def available_columns() -> list[dict]:
    """Стандартные столбцы + пользовательские формулы (из реестра COLUMNS)."""
    cols = [dict(c) for c in STANDARD_COLUMNS]
    for entry in COLUMNS:
        if entry.meta.get("source") == "runtime":
            cols.append({"key": entry.key, "title": entry.label, "source": "formula"})
    return cols


def column_by_key(key: str) -> dict | None:
    for c in available_columns():
        if c["key"] == key:
            return c
    return None


def column_value(analysis: Analysis, result: AnalysisResult, col: dict):
    """Значение столбца для анализа по его источнику."""
    src = col.get("source"); key = col["key"]
    ch = analysis.selected_channel or next(iter(analysis.channels), "")
    try:
        if src == "params":
            return getattr(analysis.params, key, float("nan"))
        if src == "channel":
            m = channel_metrics(result, ch, analysis.params.fixedlevel)
            return m.get(key, float("nan"))
        if src == "raw_max":
            return result.raw_max.get(ch, float("nan"))
        if src == "raw_min":
            return result.raw_min.get(ch, float("nan"))
        if src == "processor":         # analysis_start_time
            return result.start_time
        if src == "formula":
            return COLUMNS.target(key)(result, ch)
    except Exception:
        return float("nan")
    return float("nan")


def format_value(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, (int, float)):
        return f"{value:.2f}"            # до сотых, без научной нотации
    return str(value)
