"""
signals.services.clipboard_data
===============================

Обмен кривыми с Excel и между графиками — вставить таблицу из буфера обмена как
кривую и наоборот.

* `parse_clipboard_table(text, swap_xy=False)` — разобрать вставленный из Excel
  фрагмент в пару массивов (x, y). Распознаёт разделители (таб, `;`, `,`,
  пробелы), десятичную запятую русского Excel, пропускает строку-заголовок,
  если она есть, и сама догадывается, как лежат данные: два столбца, один
  столбец (тогда Y берём по индексу), две строки 2×N (транспонируем) или
  одна строка. Если данные лежат «боком», можно поменять X и Y местами.
* `curve_to_tsv(x, y, decimal=',')` — обратное превращение: кривая в текст для
  вставки в Excel (между X и Y — таб, между точками — перевод строки).

Самое скользкое место — отличить разделитель столбцов от десятичной запятой.
Русский Excel выгружает CSV через `;`, потому что обычная запятая занята под
дробную часть числа — значит, если в строке есть таб, `;` или пробелы, любая
встреченная запятая — это десятичный разделитель. А если из разделителей нашлась
только одиночная `,` — это, наоборот, разделитель столбцов, а числа в
международном формате с точкой. Что именно было распознано, возвращается в
`info`, чтобы пользователь видел это и мог поправить руками — например, если
угадали неверно и надо поменять X и Y местами.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ParsedTable:
    x: np.ndarray
    y: np.ndarray
    info: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.x.size > 0 and self.x.size == self.y.size


def _split_lines(text: str) -> list[str]:
    return [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if ln.strip() != ""]


def _choose_delim(text: str, decimal: str = "auto") -> tuple[str | None, bool]:
    """Вернуть (разделитель, десятичная_запятая). decimal: 'auto'|','|'.'.

    В Excel десятичный разделитель зависит от локали (рус. — запятая), в Python —
    точка. 'auto' — угадать; ',' — запятая десятичная (разделитель Tab/;/пробел);
    '.' — точка десятичная (запятая может быть разделителем).
    """
    if decimal == ",":
        if "\t" in text:
            return "\t", True
        if ";" in text:
            return ";", True
        return None, True
    if decimal == ".":
        if "\t" in text:
            return "\t", False
        if ";" in text:
            return ";", False
        if "," in text:
            return ",", False
        return None, False
    if "\t" in text:
        return "\t", ("," in text)
    if ";" in text:
        return ";", True
    if "," in text:
        return ",", False
    return None, ("," in text)


def _to_float(cell: str, dec_comma: bool):
    s = cell.strip().strip('"').strip()
    if s == "":
        return None
    if dec_comma:
        s = s.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _grid(text: str, delim: str | None, dec_comma: bool) -> list[list]:
    rows = []
    for ln in _split_lines(text):
        cells = ln.split(delim) if delim is not None else ln.split()
        rows.append([_to_float(c, dec_comma) for c in cells])
    return rows


def parse_clipboard_table(text: str, swap_xy: bool = False,
                          transpose: bool = False, decimal: str = "auto") -> ParsedTable:
    info: list[str] = []
    if not text or not text.strip():
        return ParsedTable(np.array([]), np.array([]), ["пусто"])
    delim, dec_comma = _choose_delim(text, decimal)
    info.append({"\t": "разделитель: табуляция", ";": "разделитель: ;",
                 ",": "разделитель: запятая", None: "разделитель: пробелы"}[delim])
    if dec_comma:
        info.append("десятичная запятая")

    grid = _grid(text, delim, dec_comma)
    width = max((len(r) for r in grid), default=0)

    # строка-заголовок: первая строка целиком не-числовая (а ниже есть числа)
    if len(grid) > 1 and all(v is None for v in grid[0]) and \
            any(v is not None for r in grid[1:] for v in r):
        grid = grid[1:]; info.append("заголовок пропущен")
    rows = len(grid)

    def row_nums(i):
        return np.array([v for v in grid[i] if v is not None], dtype=float)

    def col_pairs():
        col0 = [r[0] if len(r) > 0 else None for r in grid]
        col1 = [r[1] if len(r) > 1 else None for r in grid]
        p = [(a, b) for a, b in zip(col0, col1) if a is not None and b is not None]
        return (np.array([a for a, _ in p], dtype=float),
                np.array([b for _, b in p], dtype=float))

    if transpose:                                   # пользователь: «значения по рядам»
        if rows >= 2:
            x, y = row_nums(0), row_nums(1); info.append("по рядам: X=1-й ряд, Y=2-й ряд")
        else:
            y = row_nums(0); x = np.arange(y.size, dtype=float)
            info.append("ряд → Y по индексу")
    elif width == 1 or rows == 1:                   # один столбец или один ряд
        flat = np.array([v for r in grid for v in r if v is not None], dtype=float)
        y, x = flat, np.arange(flat.size, dtype=float)
        info.append(("один ряд" if rows == 1 else "один столбец") +
                    " → Y по индексу (X = 0,1,2…)")
    elif rows == 2 and width >= 4:                  # явный ряд-пара (2 строки × много)
        x, y = row_nums(0), row_nums(1)
        info.append("распознан ряд (2×N) → транспонировано")
    else:                                           # столбцы
        x, y = col_pairs()
        info.append("столбцы X, Y" + (f" (из {width}, взяты первые два)" if width > 2 else ""))

    if swap_xy:
        x, y = y, x; info.append("X↔Y переставлены")
    return ParsedTable(x, y, info)


def curves_to_tsv(curves, decimal: str = ",") -> str:
    """Несколько кривых рядом столбцами (X1 Y1 X2 Y2 …) для вставки в Excel."""
    cols = []
    for x, y in curves:
        x = np.asarray(x); y = np.asarray(y)
        n = min(x.size, y.size)
        cols.append([(repr(float(x[i])), repr(float(y[i]))) for i in range(n)])
    rows = max((len(c) for c in cols), default=0)
    out = []
    for i in range(rows):
        cells = []
        for c in cols:
            if i < len(c):
                xs, ys = c[i]
                if decimal == ",":
                    xs = xs.replace(".", ","); ys = ys.replace(".", ",")
                cells += [xs, ys]
            else:
                cells += ["", ""]
        out.append("\t".join(cells))
    return "\n".join(out)


def curve_to_tsv(x, y, decimal: str = ",") -> str:
    """Текст для вставки в Excel: 'X<TAB>Y' по строкам. decimal=',' для рус. Excel."""
    x = np.asarray(x); y = np.asarray(y)
    n = min(x.size, y.size)
    out = []
    for i in range(n):
        xs = repr(float(x[i])); ys = repr(float(y[i]))
        if decimal == ",":
            xs = xs.replace(".", ","); ys = ys.replace(".", ",")
        out.append(f"{xs}\t{ys}")
    return "\n".join(out)
