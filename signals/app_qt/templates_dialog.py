"""
signals.app_qt.templates_dialog
===============================

Окно шаблонов обработки (этап 5). Слева — список шаблонов, справа — их содержимое.
Можно сохранить текущую обработку (параметры выбранного измерения + столбцы +
формулы) как шаблон и применить шаблон к выделенным измерениям или ко всем.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ..services import column_by_key
from ..services.templates import (
    apply_to_analysis, current_formula_columns, delete_template, get_template,
    register_formulas, save_template, template_names,
)
from . import theme


class TemplatesDialog(QDialog):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.mw = main_window
        self.setWindowTitle("Шаблоны обработки")
        self.resize(720, 520)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout(); root.addLayout(top, 1)

        left = QVBoxLayout(); top.addLayout(left, 0)
        left.addWidget(QLabel("Шаблоны:"))
        self.list = QListWidget(); self.list.setMinimumWidth(240)
        self.list.currentItemChanged.connect(lambda *_: self._show_details())
        left.addWidget(self.list, 1)
        self.apply_sel_btn = QPushButton("Применить к выделенным измерениям")
        self.apply_sel_btn.clicked.connect(lambda: self._apply("selected")); left.addWidget(self.apply_sel_btn)
        self.apply_all_btn = QPushButton("Применить ко всем измерениям")
        self.apply_all_btn.clicked.connect(lambda: self._apply("all")); left.addWidget(self.apply_all_btn)
        self.del_btn = QPushButton("Удалить шаблон")
        self.del_btn.clicked.connect(self._delete); left.addWidget(self.del_btn)

        right = QVBoxLayout(); top.addLayout(right, 1)
        right.addWidget(QLabel("Содержимое шаблона:"))
        self.details = QPlainTextEdit(); self.details.setReadOnly(True)
        right.addWidget(self.details, 1)

        # --- сохранить текущее как шаблон ---
        save_box = QVBoxLayout(); root.addLayout(save_box)
        save_box.addWidget(QLabel("Сохранить текущую настройку как шаблон:"))
        row = QHBoxLayout()
        self.name_edit = QLineEdit(); self.name_edit.setPlaceholderText("имя шаблона")
        row.addWidget(self.name_edit, 1)
        self.save_btn = QPushButton("Сохранить"); self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        save_box.addLayout(row)
        opts = QHBoxLayout(); save_box.addLayout(opts)
        self.cb_params = QCheckBox("Параметры обработки (из выделенного измерения)")
        self.cb_params.setChecked(True); opts.addWidget(self.cb_params)
        self.cb_cols = QCheckBox("Столбцы"); self.cb_cols.setChecked(True); opts.addWidget(self.cb_cols)
        self.cb_formulas = QCheckBox("Формулы"); self.cb_formulas.setChecked(True)
        opts.addWidget(self.cb_formulas)

        self.close_btn = QPushButton("Закрыть"); self.close_btn.clicked.connect(self.accept)
        root.addWidget(self.close_btn)

    # ---- список/детали -----------------------------------------------------
    def _reload(self, select: str | None = None) -> None:
        self.list.clear()
        for n in template_names():
            self.list.addItem(n)
        if select:
            items = self.list.findItems(
                select, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchExactly)
            if items:
                self.list.setCurrentItem(items[0])
        elif self.list.count():
            self.list.setCurrentRow(0)
        self._show_details()

    def _current(self) -> str | None:
        it = self.list.currentItem()
        return it.text() if it else None

    def _show_details(self) -> None:
        name = self._current()
        rec = get_template(name) if name else None
        if not rec:
            self.details.setPlainText(""); return
        lines = [f"Шаблон: {name}", ""]
        proc = {k: rec[k] for k in ("cut_second", "fixedlevel", "gain", "normalize",
                                    "edge_strategy", "record_time") if k in rec}
        if proc:
            lines.append("Параметры обработки:")
            for k, v in proc.items():
                lines.append(f"  {k} = {v}")
        if rec.get("signal_start_channel") or rec.get("selected_channel"):
            lines.append(f"Каналы: фронт {rec.get('signal_start_channel', '?')}, "
                         f"анализ {rec.get('selected_channel', '?')}")
        if rec.get("columns"):
            lines.append("Столбцы: " + ", ".join(rec["columns"]))
        if rec.get("formulas"):
            lines.append("Формулы:")
            for f in rec["formulas"]:
                lines.append(f"  {f.get('label', f['key'])} = {f.get('expr', '')}")
        self.details.setPlainText("\n".join(lines))

    # ---- применение --------------------------------------------------------
    def _targets(self, scope: str) -> list:
        if scope == "selected":
            return [it[2] for it in self.mw._checked_analyses()]
        return [a for s in self.mw.project.subjects for a in s.analyses]

    def _apply(self, scope: str) -> None:
        name = self._current()
        rec = get_template(name) if name else None
        if not rec:
            QMessageBox.information(self, "Шаблоны", "Выберите шаблон."); return
        targets = self._targets(scope)
        if scope == "selected" and not targets:
            QMessageBox.information(self, "Шаблоны",
                                    "Отметьте галочками измерения, к которым применить шаблон.")
            return
        n = sum(1 for a in targets if apply_to_analysis(rec, a))
        if rec.get("formulas"):
            register_formulas(rec["formulas"])
        if rec.get("columns"):
            cols = [c for c in (column_by_key(k) for k in rec["columns"]) if c]
            if cols:
                self.mw.dynamic_columns = cols
                theme.save_settings({"columns": [c["key"] for c in cols]})
        self.mw._cache.clear(); self.mw._thumbs.clear(); self.mw.refresh()
        extra = []
        if rec.get("columns"):
            extra.append("столбцы")
        if rec.get("formulas"):
            extra.append("формулы")
        tail = (" + " + ", ".join(extra)) if extra else ""
        QMessageBox.information(self, "Шаблоны",
                                f"Шаблон «{name}» применён к измерениям: {n}{tail}.")

    def _delete(self) -> None:
        name = self._current()
        if not name:
            return
        if QMessageBox.question(self, "Удалить", f"Удалить шаблон «{name}»?") \
                == QMessageBox.StandardButton.Yes:
            delete_template(name); self._reload()

    # ---- сохранение --------------------------------------------------------
    def _save(self) -> None:
        name = self.name_edit.text().strip() or (self._current() or "")
        if not name:
            QMessageBox.information(self, "Шаблоны", "Введите имя шаблона."); return
        analysis = None
        if self.cb_params.isChecked():
            checked = self.mw._checked_analyses()
            if not checked:
                QMessageBox.information(
                    self, "Шаблоны",
                    "Чтобы сохранить параметры обработки, отметьте галочкой измерение-образец "
                    "(его настройки и возьмём). Либо снимите галочку «Параметры обработки».")
                return
            analysis = checked[0][2]
        columns = [c["key"] for c in self.mw.dynamic_columns] if self.cb_cols.isChecked() else None
        formulas = current_formula_columns() if self.cb_formulas.isChecked() else None
        if analysis is None and columns is None and formulas is None:
            QMessageBox.information(self, "Шаблоны", "Отметьте, что сохранять."); return
        save_template(name, analysis=analysis, columns=columns, formulas=formulas)
        self.name_edit.clear()
        self._reload(select=name)
        QMessageBox.information(self, "Шаблоны", f"Шаблон «{name}» сохранён.")
