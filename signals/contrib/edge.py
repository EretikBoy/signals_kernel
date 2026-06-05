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


@EDGE_STRATEGIES.register("adaptive", label="Адаптивный порог (по умолчанию)")
def by_adaptive(smoothed: np.ndarray, dt: float, params: MeasurementParams) -> int:
    """Старт сигнала по адаптивному порогу + проверка устойчивости.

    Порог не жёсткий: базовый уровень и шум оцениваются по началу записи (где до
    подачи сигнала тишина — см. предзапись pre_roll), затем берётся первый момент,
    когда сигнал устойчиво (≥70 % окна) выходит выше базового уровня.
    """
    n = smoothed.size
    if n == 0:
        return 0
    head = smoothed[:max(10, min(n // 20, 500))]      # «тихий» участок до сигнала
    base = float(np.median(head))
    noise = float(np.median(np.abs(head - base))) * 1.4826   # робастная σ (MAD)
    span = float(np.max(smoothed) - base)
    if span <= 0:
        return 0
    thr = base + max(5.0 * noise, 0.10 * span)        # адаптивный порог над базой
    above = smoothed > thr
    w = max(3, int(0.01 * n))                         # окно устойчивости ~1 %
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
