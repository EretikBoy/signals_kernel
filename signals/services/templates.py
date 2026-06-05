"""
signals.services.templates
===========================

Шаблоны ОБРАБОТКИ (этап 5): сохранённые наборы параметров анализа, которые можно
применить к другим измерениям (в т.ч. сразу к нескольким). Шаблон НЕ трогает
измерительные настройки (start/end/sweep — они свои у каждого измерения), а
сохраняет только «обработку»: сдвиг/длину строба, уровень, усиление, нормировку,
стратегию фронта и выбор каналов.

Хранилище — ~/.signals/templates.json (отдельно от настроек интерфейса).
"""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATES_PATH = Path.home() / ".signals" / "templates.json"

# Поля обработки, которые сохраняет/применяет шаблон (без частот свипа).
PROCESSING_FIELDS = ["cut_second", "fixedlevel", "gain", "normalize",
                     "edge_strategy", "record_time"]


def load_templates() -> dict:
    try:
        data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_all(data: dict) -> None:
    TEMPLATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")


def template_names() -> list[str]:
    return sorted(load_templates())


def save_template(name: str, analysis) -> dict:
    """Сохранить обработку выбранного измерения как шаблон с именем name."""
    data = load_templates()
    p = analysis.params
    rec = {f: getattr(p, f) for f in PROCESSING_FIELDS}
    rec["signal_start_channel"] = analysis.signal_start_channel
    rec["selected_channel"] = analysis.selected_channel
    data[name] = rec
    _save_all(data)
    return rec


def delete_template(name: str) -> None:
    data = load_templates()
    if name in data:
        data.pop(name); _save_all(data)


def apply_template(name: str, analysis) -> bool:
    """Применить шаблон к измерению (меняет только поля обработки). True — успех."""
    rec = load_templates().get(name)
    if not rec:
        return False
    for f in PROCESSING_FIELDS:
        if f in rec:
            setattr(analysis.params, f, rec[f])
    ssc = rec.get("signal_start_channel")
    if ssc and ssc in analysis.channels:
        analysis.signal_start_channel = ssc
    sel = rec.get("selected_channel")
    if sel and sel in analysis.channels:
        analysis.selected_channel = sel
    analysis.dirty = True
    return True
