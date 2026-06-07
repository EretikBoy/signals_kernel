"""
signals.app_qt.curve_interactor
===============================

Здесь собрано общее поведение, которое одинаково работает с кривыми на любом
графике в приложении — раньше в каждом окне это было реализовано отдельно и
немного по-разному:

* клик по кривой — выделение: она становится толще, поднимается над остальными
  и получает лёгкий ореол, чтобы сразу было видно, с чем сейчас работаем —
  это состояние держится и видно ещё до того, как что-то сделали с кривой;
* наведение — курсор-рука и подсветка (аффорданс «на меня можно нажать»);
* Ctrl+C — скопировать выделенную кривую в буфер (формат для Excel);
* Ctrl+V — вставить кривую из буфера (хост решает, что делать);
* Esc — снять выделение.

`ImportWizardPopup` — лёгкая всплывающая панель «Мастер импорта», которая появляется
у места вставки и сама исчезает через несколько секунд; в ней на ходу правится
десятичный разделитель (в Excel он отличается от Python), X↔Y и «значения по рядам».
"""
from __future__ import annotations

import matplotlib.patheffects as pe
from matplotlib.axes import Axes
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout,
)

from ..services.clipboard_data import curve_to_tsv, curves_to_tsv


def _idx_id(seq, obj) -> int:
    """Найти объект в списке по физическому совпадению (`is`, не `==`).

    Обычное сравнение тут не работает: кривая хранится как словарь с
    numpy-массивом внутри, а сравнение массивов через `==` даёт массив
    булевых значений, а не True/False, и `in`/`==` на таком словаре упадут.
    """
    for i, x in enumerate(seq):
        if x is obj:
            return i
    return -1


class CurveInteractor:
    def __init__(self, canvas, axes: Axes | None, host, *, decimal_getter=None,
                 on_status=None, on_paste=None, on_select=None) -> None:
        self.canvas = canvas
        self.ax = axes
        self.host = host
        self._decimal = decimal_getter or (lambda: ",")
        self._status = on_status or (lambda s: None)
        self._on_select = on_select or (lambda c: None)
        self._on_paste = on_paste
        self.curves: list[dict] = []
        self.selected: dict | None = None          # основная (последняя кликнутая)
        self.selected_set: list[dict] = []         # множественное выделение (Ctrl+ЛКМ)
        self._sel_names: set[str] = set()
        self._hover: dict | None = None

        canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        canvas.mpl_connect("button_press_event", self._on_click)
        canvas.mpl_connect("motion_notify_event", self._on_motion)
        # шорткаты висят на холсте графика, а не на всём окне — иначе Ctrl+C/V
        # перехватывался бы и в текстовых полях, где должен работать обычный буфер обмена
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        QShortcut(QKeySequence.StandardKey.Copy, canvas, self.copy_selected, context=ctx)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), canvas, self.clear_selection, context=ctx)
        if on_paste is not None:
            QShortcut(QKeySequence.StandardKey.Paste, canvas, on_paste, context=ctx)

    # ---- регистрация кривых (хост вызывает после своей отрисовки) ----------
    def clear(self) -> None:
        self.curves = []
        self.selected = None
        self.selected_set = []

    def add(self, name: str, x, y, line) -> dict:
        c = {"name": name, "x": x, "y": y, "line": line,
             "base_lw": float(line.get_linewidth())}
        return self.add_curve(c, line)

    def add_curve(self, curve: dict, line) -> dict:
        """Связать нарисованную линию со словарём кривой, который передал вызывающий код.

        Так состояние выделения хранится прямо в этом общем словаре — окно,
        которое нарисовало кривую, и интерактор смотрят на одни и те же
        объекты, а не на свои копии, которые могли бы разойтись.
        """
        curve["line"] = line
        curve["base_lw"] = float(line.get_linewidth())
        self.curves.append(curve)
        if curve["name"] in self._sel_names:         # восстановить выделение после перерисовки
            self.selected_set.append(curve)
            self.selected = curve
            self._emphasize(curve, True)
        return curve

    # ---- стили -------------------------------------------------------------
    @staticmethod
    def _emphasize(c: dict, on: bool) -> None:
        line = c["line"]
        if on:
            line.set_linewidth(c["base_lw"] * 2.4)
            line.set_zorder(12)
            line.set_path_effects([pe.Stroke(linewidth=c["base_lw"] * 4.2,
                                             foreground=(1, 1, 1, 0.35)), pe.Normal()])
        else:
            line.set_linewidth(c["base_lw"])
            line.set_zorder(2)
            line.set_path_effects([])

    def _restyle_all(self) -> None:
        for c in self.curves:
            self._emphasize(c, _idx_id(self.selected_set, c) >= 0)
        self.canvas.draw_idle()

    def _commit_selection(self) -> None:
        self.selected = self.selected_set[-1] if self.selected_set else None
        self._sel_names = {c["name"] for c in self.selected_set}
        self._restyle_all()
        self._on_select(list(self.selected_set))
        if len(self.selected_set) > 1:
            self._status(f"Выделено кривых: {len(self.selected_set)} — Ctrl+C скопирует все.")
        elif self.selected:
            self._status(f"Выделена «{self.selected['name']}» — Ctrl+C копировать, "
                         "Del удалить, H скрыть.")

    # ---- действия ----------------------------------------------------------
    def select(self, c: dict | None) -> None:
        self.selected_set = [c] if c else []
        self._commit_selection()

    def select_many(self, curves: list) -> None:
        self.selected_set = [c for c in curves if _idx_id(self.curves, c) >= 0]
        self._commit_selection()

    def toggle(self, c: dict) -> None:
        i = _idx_id(self.selected_set, c)
        if i >= 0:
            del self.selected_set[i]
        else:
            self.selected_set.append(c)
        self._commit_selection()

    def clear_selection(self) -> None:
        if self.selected_set:
            self.selected_set = []
            self._commit_selection()
            self._status("Выделение снято.")

    def copy_selected(self) -> None:
        if not self.selected_set:
            self._status("Сначала выделите кривую (клик по линии), затем Ctrl+C.")
            return
        if len(self.selected_set) == 1:
            c = self.selected_set[0]
            QApplication.clipboard().setText(curve_to_tsv(c["x"], c["y"], decimal=self._decimal()))
            self._status(f"Скопировано: «{c['name']}» ({len(c['x'])} точек) → буфер.")
        else:
            data = [(c["x"], c["y"]) for c in self.selected_set]
            QApplication.clipboard().setText(curves_to_tsv(data, decimal=self._decimal()))
            self._status(f"Скопировано кривых: {len(data)} (столбцами) → буфер.")

    # ---- события мыши ------------------------------------------------------
    def _hit(self, event):
        best = None
        for c in self.curves:
            contains, _ = c["line"].contains(event)
            if contains:
                best = c
        return best

    def _on_click(self, event) -> None:
        if event.button != 1 or event.inaxes is not self.ax:
            return
        c = self._hit(event)
        ctrl = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        if ctrl and c:
            self.toggle(c)
        else:
            self.select(c)

    def _on_motion(self, event) -> None:
        c = self._hit(event) if event.inaxes is self.ax else None
        if c is not self._hover:
            # снять временную ховер-подсветку с прежней
            if self._hover is not None and _idx_id(self.selected_set, self._hover) < 0:
                self._emphasize(self._hover, False)
            self._hover = c
            if c is not None and _idx_id(self.selected_set, c) < 0:
                c["line"].set_linewidth(c["base_lw"] * 1.6)
            self.canvas.draw_idle()
        self.canvas.setCursor(Qt.CursorShape.PointingHandCursor if c
                              else Qt.CursorShape.ArrowCursor)


class ImportWizardPopup(QFrame):
    """Временная панель правки вставки (десятичный разделитель, X↔Y, по рядам)."""

    def __init__(self, host, on_change) -> None:
        super().__init__(host)
        self._on_change = on_change
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        self.setObjectName("importWizard")
        self.setStyleSheet("#importWizard { border: 1px solid palette(highlight);"
                           " border-radius: 8px; background: palette(window); }")
        lay = QVBoxLayout(self); lay.setContentsMargins(10, 8, 10, 8)
        title = QLabel("Мастер импорта — поправьте, если вставилось не так")
        title.setStyleSheet("font-weight: bold;"); lay.addWidget(title)

        row = QHBoxLayout(); lay.addLayout(row)
        row.addWidget(QLabel("Десятичный разделитель:"))
        self.dec = QComboBox(); self.dec.addItems(["Авто", "запятая  ,", "точка  ."])
        row.addWidget(self.dec)
        self.swap = QCheckBox("X ↔ Y"); row.addWidget(self.swap)
        self.transpose = QCheckBox("значения по рядам"); row.addWidget(self.transpose)

        self.info = QLabel(""); self.info.setWordWrap(True); self.info.setStyleSheet("color: gray;")
        lay.addWidget(self.info)
        self.preview = QLabel(""); self.preview.setStyleSheet("font-family: monospace;")
        lay.addWidget(self.preview)

        btns = QHBoxLayout(); lay.addLayout(btns); btns.addStretch(1)
        done = QPushButton("Готово"); done.clicked.connect(self.hide); btns.addWidget(done)

        for w in (self.dec, self.swap, self.transpose):
            (w.currentIndexChanged if isinstance(w, QComboBox) else w.toggled).connect(self._changed)

        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def decimal(self) -> str:
        return {0: "auto", 1: ",", 2: "."}[self.dec.currentIndex()]

    def _changed(self, *_) -> None:
        self._bump()
        self._on_change(self.decimal(), self.swap.isChecked(), self.transpose.isChecked())

    def set_feedback(self, info: str, preview: str) -> None:
        self.info.setText(info); self.preview.setText(preview)

    def _bump(self, ms: int = 6000) -> None:
        self._timer.start(ms)

    def popup_at(self, *_ignore) -> None:
        self.dec.setCurrentIndex(0); self.swap.setChecked(False); self.transpose.setChecked(False)
        self.adjustSize()
        host = self.parentWidget()
        w, h = self.width(), self.height()
        if host is not None:
            x = max(8, min((host.width() - w) // 2, host.width() - w - 8))
            y = max(8, min(70, max(8, host.height() - h - 8)))
        else:
            x, y = 40, 70
        self.move(x, y)
        self.show(); self.raise_(); self._bump()

    def enterEvent(self, event) -> None:       # пока мышь над панелью — не прячем
        self._timer.stop(); super().enterEvent(event)

    def leaveEvent(self, a0) -> None:
        self._bump(4000); super().leaveEvent(a0)
