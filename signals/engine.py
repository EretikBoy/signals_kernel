"""
signals.engine
==============

Чистая обработка сигнала (без Qt): временные ряды (сырой/сглаженный/обрезанный),
АЧХ, полные метрики с диапазонами полос и прогноз полосы — всё, что нужно
графику для строба, маркеров и панели параметров.

Поиск начала сигнала — из реестра EDGE_STRATEGIES (TODO #7).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .domain import Analysis
from .extpoints import EDGE_STRATEGIES


@dataclass
class ChannelSeries:
    time: np.ndarray
    raw: np.ndarray
    smoothed: np.ndarray
    crop_time: np.ndarray
    crop_smoothed: np.ndarray


@dataclass
class AnalysisResult:
    freqs: np.ndarray
    amplitude: dict[str, np.ndarray]          # АЧХ по каналам (линейная)
    series: dict[str, ChannelSeries] = field(default_factory=dict)
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    start_index: int = 0
    start_time: float = 0.0
    dt: float = 0.0
    raw_min: dict[str, float] = field(default_factory=dict)
    raw_max: dict[str, float] = field(default_factory=dict)


def smooth(values: np.ndarray, window: int = 15) -> np.ndarray:
    if values.size == 0:
        return values
    kernel = np.ones(window) / window
    return np.convolve(np.abs(values), kernel, mode="same")


def _crop_bounds(analysis: Analysis) -> tuple[int, int, float, float]:
    start_ch = analysis.signal_start_channel or next(iter(analysis.channels), "")
    ref = analysis.channels.get(start_ch)
    if ref is None or ref.time.size < 2:
        return 0, 0, 0.0, 0.0
    dt = float(ref.time[1] - ref.time[0])
    strategy = EDGE_STRATEGIES.target(analysis.params.edge_strategy)
    start = strategy(smooth(ref.amplitude), dt, analysis.params)
    n = int(analysis.params.record_time / dt) if dt > 0 else ref.time.size
    end = min(start + n, ref.time.size)
    start_time = float(ref.time[start]) if start < ref.time.size else 0.0
    return start, end, dt, start_time


def analyze(analysis: Analysis) -> AnalysisResult:
    params = analysis.params
    start, end, dt, start_time = _crop_bounds(analysis)
    if end <= start:
        return AnalysisResult(freqs=np.array([]), amplitude={})

    ref = analysis.channels[analysis.signal_start_channel or next(iter(analysis.channels))]
    t = ref.time[start:end]
    t0 = t - t[0]
    freqs = params.start_freq + (params.bandwidth / params.record_time) * t0

    amplitude: dict[str, np.ndarray] = {}
    series: dict[str, ChannelSeries] = {}
    raw_min: dict[str, float] = {}
    raw_max: dict[str, float] = {}
    for name, ch in analysis.channels.items():
        sm = smooth(ch.amplitude)
        crop_sm = sm[start:end] * params.gain
        if params.normalize and crop_sm.size and np.max(crop_sm) != 0:
            crop_sm = crop_sm / np.max(crop_sm)
        amplitude[name] = crop_sm
        series[name] = ChannelSeries(time=ch.time, raw=ch.amplitude, smoothed=sm,
                                     crop_time=t0, crop_smoothed=crop_sm)
        raw_min[name] = float(np.min(ch.amplitude)) if ch.amplitude.size else 0.0
        raw_max[name] = float(np.max(ch.amplitude)) if ch.amplitude.size else 0.0

    return AnalysisResult(freqs=freqs, amplitude=amplitude, series=series,
                          start_index=start, start_time=start_time, dt=dt,
                          raw_min=raw_min, raw_max=raw_max)


def _band_range(freqs: np.ndarray, amp: np.ndarray, level: float) -> tuple[float, float, float]:
    above = np.where(amp >= level)[0]
    if above.size < 2:
        return 0.0, 0.0, 0.0
    lo, hi = float(freqs[above[0]]), float(freqs[above[-1]])
    return hi - lo, lo, hi


def channel_metrics(result: AnalysisResult, channel: str, fixedlevel: float = 0.6) -> dict:
    """Полный набор параметров канала (резонанс, полосы с диапазонами, Q)."""
    amp = result.amplitude.get(channel, np.array([]))
    freqs = result.freqs
    if amp.size == 0 or freqs.size == 0:
        return {}
    idx = int(np.argmax(amp))
    max_amp = float(amp[idx]); resonance = float(freqs[idx])
    bw707, lo707, hi707 = _band_range(freqs, amp, max_amp * 0.707)
    bwf, lof, hif = _band_range(freqs, amp, fixedlevel)
    return {
        "max_amplitude": max_amp,
        "resonance_frequency": resonance,
        "bandwidth_707": bw707, "bandwidth_707_range": (lo707, hi707),
        "bandwidth_fixed": bwf, "bandwidth_fixed_range": (lof, hif),
        "q_factor": resonance / bw707 if bw707 > 0 else 0.0,
    }


def frequency_forecast(resonance: float, criterion: float, record_time: float) -> tuple[float, float]:
    """Прогноз полосы для проверки (формула оригинала)."""
    half = criterion * record_time / 2.0
    return resonance - half, resonance + half
