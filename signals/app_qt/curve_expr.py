"""
signals.app_qt.curve_expr
=========================

Язык выражений над кривыми. Кривые называются g1, g2, и так далее по порядку
добавления. Срез берётся по частоте, не по индексу: g1[2160:2165] — это часть
кривой в полосе от 2160 до 2165 Гц, а не первые несколько точек массива.

Свёртки кривой в число не просто возвращают результат — они ещё и рисуют его
прямо на графике, чтобы не приходилось гадать, к какой именно точке он
относится:
  max(g)/min(g)        — точка экстремума + подпись значения;
  sum(g)/integral(g)   — заливка области по X кривой + подпись интеграла (∫);
  mean(g)              — горизонтальная линия среднего + подпись;
  argmax(g)/argmin(g)  — частота экстремума (точка);
  band(g, 0.707)       — полоса вокруг резонанса, где y ≥ уровень·max (две вертикали
                         по −3 дБ), как сужающий срез: integral(band(g)) = площадь пика;
  tangent(g, f)        — касательная к кривой на частоте f + подпись наклона;
  at(g, f)/value(g,f)  — точка на кривой на частоте f.

Поэлементно (новая кривая): log(g), exp(g), sqrt(g), g1-g2, derivative(g), cumint(g)…
Результат-число → рисуются аннотации и показывается значение; результат-кривая →
добавляется как новая кривая.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..runtime_ext import compile_safe

_TRAPZ = getattr(np, "trapezoid", getattr(np, "trapz", None))


def _trap(y, x) -> float:
    if _TRAPZ is not None:
        return float(_TRAPZ(y, x))
    y = np.asarray(y, float); x = np.asarray(x, float)
    return float(np.sum((y[1:] + y[:-1]) / 2.0 * np.diff(x)))


class Curve:
    """Кривая (x, y) с поддержкой среза по X и поэлементной арифметики/ufunc."""

    def __init__(self, x, y, annot: list | None = None, label: str = "") -> None:
        self.x = np.asarray(x, float)
        self.y = np.asarray(y, float)
        self.annot = annot if annot is not None else []
        self.label = label

    # срез по частоте, не по индексу массива: g[a:b]
    def __getitem__(self, s):
        if isinstance(s, slice):
            a = self.x.min() if s.start is None else float(s.start)
            b = self.x.max() if s.stop is None else float(s.stop)
            m = (self.x >= a) & (self.x <= b)
            return Curve(self.x[m], self.y[m], self.annot, self.label)
        return self.y[s]

    def _ya(self, o):
        return np.interp(self.x, o.x, o.y) if isinstance(o, Curve) else o

    def __add__(self, o): return Curve(self.x, self.y + self._ya(o), self.annot, self.label)
    def __radd__(self, o): return Curve(self.x, self._ya(o) + self.y, self.annot, self.label)
    def __sub__(self, o): return Curve(self.x, self.y - self._ya(o), self.annot, self.label)
    def __rsub__(self, o): return Curve(self.x, self._ya(o) - self.y, self.annot, self.label)
    def __mul__(self, o): return Curve(self.x, self.y * self._ya(o), self.annot, self.label)
    def __rmul__(self, o): return Curve(self.x, self._ya(o) * self.y, self.annot, self.label)
    def __truediv__(self, o):
        with np.errstate(divide="ignore", invalid="ignore"):
            return Curve(self.x, self.y / self._ya(o), self.annot, self.label)
    def __rtruediv__(self, o):
        with np.errstate(divide="ignore", invalid="ignore"):
            return Curve(self.x, self._ya(o) / self.y, self.annot, self.label)
    def __pow__(self, o): return Curve(self.x, self.y ** self._ya(o), self.annot, self.label)
    def __neg__(self): return Curve(self.x, -self.y, self.annot, self.label)

    # сравнения → булев массив (для where/условий)
    def __gt__(self, o): return self.y > self._ya(o)
    def __lt__(self, o): return self.y < self._ya(o)
    def __ge__(self, o): return self.y >= self._ya(o)
    def __le__(self, o): return self.y <= self._ya(o)

    def __array__(self, dtype=None):
        return self.y.astype(dtype) if dtype else self.y

    def __array_ufunc__(self, ufunc, method, *inputs, **kw):
        arrs = [i.y if isinstance(i, Curve) else i for i in inputs]
        res = getattr(ufunc, method)(*arrs, **kw)
        if isinstance(res, np.ndarray) and res.shape == self.y.shape:
            return Curve(self.x, res, self.annot, self.label)
        return res


# ---- редукции с аннотациями -------------------------------------------------
def _max(c):
    if isinstance(c, Curve) and c.y.size:
        i = int(np.argmax(c.y))
        c.annot.append({"type": "point", "x": float(c.x[i]), "y": float(c.y[i]),
                        "text": f"max={c.y[i]:.3g} @ {c.x[i]:.4g}"})
        return float(c.y[i])
    return float(np.max(c))


def _min(c):
    if isinstance(c, Curve) and c.y.size:
        i = int(np.argmin(c.y))
        c.annot.append({"type": "point", "x": float(c.x[i]), "y": float(c.y[i]),
                        "text": f"min={c.y[i]:.3g} @ {c.x[i]:.4g}"})
        return float(c.y[i])
    return float(np.min(c))


def _argmax(c):
    if isinstance(c, Curve) and c.y.size:
        i = int(np.argmax(c.y))
        c.annot.append({"type": "point", "x": float(c.x[i]), "y": float(c.y[i]),
                        "text": f"@ {c.x[i]:.4g}"})
        return float(c.x[i])
    return float(np.argmax(c))


def _integral(c):
    if isinstance(c, Curve) and c.x.size > 1:
        area = _trap(c.y, c.x)
        c.annot.append({"type": "vspan", "x0": float(c.x.min()), "x1": float(c.x.max()),
                        "text": f"∫={area:.3g}"})
        return area
    return float(np.sum(c))


def _mean(c):
    if isinstance(c, Curve) and c.y.size:
        m = float(np.mean(c.y))
        c.annot.append({"type": "hline", "y": m, "x0": float(c.x.min()),
                        "x1": float(c.x.max()), "text": f"mean={m:.3g}"})
        return m
    return float(np.mean(c))


def _band(c, level: float = 0.707):
    """Полоса вокруг глобального максимума, где y ≥ level·max (резонанс по −3 дБ)."""
    if not isinstance(c, Curve) or c.y.size == 0:
        return c
    peak = int(np.argmax(c.y)); thr = level * float(c.y[peak])
    lo = peak
    while lo > 0 and c.y[lo - 1] >= thr:
        lo -= 1
    hi = peak
    while hi < c.y.size - 1 and c.y[hi + 1] >= thr:
        hi += 1
    c.annot.append({"type": "vline", "x": float(c.x[lo])})
    c.annot.append({"type": "vline", "x": float(c.x[hi])})
    return Curve(c.x[lo:hi + 1], c.y[lo:hi + 1], c.annot, c.label)


def _at(c, f):
    f = float(f)
    yv = float(np.interp(f, c.x, c.y)) if isinstance(c, Curve) else float("nan")
    if isinstance(c, Curve):
        c.annot.append({"type": "point", "x": f, "y": yv, "text": f"{yv:.3g} @ {f:.4g}"})
    return yv


def _tangent(c, f):
    if not isinstance(c, Curve) or c.x.size < 2:
        return float("nan")
    f = float(f)
    dy = np.gradient(c.y, c.x)
    slope = float(np.interp(f, c.x, dy)); y0 = float(np.interp(f, c.x, c.y))
    span = (float(c.x.max()) - float(c.x.min())) * 0.12 or 1.0
    c.annot.append({"type": "tangent", "px": f, "py": y0,
                    "x0": f - span, "y0": y0 - slope * span,
                    "x1": f + span, "y1": y0 + slope * span,
                    "text": f"наклон={slope:.3g}"})
    return slope


def _cumint(c):
    if isinstance(c, Curve):
        out = np.zeros_like(c.y)
        if c.y.size > 1:
            out[1:] = np.cumsum((c.y[1:] + c.y[:-1]) / 2.0 * np.diff(c.x))
        return Curve(c.x, out, c.annot, c.label)
    return np.cumsum(c)


def _derivative(c):
    if isinstance(c, Curve):
        return Curve(c.x, np.gradient(c.y, c.x), c.annot, c.label)
    return np.gradient(c)


_NS = {
    "max": _max, "min": _min, "sum": _integral, "integral": _integral, "trapz": _integral,
    "mean": _mean, "argmax": _argmax, "argmin": lambda c: _argmax(-c) if isinstance(c, Curve) else np.argmin(c),
    "band": _band, "tangent": _tangent, "at": _at, "value": _at,
    "cumint": _cumint, "derivative": _derivative, "diff": _derivative,
    "log": np.log, "ln": np.log, "log10": np.log10, "exp": np.exp, "sqrt": np.sqrt,
    "abs": np.abs, "sin": np.sin, "cos": np.cos, "tan": np.tan, "arctan": np.arctan,
    "where": np.where, "clip": np.clip, "minimum": np.minimum, "maximum": np.maximum,
    "std": lambda c: float(np.std(np.asarray(c))), "pi": np.pi, "e": np.e,
}


def evaluate(expr: str, curves: list[dict]) -> dict:
    """Вычислить выражение. Возвращает {kind, ...}.

    kind='curve' → x,y,name (новая кривая); kind='scalar' → value; всегда annotations.
    """
    annot: list = []
    names = dict(_NS)
    for i, c in enumerate(curves, start=1):
        cv = Curve(c["x"], c["y"], annot, c["name"])
        names[f"g{i}"] = cv
        names[f"x{i}"] = cv.x
    if curves:
        names["x"] = Curve(curves[0]["x"], curves[0]["x"], annot)
    res = eval(compile_safe(expr), {"__builtins__": {}}, names)  # noqa: S307 — песочница
    out: dict[str, Any] = {"annotations": annot}
    if isinstance(res, Curve):
        out.update(kind="curve", x=res.x, y=res.y)
    elif isinstance(res, np.ndarray):
        xref = curves[0]["x"] if curves and res.shape == np.asarray(curves[0]["x"]).shape \
            else np.arange(res.size, dtype=float)
        out.update(kind="curve", x=xref, y=res.astype(float))
    else:
        out.update(kind="scalar", value=float(res))
    return out
