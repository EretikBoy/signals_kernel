"""
signals.app_qt.curve_board
==========================

Интерактивный «Набор кривых» (этап 6). Стандартные «экселевские» взаимодействия:

  ЛКМ — выделить кривую (толще + ореол); Ctrl+ЛКМ — добавить/убрать из выделения;
  ПКМ по полю — список кривых (показать/скрыть/выделить/удалить);
  Ctrl+C копировать (несколько — столбцами), Ctrl+V вставить (+мастер импорта),
  Ctrl+X вырезать, Ctrl+Z отменить, Ctrl+Y/Ctrl+Shift+Z повторить, Ctrl+A выделить
  все, Ctrl+D дублировать, Del удалить, H скрыть/показать выделенные, Esc снять.

Поддерживает свой язык формул над кривыми (g1, g2, …; срез по частоте g1[a:b]):
если результат — число, оно отмечается на графике (точкой, полосой или
касательной), если кривая — добавляется как новая. Сам язык — в curve_expr.
"""
from __future__ import annotations

import copy

import numpy as np
from matplotlib.backends.backend_qt import NavigationToolbar2QT
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QVBoxLayout,
)

from . import curve_expr
from ..services.clipboard_data import parse_clipboard_table
from .curve_interactor import CurveInteractor, ImportWizardPopup, _idx_id

_CTX = Qt.ShortcutContext.WidgetWithChildrenShortcut


class CurveBoard(QDialog):
    def __init__(self, parent=None, seed=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Набор кривых")
        self.resize(1080, 700)
        self.curves: list[dict] = []
        self._last_clip = ""
        self._pasted: dict | None = None
        self._annotations: list = []
        self._undo: list = []
        self._redo: list = []
        self._guard = False
        self._build_ui()
        self._install_shortcuts()
        for name, x, y in (seed or []):
            self._add(name, np.asarray(x, float), np.asarray(y, float))
        self._redraw()

    # ---- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout(); root.addLayout(left, 0)
        hint = QLabel("ЛКМ — выделить, Ctrl+ЛКМ — несколько, ПКМ — список.\n"
                      "Ctrl+C/V/X/Z/Y, Del, Ctrl+A/D, H — как в Excel.")
        hint.setStyleSheet("color: gray;"); left.addWidget(hint)
        self.list = QListWidget(); self.list.setMinimumWidth(290)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemChanged.connect(lambda *_: self._redraw())
        self.list.itemSelectionChanged.connect(self._on_list_selection)
        left.addWidget(self.list, 1)

        row = QHBoxLayout(); left.addLayout(row)
        row.addWidget(QLabel("Копировать как:"))
        self.copy_dec = QComboBox(); self.copy_dec.addItems(["запятая  ,", "точка  ."])
        row.addWidget(self.copy_dec, 1)

        left.addWidget(QLabel("Своя формула над кривыми (g1, g2, …):"))
        self.vars_lbl = QLabel(""); self.vars_lbl.setWordWrap(True)
        self.vars_lbl.setStyleSheet("color: gray; font-size: 11px;")
        left.addWidget(self.vars_lbl)
        self.expr = QLineEdit()
        self.expr.setPlaceholderText("max(g1[2280:2320])  |  integral(band(g1,0.707))  |  log(g1)")
        self.expr.returnPressed.connect(self._eval_expr); left.addWidget(self.expr)
        self.name_edit = QLineEdit(); self.name_edit.setPlaceholderText("имя результата (необязательно)")
        left.addWidget(self.name_edit)
        funcs = QLabel("срез по частоте g1[a:b]; функции: max, min, mean, sum/integral, "
                       "band(g,0.707), tangent(g,f), at(g,f), argmax, derivative, log, exp, sqrt…")
        funcs.setWordWrap(True); funcs.setStyleSheet("color: gray; font-size: 11px;")
        left.addWidget(funcs)
        eval_btn = QPushButton("Создать / вычислить (Enter)"); eval_btn.clicked.connect(self._eval_expr)
        left.addWidget(eval_btn)

        right = QVBoxLayout(); root.addLayout(right, 1)
        self.figure = Figure(figsize=(7.2, 5.2)); self.canvas = FigureCanvasQTAgg(self.figure)
        right.addWidget(NavigationToolbar2QT(self.canvas, self))
        right.addWidget(self.canvas, 1)
        self.canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.canvas.customContextMenuRequested.connect(self._context_menu)
        self.ax = self.figure.add_subplot(111)
        self.status = QLabel("ЛКМ — выделить, Ctrl+C — копировать, Ctrl+V — вставить.")
        right.addWidget(self.status)

        self.interactor = CurveInteractor(
            self.canvas, self.ax, self,
            decimal_getter=lambda: "," if self.copy_dec.currentIndex() == 0 else ".",
            on_status=self.status.setText, on_paste=self._paste,
            on_select=self._on_plot_select)
        self.wizard = ImportWizardPopup(self, self._wizard_change)

    def _sc(self, key, slot, widgets) -> None:
        for w in widgets:
            QShortcut(key, w, slot, context=_CTX)

    def _install_shortcuts(self) -> None:
        both = (self.canvas, self.list)          # действия активны на полотне и в списке
        self._sc(QKeySequence.StandardKey.Cut, self._cut, both)
        self._sc(QKeySequence.StandardKey.Undo, self._undo_act, both)
        self._sc(QKeySequence.StandardKey.Redo, self._redo_act, both)
        self._sc(QKeySequence("Ctrl+Shift+Z"), self._redo_act, both)
        self._sc(QKeySequence.StandardKey.SelectAll, self._select_all, both)
        self._sc(QKeySequence.StandardKey.Delete, self._delete, both)
        self._sc(QKeySequence(Qt.Key.Key_Delete), self._delete, both)
        self._sc(QKeySequence("Ctrl+D"), self._duplicate, both)
        self._sc(QKeySequence("Ctrl+H"), self._hide_selected, both)
        # копировать/вставить/снять — на списке (на полотне это делает интерактор)
        self._sc(QKeySequence.StandardKey.Copy, self.interactor.copy_selected, (self.list,))
        self._sc(QKeySequence.StandardKey.Paste, self._paste, (self.list,))
        self._sc(QKeySequence(Qt.Key.Key_Escape), self.interactor.clear_selection, (self.list,))

    # ---- модель/список -----------------------------------------------------
    def _add(self, name: str, x, y, visible: bool = True) -> dict:
        c = {"name": name, "x": np.asarray(x, float), "y": np.asarray(y, float)}
        self.curves.append(c)
        it = QListWidgetItem(name)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked)
        self.list.addItem(it)
        self._update_vars()
        return c

    def _update_vars(self) -> None:
        self.vars_lbl.setText(("переменные: " + ", ".join(
            f"g{i+1}={c['name']}" for i, c in enumerate(self.curves))) if self.curves else "нет кривых")

    def _selected_curves(self) -> list:
        # выделение списка переживает скрытие и охватывает скрытые кривые
        return [self.curves[self.list.row(it)] for it in self.list.selectedItems()]

    def _on_list_selection(self) -> None:
        if self._guard:
            return
        self._guard = True
        rows = sorted(self.list.row(it) for it in self.list.selectedItems())
        self.interactor.select_many([self.curves[r] for r in rows if 0 <= r < len(self.curves)])
        self._guard = False

    def _on_plot_select(self, curves_list) -> None:
        if self._guard:
            return
        self._guard = True
        self.list.clearSelection()
        for c in curves_list:
            i = _idx_id(self.curves, c)
            if i >= 0:
                self.list.item(i).setSelected(True)
        self._guard = False

    # ---- undo/redo ---------------------------------------------------------
    def _snapshot(self) -> None:
        snap = [{"name": c["name"], "x": c["x"].copy(), "y": c["y"].copy(),
                 "visible": self.list.item(i) is None or
                 self.list.item(i).checkState() == Qt.CheckState.Checked}
                for i, c in enumerate(self.curves)]
        self._undo.append(snap)
        if len(self._undo) > 50:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, snap) -> None:
        self.curves = []; self.list.clear(); self.interactor._sel_names = set()
        for c in snap:
            self._add(c["name"], c["x"], c["y"], c.get("visible", True))
        self._annotations = []; self._redraw()

    def _undo_act(self) -> None:
        if not self._undo:
            self.status.setText("Отменять нечего."); return
        cur = [{"name": c["name"], "x": c["x"].copy(), "y": c["y"].copy(),
                "visible": self.list.item(i).checkState() == Qt.CheckState.Checked}
               for i, c in enumerate(self.curves)]
        self._redo.append(cur)
        self._restore(self._undo.pop()); self.status.setText("Отменено (Ctrl+Z).")

    def _redo_act(self) -> None:
        if not self._redo:
            self.status.setText("Повторять нечего."); return
        cur = [{"name": c["name"], "x": c["x"].copy(), "y": c["y"].copy(),
                "visible": self.list.item(i).checkState() == Qt.CheckState.Checked}
               for i, c in enumerate(self.curves)]
        self._undo.append(cur)
        self._restore(self._redo.pop()); self.status.setText("Повторено.")

    # ---- буфер обмена ------------------------------------------------------
    def _paste(self) -> None:
        self._last_clip = QApplication.clipboard().text()
        r = parse_clipboard_table(self._last_clip)
        if not r.ok:
            self.status.setText("Буфер пуст или не разобрался: " + "; ".join(r.info)); return
        self._snapshot(); self._annotations = []
        self._pasted = self._add(self._make_name(), r.x, r.y)
        self._redraw(); self.interactor.select(self._pasted)
        self.wizard.popup_at(); self._feedback(r)

    def _wizard_change(self, decimal, swap, transpose) -> None:
        if self._pasted is None or _idx_id(self.curves, self._pasted) < 0:
            return
        r = parse_clipboard_table(self._last_clip, swap_xy=swap, transpose=transpose, decimal=decimal)
        if r.ok:
            self._pasted["x"], self._pasted["y"] = r.x, r.y
            self.interactor._sel_names = {self._pasted["name"]}
            self._redraw()
            self.list.item(_idx_id(self.curves, self._pasted)).setSelected(True)
        self._feedback(r)

    def _feedback(self, r) -> None:
        pv = "\n".join(f"{x:g} → {y:g}" for x, y in zip(r.x[:3], r.y[:3]))
        self.wizard.set_feedback(f"{r.x.size} точек: " + "; ".join(r.info), pv)

    def _make_name(self) -> str:
        n = sum(1 for c in self.curves if c["name"].startswith("Вставка")) + 1
        return f"Вставка {n}"

    def _cut(self) -> None:
        if not self._selected_curves():
            return
        self.interactor.copy_selected(); self._delete()
        self.status.setText("Вырезано (Ctrl+X).")

    # ---- формула -----------------------------------------------------------
    def _eval_expr(self) -> None:
        expr = self.expr.text().strip()
        if not expr or not self.curves:
            return
        try:
            res = curve_expr.evaluate(expr, self.curves)
        except Exception as exc:                       # noqa: BLE001
            self.status.setText(f"Ошибка в формуле: {exc}"); return
        self._annotations = res.get("annotations", [])
        if res["kind"] == "curve":
            self._snapshot()
            name = self.name_edit.text().strip() or f"f: {expr}"
            c = self._add(name, res["x"], res["y"]); self._redraw(); self.interactor.select(c)
            self.status.setText(f"Создана кривая: {name}")
        else:
            self._redraw()
            self.status.setText(f"{expr} = {res['value']:.6g}  (отмечено на графике)")

    # ---- видимость/удаление ------------------------------------------------
    def _delete(self) -> None:
        sel = self._selected_curves()
        if not sel:
            return
        self._snapshot(); self._annotations = []
        for c in sel:
            i = _idx_id(self.curves, c)
            if i < 0:
                continue
            self.curves.pop(i); self.list.takeItem(i)
            if self._pasted is c:
                self._pasted = None
        self.interactor._sel_names = set(); self._update_vars(); self._redraw()
        self.status.setText(f"Удалено кривых: {len(sel)}.")

    def _hide_selected(self) -> None:
        sel = self._selected_curves()
        if not sel:
            return
        any_visible = any(self.list.item(_idx_id(self.curves, c)).checkState() == Qt.CheckState.Checked
                          for c in sel if _idx_id(self.curves, c) >= 0)
        new = Qt.CheckState.Unchecked if any_visible else Qt.CheckState.Checked
        for c in sel:
            i = _idx_id(self.curves, c)
            if i >= 0:
                self.list.item(i).setCheckState(new)
        self.status.setText("Скрыто." if any_visible else "Показано.")

    def _show_all(self) -> None:
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked)

    def _select_all(self) -> None:
        self.interactor.select_many(list(self.curves))

    def _duplicate(self) -> None:
        sel = self._selected_curves()
        if not sel:
            return
        self._snapshot()
        for c in sel:
            self._add(f"{c['name']} (копия)", c["x"].copy(), c["y"].copy())
        self._redraw()

    # ---- контекст-меню по ПКМ ---------------------------------------------
    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        for i, c in enumerate(self.curves):
            act = menu.addAction(c["name"])
            act.setCheckable(True)
            it = self.list.item(i)
            act.setChecked(it.checkState() == Qt.CheckState.Checked)
            act.toggled.connect(lambda on, i=i: self.list.item(i).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked))
        if self.curves:
            menu.addSeparator()
        menu.addAction("Скрыть/показать выделенные (H)", self._hide_selected)
        menu.addAction("Показать все", self._show_all)
        menu.addAction("Дублировать выделенные (Ctrl+D)", self._duplicate)
        menu.addAction("Удалить выделенные (Del)", self._delete)
        menu.addAction("Снять выделение (Esc)", self.interactor.clear_selection)
        menu.exec(self.canvas.mapToGlobal(pos))

    # ---- отрисовка ---------------------------------------------------------
    def _draw_annotations(self, ax) -> None:
        for a in self._annotations:
            t = a["type"]
            if t == "point":
                ax.plot([a["x"]], [a["y"]], "o", color="crimson", zorder=15)
                ax.annotate(a.get("text", ""), (a["x"], a["y"]), textcoords="offset points",
                            xytext=(6, 6), color="crimson", fontsize=9)
            elif t == "vline":
                ax.axvline(a["x"], color="crimson", linestyle="--", linewidth=1)
            elif t == "vspan":
                ax.axvspan(a["x0"], a["x1"], color="orange", alpha=0.18)
                if a.get("text"):
                    ax.text((a["x0"] + a["x1"]) / 2, ax.get_ylim()[1] * 0.92, a["text"],
                            ha="center", color="darkorange", fontsize=10)
            elif t == "hline":
                ax.axhline(a["y"], color="green", linestyle="--", linewidth=1)
                if a.get("text"):
                    ax.text(a.get("x1", ax.get_xlim()[1]), a["y"], a["text"],
                            color="green", fontsize=9, va="bottom", ha="right")
            elif t == "tangent":
                ax.plot([a["x0"], a["x1"]], [a["y0"], a["y1"]], color="purple", linewidth=1.6)
                ax.plot([a["px"]], [a["py"]], "o", color="purple", zorder=15)
                ax.annotate(a.get("text", ""), (a["px"], a["py"]), textcoords="offset points",
                            xytext=(6, -12), color="purple", fontsize=9)

    def _redraw(self) -> None:
        for i, c in enumerate(self.curves):
            it = self.list.item(i)
            c["visible"] = it is None or it.checkState() == Qt.CheckState.Checked
        self.figure.clear(); self.ax = self.figure.add_subplot(111)
        self.interactor.ax = self.ax; self.interactor.clear()
        for c in self.curves:
            if not c.get("visible", True) or c["x"].size == 0:
                continue
            line, = self.ax.plot(c["x"], c["y"], linewidth=1.4, label=c["name"], picker=5)
            self.interactor.add_curve(c, line)
        self._draw_annotations(self.ax)
        if self.ax.get_legend_handles_labels()[0]:
            self.ax.legend(fontsize=8)
        self.ax.grid(True, alpha=0.3); self.figure.tight_layout(); self.canvas.draw_idle()
