"""
signals.io.parsers
==================

Парсеры входных файлов. Каждый формат регистрируется в реестре PARSERS —
добавить новый формат = одна функция с декоратором (точка расширения).
Поддержаны форматы оригинала, чтобы открывались уже существующие данные:

* CSV «новый» — заголовок CHx_time, CHx_amplitude (так сохраняет приложение);
* CSV «старый» — экспорт осциллографа без заголовка (метаданные в первых строках);
* Excel — двухканальный экспорт (метаданные A:C / G:I, данные D/E и J/K).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..domain import Channel, ChannelMetadata
from ..extpoints import PARSERS


def _channel(name: str, time, amp, label: str = "") -> Channel:
    t = np.asarray(time, dtype=np.float64)
    a = np.asarray(amp, dtype=np.float64)
    mask = ~(np.isnan(t) | np.isnan(a))
    t, a = t[mask], a[mask]
    return Channel(name=name, time=t, amplitude=a,
                   metadata=ChannelMetadata(record_length=t.size, source_label=label or name))


@PARSERS.register("csv", label="CSV", extensions=[".csv"])
def parse_csv(path: str) -> dict[str, Channel]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        first = f.readline()
    if first.startswith("CH") and "_time" in first and "_amplitude" in first:
        return _parse_csv_new(path)
    return _parse_csv_old(path)


def _parse_csv_new(path: str) -> dict[str, Channel]:
    df = pd.read_csv(path, encoding="utf-8")
    channels: dict[str, Channel] = {}
    for col in [c for c in df.columns if str(c).endswith("_time")]:
        name = str(col)[: -len("_time")]
        amp_col = f"{name}_amplitude"
        if amp_col in df.columns:
            channels[name] = _channel(name, df[col].to_numpy(), df[amp_col].to_numpy())
    return channels


def _parse_csv_old(path: str) -> dict[str, Channel]:
    df = pd.read_csv(path, header=None)
    channels: dict[str, Channel] = {}
    blocks = [(0, 1, 2, 3, 4), (6, 7, 8, 9, 10)]   # meta0..2, time, amp
    for m0, _m1, _m2, tcol, acol in blocks:
        if acol >= df.shape[1]:
            continue
        meta = df.iloc[:16, m0 : m0 + 3].dropna(how="all").T
        try:
            meta_dict = dict(zip(meta.iloc[0], meta.iloc[1]))
            name = str(meta_dict.get("Source", f"CH{tcol}"))
        except Exception:
            name = f"CH{tcol}"
        channels[name] = _channel(name, df.iloc[:, tcol].to_numpy(), df.iloc[:, acol].to_numpy())
    return channels


@PARSERS.register("excel", label="Excel", extensions=[".xlsx", ".xls"])
def parse_excel(path: str) -> dict[str, Channel]:
    channels: dict[str, Channel] = {}
    structures = [("A:C", "D", "E"), ("G:I", "J", "K")]
    with pd.ExcelFile(path) as xlsx:
        for meta_cols, tcol, acol in structures:
            try:
                meta = pd.read_excel(xlsx, usecols=meta_cols, header=None, nrows=16).dropna(how="all").T
                meta_dict = dict(zip(meta.iloc[0], meta.iloc[1]))
                name = str(meta_dict.get("Source", tcol))
                t = pd.read_excel(xlsx, usecols=tcol, header=None).squeeze("columns")
                a = pd.read_excel(xlsx, usecols=acol, header=None).squeeze("columns")
                channels[name] = _channel(name, np.asarray(t), np.asarray(a))
            except Exception:
                continue
    return channels


def register_builtin_parsers() -> None:
    """Парсеры регистрируются при импорте модуля; функция для явности."""
    return None


def parse_file(path: str | Path) -> dict[str, Channel]:
    """Выбрать парсер по расширению (через реестр PARSERS) и распарсить."""
    ext = Path(path).suffix.lower()
    for entry in PARSERS:
        if ext in entry.meta.get("extensions", []):
            return entry.target(str(path))
    raise ValueError(f"Нет парсера для формата: {ext}")
