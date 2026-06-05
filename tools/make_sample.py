"""Сгенерировать образцовые CSV (формат приложения) для проверки без прибора."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


def make(path: Path, code: str, f0: float, q: float) -> None:
    fs = 200_000
    t = np.arange(0, 1.0, 1 / fs)
    f = 1000 + 99000 * t                       # свип 1–100 кГц за 1 c
    drive = np.sin(2 * np.pi * f * t)
    resp = drive / np.sqrt((1 - (f / f0) ** 2) ** 2 + (f / (f0 * q)) ** 2)
    pd.DataFrame({
        "CH1_time": t, "CH1_amplitude": resp / np.max(np.abs(resp)) * 0.8,
        "CH2_time": t, "CH2_amplitude": drive * 0.2,
    }).to_csv(path, index=False)
    print("written", path)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out.mkdir(parents=True, exist_ok=True)
    # имя 'CODE_START_END_TIME' распознаётся приложением автоматически
    make(out / "Деталь-A_1000_100000_1.csv", "Деталь-A", 45000, 30)
    make(out / "Деталь-B_1000_100000_1.csv", "Деталь-B", 60000, 18)
