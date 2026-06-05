"""
Пример DROP-IN плагина («вирус»).

Этот файл НЕ входит в пакет signals. Он лежит в отдельной папке плагинов и
подхватывается приложением на старте через discover(folders=[...]) — без
переустановки и без правок ядра. Так пользователь/инженер добавляет свой прибор,
колонку или функцию, просто положив сюда .py-файл.

Здесь добавляем демонстрационную колонку «крутизна на резонансе».
"""
import numpy as np

from signals.engine import AnalysisResult
from signals.extpoints import COLUMNS


@COLUMNS.register("peak_sharpness", label="Крутизна пика", unit="1/Гц", source="dropin")
def peak_sharpness(result: AnalysisResult, channel: str) -> float:
    amp = result.amplitude.get(channel, np.array([]))
    if amp.size < 3 or result.freqs.size < 3:
        return 0.0
    i = int(np.argmax(amp))
    i = min(max(i, 1), amp.size - 2)
    df = result.freqs[i + 1] - result.freqs[i - 1]
    return float(abs(amp[i + 1] - 2 * amp[i] + amp[i - 1]) / (df or 1.0))
