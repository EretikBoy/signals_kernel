"""Стратегии поиска начала сигнала. Каждая — отдельный плагин (TODO #7)."""
from __future__ import annotations

import numpy as np

from ..domain import MeasurementParams
from ..extpoints import EDGE_STRATEGIES


@EDGE_STRATEGIES.register("max_amplitude", label="По максимуму амплитуды")
def by_max_amplitude(smoothed: np.ndarray, dt: float, params: MeasurementParams) -> int:
    """Исходный алгоритм: момент максимума + смещение cut_second."""
    if smoothed.size == 0:
        return 0
    peak = int(np.argmax(smoothed))
    offset = int(params.cut_second / dt) if dt > 0 else 0
    return max(0, min(peak + offset, smoothed.size - 1))


@EDGE_STRATEGIES.register("level_jump", label="Скачок на новый уровень (по умолчанию)")
def by_level_jump(smoothed: np.ndarray, dt: float, params: MeasurementParams) -> int:
    """Старт сигнала — точка самого резкого перехода с тихого уровня на новый,
    заметно более высокий (фронт). Именно так выглядит включение генератора в
    записи «тишина → сигнал → тишина»: сравниваем среднее значение в окне ДО и
    ПОСЛЕ каждой точки и берём точку наибольшего скачка вверх — двухоконный
    детектор перепада уровня, без подгонки под форму самого сигнала.
    """
    n = smoothed.size
    w = max(3, int(0.02 * n))                 # окно сравнения «до/после», ~2 % записи
    if n < 4 * w:
        return 0
    cs = np.concatenate(([0.0], np.cumsum(smoothed, dtype=np.float64)))
    i = np.arange(w, n - w)
    before = (cs[i] - cs[i - w]) / w           # средний уровень ДО точки
    after = (cs[i + w] - cs[i]) / w             # средний уровень ПОСЛЕ точки
    jump = after - before
    k = int(np.argmax(jump))
    idx = int(i[k])
    span = float(np.max(smoothed) - np.min(smoothed))
    if span <= 0 or jump[k] < 0.2 * span:       # заметного скачка нет — сигнал шёл с самого начала
        idx = 0
    offset = int(params.cut_second / dt) if dt > 0 else 0
    return max(0, min(idx + offset, n - 1))


@EDGE_STRATEGIES.register("adaptive", label="Адаптивный порог")
def by_adaptive(smoothed: np.ndarray, dt: float, params: MeasurementParams) -> int:
    """Старт сигнала по адаптивному порогу + проверка устойчивости.

    Базовый уровень и шум считаются по всей записи через нижний перцентиль —
    выброс на старте не собьёт оценку, и стратегия работает, даже если перед
    сигналом нет «тихого» участка (генератор включился сразу). Дальше ищем
    первый момент, когда сигнал устойчиво (не менее 70% окна) держится выше
    порога — случайный одиночный всплеск шума не примет за начало записи.
    """
    n = smoothed.size
    if n == 0:
        return 0
    base = float(np.percentile(smoothed, 10))         # робастная база (нижний уровень)
    low = smoothed[smoothed <= np.percentile(smoothed, 30)]
    noise = float(np.median(np.abs(low - base))) * 1.4826 if low.size else 0.0   # σ через MAD
    span = float(np.max(smoothed)) - base
    if span <= 0:
        return 0
    thr = base + max(5.0 * noise, 0.10 * span)        # адаптивный порог над базой
    above = smoothed > thr
    w = max(3, int(0.01 * n))                          # окно устойчивости ~1 %
    csum = np.cumsum(above.astype(np.float64))
    start = 0
    for i in range(n - w):
        if above[i] and (csum[i + w] - csum[i]) >= 0.7 * w:   # держится выше порога
            start = i; break
    else:
        idx = np.where(above)[0]
        start = int(idx[0]) if idx.size else 0
    offset = int(params.cut_second / dt) if dt > 0 else 0
    return max(0, min(start + offset, n - 1))


@EDGE_STRATEGIES.register("threshold_crossing", label="По пересечению порога")
def by_threshold(smoothed: np.ndarray, dt: float, params: MeasurementParams) -> int:
    """Первый выход сигнала за долю (fixedlevel) от максимума — фронт нарастания."""
    if smoothed.size == 0:
        return 0
    level = np.max(smoothed) * params.fixedlevel
    above = np.where(smoothed >= level)[0]
    start = int(above[0]) if above.size else 0
    offset = int(params.cut_second / dt) if dt > 0 else 0
    return max(0, min(start + offset, smoothed.size - 1))
