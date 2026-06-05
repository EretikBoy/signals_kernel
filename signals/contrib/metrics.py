"""
Метрики АЧХ как колонки дерева. Каждая колонка — одна функция с декоратором.
GUI строит динамические столбцы, перечисляя реестр COLUMNS, поэтому добавить
столбец = добавить сюда функцию (TODO #2). Подпись столбца берётся из meta['label'].
"""
from __future__ import annotations

import numpy as np

from ..engine import AnalysisResult
from ..extpoints import COLUMNS


def _resonance(result: AnalysisResult, channel: str) -> tuple[float, float]:
    amp = result.amplitude.get(channel, np.array([]))
    if amp.size == 0 or result.freqs.size == 0:
        return 0.0, 0.0
    idx = int(np.argmax(amp))
    return float(amp[idx]), float(result.freqs[idx])


@COLUMNS.register("max_amplitude", label="Макс. амплитуда", unit="")
def max_amplitude(result: AnalysisResult, channel: str) -> float:
    return _resonance(result, channel)[0]


@COLUMNS.register("resonance", label="Резонанс", unit="Гц")
def resonance(result: AnalysisResult, channel: str) -> float:
    return _resonance(result, channel)[1]


@COLUMNS.register("bandwidth_707", label="Полоса −3 дБ", unit="Гц")
def bandwidth_707(result: AnalysisResult, channel: str) -> float:
    amp = result.amplitude.get(channel, np.array([]))
    if amp.size == 0:
        return 0.0
    level = np.max(amp) * 0.707
    above = np.where(amp >= level)[0]
    if above.size < 2:
        return 0.0
    return float(result.freqs[above[-1]] - result.freqs[above[0]])


@COLUMNS.register("q_factor", label="Добротность Q", unit="")
def q_factor(result: AnalysisResult, channel: str) -> float:
    _, f0 = _resonance(result, channel)
    bw = bandwidth_707(result, channel)
    return float(f0 / bw) if bw > 0 else 0.0
