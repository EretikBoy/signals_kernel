"""Функции языка выражений сводки. Добавить функцию = одна строка с декоратором."""
from __future__ import annotations

import numpy as np

from ..extpoints import FUNCTIONS

for _name, _fn in {
    "max": np.max, "min": np.min, "mean": np.mean, "std": np.std,
    "sum": np.sum, "abs": np.abs, "sqrt": np.sqrt, "log10": np.log10,
}.items():
    FUNCTIONS.add(_name, _fn, source="builtin")
