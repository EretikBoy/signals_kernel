"""
signals.app_qt.summary_dialog
=============================

Сводный анализ: наложение АЧХ выбранных измерений на общей сетке частот,
переключение видимости датасетов, маркеры резонанса, метрики, выражения над
датасетами (g1, g2, …) и экспорт в Excel.

АЧХ строится по каналу, выбранному для анализа (`selected_channel`) — именно
он несёт отклик измеряемой системы, остальные каналы тут не нужны. Выражения
над датасетами считаются в песочнице (ограниченный AST, без доступа к
builtins); доступны функции из реестра FUNCTIONS.
"""
from __future__ import annotations

import ast

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qt import NavigationToolbar2QT
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ..engine import channel_metrics
from ..extpoints import FUNCTIONS
from ..runtime_ext import _check_safe
from ..services import analyze_full
from ..services.clipboard_data import parse_clipboard_table
from .curve_interactor import CurveInteractor, ImportWizardPopup


class SummaryDialog(QDialog):
    def __init__(self, analyses: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сводный анализ")
        self.resize(1060, 680)
        self.datasets: list[dict] = []
        self._expr_curve = None
        self._collect(analyses)
        self._build_ui()
        self._build_grid()
        self._fill_metrics()
        self.redraw()

    def _collect(self, analyses: list) -> None:
        for idx, (label, analysis) in enumerate(analyses, start=1):
            result = analyze_full(analysis)
            ch = analysis.selected_channel or analysis.signal_start_channel \
                or next(iter(analysis.channels), "")
            amp = result.amplitude.get(ch)
            if amp is None or not getattr(amp, "size", 0) or not result.freqs.size:
                continue
            m = channel_metrics(result, ch, analysis.params.fixedlevel)
            self.datasets.append({"key": f"g{idx}", "label": f"g{idx}: {label} [{ch}]",
                                  "freqs": result.freqs, "amp": amp, "metrics": m})

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout(); root.addLayout(left, 0)
        left.addWidget(QLabel("Датасеты (отметьте для показа):"))
        self.list = QListWidget(); self.list.setMinimumWidth(280)
        for ds in self.datasets:
            it = QListWidgetItem(ds["label"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(it)
        self.list.itemChanged.connect(lambda *_: self.redraw())
        left.addWidget(self.list, 1)

        self.show_res = QCheckBox("Отмечать резонанс"); self.show_res.setChecked(True)
        self.show_res.toggled.connect(self.redraw); left.addWidget(self.show_res)

        left.addWidget(QLabel("Выражение (g1, g2, …; функции: " +
                              ", ".join(e.key for e in FUNCTIONS) + "):"))
        self.expr = QLineEdit(); self.expr.setPlaceholderText("например: g1 / g2")
        left.addWidget(self.expr)
        eval_btn = QPushButton("Вычислить и наложить"); eval_btn.clicked.connect(self.evaluate)
        left.addWidget(eval_btn)
        clear_btn = QPushButton("Убрать выражение"); clear_btn.clicked.connect(self._clear_expr)
        left.addWidget(clear_btn)
        left.addWidget(QLabel("Метрики:"))
        self.metrics_view = QPlainTextEdit(); self.metrics_view.setReadOnly(True)
        self.metrics_view.setMaximumHeight(160); left.addWidget(self.metrics_view)
        export_btn = QPushButton("Экспорт в Excel…"); export_btn.clicked.connect(self.export_excel)
        left.addWidget(export_btn)
        board_btn = QPushButton("Открыть в наборе кривых")
        board_btn.clicked.connect(self._to_curve_board); left.addWidget(board_btn)

        right = QVBoxLayout(); root.addLayout(right, 1)
        self.figure = Figure(figsize=(7, 4.5)); self.canvas = FigureCanvasQTAgg(self.figure)
        right.addWidget(NavigationToolbar2QT(self.canvas, self))
        right.addWidget(self.canvas, 1)
        self.sum_status = QLabel("ЛКМ по кривой — выделить, Ctrl+C — копировать; "
                                 "Ctrl+V — вставить кривую из Excel.")
        self.sum_status.setStyleSheet("color: gray;"); right.addWidget(self.sum_status)
        self._imports: list[dict] = []
        self.interactor = CurveInteractor(
            self.canvas, None, self, decimal_getter=lambda: ",",
            on_status=self.sum_status.setText, on_paste=self._paste_overlay)
        self.wizard = ImportWizardPopup(self, self._wizard_change)

    def _build_grid(self) -> None:
        if not self.datasets:
            self.grid = np.array([]); return
        lo = max(ds["freqs"].min() for ds in self.datasets)
        hi = min(ds["freqs"].max() for ds in self.datasets)
        if not (hi > lo):                              # диапазоны не пересеклись
            lo = min(ds["freqs"].min() for ds in self.datasets)
            hi = max(ds["freqs"].max() for ds in self.datasets)
        n = max((ds["amp"].size for ds in self.datasets), default=1000)
        self.grid = np.linspace(lo, hi, int(min(max(n, 2), 4000)))
        for ds in self.datasets:
            ds["interp"] = np.interp(self.grid, ds["freqs"], ds["amp"])

    def _fill_metrics(self) -> None:
        lines = []
        for ds in self.datasets:
            m = ds.get("metrics") or {}
            lines.append(
                f"{ds['key']}: резонанс {m.get('resonance_frequency', float('nan')):.2f} Гц, "
                f"Q {m.get('q_factor', float('nan')):.2f}, "
                f"макс {m.get('max_amplitude', float('nan')):.2f}")
        self.metrics_view.setPlainText("\n".join(lines) or "Нет данных")

    def _checked(self) -> list[dict]:
        out = []
        for i in range(self.list.count()):
            if self.list.item(i).checkState() == Qt.CheckState.Checked:
                out.append(self.datasets[i])
        return out

    def evaluate(self) -> None:
        text = self.expr.text().strip()
        if not text or self.grid.size == 0:
            return
        try:
            tree = ast.parse(text, mode="eval"); _check_safe(tree)
            names = {e.key: e.target for e in FUNCTIONS}
            names["freqs"] = self.grid
            for ds in self.datasets:
                names[ds["key"]] = ds["interp"]
            self._expr_curve = np.asarray(
                eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, names))
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.warning(self, "Ошибка выражения", str(exc)); return
        self.redraw()

    def _clear_expr(self) -> None:
        self._expr_curve = None; self.expr.clear(); self.redraw()

    def redraw(self) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        self.interactor.ax = ax; self.interactor.clear()
        for ds in self._checked():
            line, = ax.plot(self.grid, ds["interp"], label=ds["label"])
            self.interactor.add(ds["label"], self.grid, ds["interp"], line)
            if self.show_res.isChecked():
                m = ds.get("metrics") or {}
                rf = m.get("resonance_frequency")
                if rf and self.grid.min() <= rf <= self.grid.max():
                    ax.axvline(rf, color=line.get_color(), linestyle=":", alpha=0.6)
        if self._expr_curve is not None and self._expr_curve.shape == self.grid.shape:
            el, = ax.plot(self.grid, self._expr_curve, "k--", linewidth=2,
                          label=f"выражение: {self.expr.text()}")
            self.interactor.add("выражение", self.grid, self._expr_curve, el)
        for imp in self._imports:                       # вставленные из Excel наложения
            il, = ax.plot(imp["x"], imp["y"], linestyle=":", linewidth=1.4, label=imp["name"])
            self.interactor.add(imp["name"], imp["x"], imp["y"], il)
        ax.set_xlabel("Частота, Гц"); ax.set_ylabel("Амплитуда")
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3); self.figure.tight_layout()
        self.canvas.draw_idle()

    def _paste_overlay(self) -> None:
        text = QApplication.clipboard().text()
        r = parse_clipboard_table(text)
        if not r.ok:
            self.sum_status.setText("Буфер пуст или не разобрался: " + "; ".join(r.info)); return
        self._last_clip = text
        self._imports.append({"name": f"Импорт {len(self._imports) + 1}", "x": r.x, "y": r.y})
        self.redraw()
        if self.interactor.curves:
            self.interactor.select(self.interactor.curves[-1])
        self.wizard.popup_at(self.width() - 380, 64)
        self._wizard_feedback(r)

    def _wizard_change(self, decimal, swap, transpose) -> None:
        if not self._imports:
            return
        r = parse_clipboard_table(getattr(self, "_last_clip", ""), swap_xy=swap,
                                  transpose=transpose, decimal=decimal)
        if r.ok:
            self._imports[-1]["x"], self._imports[-1]["y"] = r.x, r.y
            self.redraw()
        self._wizard_feedback(r)

    def _wizard_feedback(self, r) -> None:
        pv = "\n".join(f"{x:g} → {y:g}" for x, y in zip(r.x[:3], r.y[:3]))
        self.wizard.set_feedback(f"{r.x.size} точек: " + "; ".join(r.info), pv)

    def _copy_curve(self) -> None:
        from PyQt6.QtWidgets import QApplication
        from ..services.clipboard_data import curve_to_tsv
        i = self.list.currentRow()
        if not (0 <= i < len(self.datasets)):
            QMessageBox.information(self, "Кривые", "Выберите датасет в списке."); return
        ds = self.datasets[i]
        QApplication.clipboard().setText(curve_to_tsv(ds["freqs"], ds["amp"], decimal=","))
        QMessageBox.information(self, "Кривые",
                                f"Кривая «{ds['label']}» скопирована в буфер — вставьте в Excel.")

    def _to_curve_board(self) -> None:
        from .curve_board import CurveBoard
        seed = [(ds["label"], ds["freqs"], ds["amp"]) for ds in self.datasets]
        if not hasattr(self, "_boards"):
            self._boards = []
        b = CurveBoard(self, seed=seed); self._boards.append(b); b.show()

    def export_excel(self) -> None:
        if not self.datasets:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить сводку", "summary.xlsx",
                                              "Excel (*.xlsx)")
        if not path:
            return
        ach = {"Частота, Гц": self.grid}
        for ds in self.datasets:
            ach[ds["label"]] = ds["interp"]
        if self._expr_curve is not None and self._expr_curve.shape == self.grid.shape:
            ach[f"выражение: {self.expr.text()}"] = self._expr_curve
        metrics = []
        for ds in self.datasets:
            m = ds.get("metrics") or {}
            metrics.append({"Датасет": ds["label"],
                            "Резонанс, Гц": m.get("resonance_frequency"),
                            "Полоса -3дБ, Гц": m.get("bandwidth_707"),
                            "Добротность": m.get("q_factor"),
                            "Макс. амплитуда": m.get("max_amplitude")})
        try:
            with pd.ExcelWriter(path, engine="openpyxl") as xw:
                pd.DataFrame(ach).to_excel(xw, sheet_name="АЧХ", index=False)
                pd.DataFrame(metrics).to_excel(xw, sheet_name="Метрики", index=False)
            QMessageBox.information(self, "Экспорт", f"Сохранено: {path}")
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.warning(self, "Ошибка экспорта", str(exc))
