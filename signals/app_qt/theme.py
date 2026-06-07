"""
signals.app_qt.theme
====================

Темизация: встроенные светлая и тёмная темы + возможность загрузить свой .qss
(кастомизация, как в Discord). Выбор сохраняется в ~/.signals/settings.json.

Стили подобраны так, чтобы каждый интерактивный элемент «кричал» о себе:
кнопки с заметной заливкой/границей и эффектами hover/pressed, видимые стрелки
у спинбоксов и комбобоксов, подсветка выделения в дереве.
"""
from __future__ import annotations

import json
from pathlib import Path
from string import Template

from PyQt6.QtWidgets import QApplication, QStyleFactory

SETTINGS_PATH = Path.home() / ".signals" / "settings.json"

# Стиль виджетов Qt. По умолчанию Fusion — он чистый, одинаковый на всех ОС и не
# тащит за собой «отвратительный» нативный стиль Windows 11. На Windows доступны также
# 'windowsvista' (вид Windows 10) и 'windows11'.
DEFAULT_STYLE = "Fusion"
SYSTEM_THEME = "Системная (без темы)"

PALETTES = {
    "Тёмная": dict(
        bg="#2b2d31", surface="#313338", surface2="#383a40", elevated="#404249",
        text="#dbdee1", subtext="#b5bac1", border="#1e1f22",
        accent="#5865f2", accent_hover="#4752c4", accent_pressed="#3c45a5",
        on_accent="#ffffff", danger="#da373c", success="#248046",
    ),
    "Светлая": dict(
        bg="#f2f3f5", surface="#ffffff", surface2="#ebedef", elevated="#e3e5e8",
        text="#2e3338", subtext="#4e5058", border="#cdd0d4",
        accent="#5865f2", accent_hover="#4752c4", accent_pressed="#3c45a5",
        on_accent="#ffffff", danger="#da373c", success="#248046",
    ),
}

_QSS = Template("""
QWidget { background-color: $bg; color: $text; font-size: 13px; }
QMainWindow, QDialog { background-color: $bg; }
QGroupBox {
    background-color: $surface; border: 1px solid $border; border-radius: 8px;
    margin-top: 14px; padding: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px; padding: 0 4px;
    color: $subtext; font-weight: bold;
}
QLabel { background: transparent; }

/* Кнопки — заметные, с откликом */
QPushButton {
    background-color: $surface2; color: $text;
    border: 1px solid $border; border-radius: 6px;
    padding: 7px 14px; font-weight: 600;
}
QPushButton:hover { background-color: $elevated; border-color: $accent; }
QPushButton:pressed { background-color: $accent_pressed; color: $on_accent; }
QPushButton:disabled { color: $subtext; border-color: $surface2; }
QPushButton[accent="true"] {
    background-color: $accent; color: $on_accent; border: none;
}
QPushButton[accent="true"]:hover { background-color: $accent_hover; }
QPushButton[danger="true"] { background-color: $danger; color: #fff; border: none; }

/* Поля ввода и крутилки — видимые стрелки */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background-color: $surface; color: $text;
    border: 1px solid $border; border-radius: 6px; padding: 5px 8px;
    selection-background-color: $accent; selection-color: $on_accent;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid $accent;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 18px; background-color: $surface2; border-left: 1px solid $border;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: $accent;
}
QComboBox::drop-down { width: 22px; border-left: 1px solid $border; background: $surface2; }
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $border;
    selection-background-color: $accent; selection-color: $on_accent;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border: 1px solid $border; border-radius: 4px;
    background: $surface;
}
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }

/* Дерево */
QTreeWidget, QTreeView {
    background-color: $surface; alternate-background-color: $surface2;
    border: 1px solid $border; border-radius: 8px;
}
QTreeView::item { padding: 5px; }
QTreeView::item:hover { background-color: $elevated; }
QTreeView::item:selected { background-color: $accent; color: $on_accent; }
QHeaderView::section {
    background-color: $surface2; color: $subtext; padding: 6px;
    border: none; border-right: 1px solid $border; font-weight: bold;
}
QHeaderView::section:hover { background-color: $elevated; color: $text; }
QHeaderView::section:pressed { background-color: $accent; color: $on_accent; }
QListView::item:hover, QListWidget::item:hover { background-color: $elevated; }
QListView::item:selected, QListWidget::item:selected {
    background-color: $accent; color: $on_accent;
}
QPushButton:focus, QToolButton:focus { border: 1px solid $accent; }

/* Тулбар, доки, меню */
QToolBar { background: $surface; border-bottom: 1px solid $border; spacing: 4px; padding: 4px; }
QToolBar QToolButton {
    background: $surface2; border: 1px solid $border; border-radius: 6px;
    padding: 6px 10px; font-weight: 600;
}
QToolBar QToolButton:hover { background: $elevated; border-color: $accent; }
QToolBar QToolButton:pressed { background: $accent; color: $on_accent; }
QDockWidget { titlebar-close-icon: none; }
QDockWidget::title {
    background: $surface2; padding: 6px; border-bottom: 1px solid $border; font-weight: bold;
}
QMenuBar { background: $surface; }
QMenuBar::item:selected { background: $accent; color: $on_accent; }
QMenu { background: $surface; border: 1px solid $border; }
QMenu::item:selected { background: $accent; color: $on_accent; }
QProgressBar {
    border: 1px solid $border; border-radius: 6px; text-align: center;
    background: $surface; height: 18px;
}
QProgressBar::chunk { background-color: $accent; border-radius: 5px; }
QScrollBar:vertical { background: $surface; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: $elevated; border-radius: 6px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
""")


def build_qss(theme: str) -> str:
    palette = PALETTES.get(theme, PALETTES["Тёмная"])
    return _QSS.substitute(palette)


def list_themes() -> list[str]:
    return list(PALETTES) + [SYSTEM_THEME]


def list_styles() -> list[str]:
    """Доступные стили виджетов Qt (зависит от ОС)."""
    return list(QStyleFactory.keys())


def apply_style(app: QApplication, style: str | None = None) -> None:
    """Применить стиль виджетов Qt (по умолчанию Fusion вместо нативного Win11)."""
    name = style or DEFAULT_STYLE
    keys = {k.lower(): k for k in QStyleFactory.keys()}
    real = keys.get(name.lower())
    if real:
        app.setStyle(real)


def apply_theme(app: QApplication, theme: str) -> None:
    """Тема по имени, путь к .qss, или «Системная» (без QSS — нативный вид стиля)."""
    if theme == SYSTEM_THEME:
        app.setStyleSheet("")
        return
    path = Path(theme)
    if theme not in PALETTES and path.suffix == ".qss" and path.exists():
        app.setStyleSheet(path.read_text(encoding="utf-8"))
    else:
        app.setStyleSheet(build_qss(theme))


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("theme", "Тёмная")
    data.setdefault("style", DEFAULT_STYLE)
    return data


def save_settings(settings: dict) -> None:
    """Слить переданные ключи с уже сохранёнными и записать."""
    current = {}
    try:
        current = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    current.update(settings)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2),
                             encoding="utf-8")
