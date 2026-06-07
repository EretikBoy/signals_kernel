"""
signals.services.templates
===========================

Шаблон обработки — это сохранённый набор настроек анализа, который потом можно
применить к другим измерениям разом, не настраивая каждое заново руками.

Важно, что шаблон не трогает параметры самого измерения (с какой по какую
частоту мерить, сколько по времени) — это снимается с прибора и у каждого
измерения своё. В шаблон попадает только то, что относится к обработке уже
снятых данных:
  * настройки анализа — сдвиг и длина строба, уровень среза, усиление,
    нормировка, какой стратегией искать начало сигнала, какие каналы брать;
  * какие столбцы показывать в дереве (их ключи);
  * пользовательские столбцы-формулы — имя и само выражение, чтобы при
    применении шаблона их можно было воссоздать на новом месте.

Хранится отдельно от настроек интерфейса — в ~/.signals/templates.json. Модуль
не зависит от Qt, как и весь слой services.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..extpoints import COLUMNS
from ..runtime_ext import register_user_column

TEMPLATES_PATH = Path.home() / ".signals" / "templates.json"

# Поля обработки, которые сохраняет/применяет шаблон (без частот свипа).
PROCESSING_FIELDS = ["cut_second", "fixedlevel", "gain", "normalize",
                     "edge_strategy", "record_time"]


def load_templates() -> dict:
    try:
        data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:                                  # noqa: BLE001
        return {}


def _save_all(data: dict) -> None:
    TEMPLATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")


def template_names() -> list[str]:
    return sorted(load_templates())


def get_template(name: str) -> dict | None:
    return load_templates().get(name)


def delete_template(name: str) -> None:
    data = load_templates()
    if name in data:
        data.pop(name); _save_all(data)


def current_formula_columns() -> list[dict]:
    """Текущие пользовательские формулы-столбцы (для сохранения в шаблон)."""
    out: list[dict] = []
    for e in COLUMNS:
        if e.source == "runtime" and e.meta.get("expr"):
            out.append({"key": e.key, "label": e.meta.get("label", e.key),
                        "unit": e.meta.get("unit", ""), "expr": e.meta["expr"]})
    return out


def register_formulas(formulas) -> list[str]:
    """Воссоздать формулы-столбцы из шаблона. Возвращает ключи добавленных."""
    added: list[str] = []
    for f in formulas or []:
        try:
            register_user_column(f["key"], f.get("label", f["key"]), f["expr"],
                                  unit=f.get("unit", ""))
            added.append(f["key"])
        except Exception:                              # noqa: BLE001
            pass
    return added


def save_template(name: str, *, analysis=None, columns=None, formulas=None) -> dict:
    """Сохранить шаблон. Любая часть необязательна (что передали — то и пишем).

    analysis — измерение, чьи параметры обработки/каналы взять;
    columns  — список ключей столбцов; formulas — список формул-столбцов.
    """
    data = load_templates()
    rec = data.get(name, {})
    if analysis is not None:
        p = analysis.params
        for f in PROCESSING_FIELDS:
            rec[f] = getattr(p, f)
        rec["signal_start_channel"] = analysis.signal_start_channel
        rec["selected_channel"] = analysis.selected_channel
    if columns is not None:
        rec["columns"] = list(columns)
    if formulas is not None:
        rec["formulas"] = list(formulas)
    data[name] = rec
    _save_all(data)
    return rec


def apply_to_analysis(name_or_rec, analysis) -> bool:
    """Применить обработку шаблона к измерению (поля обработки + каналы)."""
    rec = name_or_rec if isinstance(name_or_rec, dict) else load_templates().get(name_or_rec)
    if not rec:
        return False
    changed = False
    for f in PROCESSING_FIELDS:
        if f in rec:
            setattr(analysis.params, f, rec[f]); changed = True
    ssc = rec.get("signal_start_channel")
    if ssc and ssc in analysis.channels:
        analysis.signal_start_channel = ssc
    sel = rec.get("selected_channel")
    if sel and sel in analysis.channels:
        analysis.selected_channel = sel
    if changed:
        analysis.dirty = True
    return changed
