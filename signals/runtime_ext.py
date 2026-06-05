"""
signals.runtime_ext
====================

Рантайм-расширения для конечного пользователя: добавить вычисляемую колонку или
именованное выражение во время работы приложения, без программиста и перезапуска.

Под капотом — те же реестры (`COLUMNS`, `FUNCTIONS`), просто регистрация в момент
действия пользователя с `source="runtime"`. Поскольку реестры уведомляют
подписчиков (`on_change`), дерево/сводка сразу подхватывают новую колонку.

Выражения вычисляются в песочнице: доступны только numpy-безопасные функции из
реестра FUNCTIONS и переменные результата (freqs, амплитуды каналов). Это не
`eval` по сырому коду — имена ограничены, встроенные builtins отключены.
"""
from __future__ import annotations

import ast
from typing import Any, Callable

import numpy as np

from .engine import AnalysisResult
from .extpoints import COLUMNS, FUNCTIONS

# Узлы AST, разрешённые в пользовательских выражениях.
_ALLOWED_NODES = (
    ast.Expression, ast.Call, ast.Name, ast.Load, ast.Constant,
    ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
    ast.USub, ast.UAdd, ast.Mod, ast.Subscript, ast.Index, ast.Slice,
    ast.Tuple, ast.List,
)


def _check_safe(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"Недопустимый элемент выражения: {type(node).__name__}")


def compile_expression(expr: str) -> Callable[[AnalysisResult, str], Any]:
    """Скомпилировать пользовательское выражение в функцию (result, channel) -> value."""
    tree = ast.parse(expr, mode="eval")
    _check_safe(tree)
    code = compile(tree, "<user-expression>", "eval")

    def evaluate(result: AnalysisResult, channel: str) -> Any:
        names: dict[str, Any] = {e.key: e.target for e in FUNCTIONS}
        names["freqs"] = result.freqs
        names["amp"] = result.amplitude.get(channel, np.array([]))
        names["pi"] = np.pi
        return eval(code, {"__builtins__": {}}, names)  # noqa: S307 — песочница выше

    return evaluate


def register_user_column(key: str, label: str, expr: str, *, unit: str = "") -> None:
    """Зарегистрировать пользовательскую колонку из выражения (вызывается из UI)."""
    evaluator = compile_expression(expr)

    def column(result: AnalysisResult, channel: str) -> Any:
        return evaluator(result, channel)

    COLUMNS.add(key, column, source="runtime", label=label, unit=unit, expr=expr)


def register_user_function(name: str, func: Callable[..., Any]) -> None:
    """Добавить функцию в язык выражений в рантайме."""
    FUNCTIONS.add(name, func, source="runtime")
