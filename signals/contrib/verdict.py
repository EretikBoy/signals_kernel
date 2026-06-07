"""
signals.contrib.verdict
=======================

Колонка-вердикт о годности антенны по максимальной амплитуде АЧХ. Порог
настраивается (settings['verdict_threshold'], В); антенны с амплитудой ниже порога
считаются браком. Используется базовым обучением (калибровка антенн), но доступна
как обычный столбец-плагин в диалоге настройки столбцов.
"""
from __future__ import annotations

from ..engine import channel_metrics
from ..extpoints import COLUMNS

DEFAULT_THRESHOLD = 0.5  # В


def threshold() -> float:
    try:
        from ..app_qt import theme
        return float(theme.load_settings().get("verdict_threshold", DEFAULT_THRESHOLD))
    except Exception:                                  # noqa: BLE001 — без GUI/настроек
        return DEFAULT_THRESHOLD


def antenna_verdict(result, channel: str):
    """Вывод о годности по максимальной амплитуде канала."""
    m = channel_metrics(result, channel, 0.707)
    amp = m.get("max_amplitude")
    if amp is None or (isinstance(amp, float) and amp != amp):
        return ""
    thr = threshold()
    return "Годна" if amp >= thr else f"Брак (<{thr:g} В)"


COLUMNS.add("antenna_verdict", antenna_verdict, source="runtime",
            label="Годность антенны", unit="")
