"""
signals.app_qt.filter_dialog
============================

Фильтр — свойство столбца (как в оригинале): двойной клик по заголовку открывает
этот диалог для конкретного столбца. Тип: Все значения / Равно / Больше / Меньше /
Между; поле «До» активно только для «Между». Для столбца предмета — текстовый фильтр.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QVBoxLayout,
)

FILTER_TYPES = ["Все значения", "Равно", "Больше", "Меньше", "Между"]


class ColumnFilterDialog(QDialog):
    def __init__(self, column_title: str, current=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Фильтр: {column_title}")
        self.setModal(True)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Тип фильтра:"))
        self.type = QComboBox(); self.type.addItems(FILTER_TYPES)
        layout.addWidget(self.type)

        row1 = QHBoxLayout(); row1.addWidget(QLabel("Значение:"))
        self.v1 = QLineEdit(); row1.addWidget(self.v1); layout.addLayout(row1)
        self.row2 = QHBoxLayout(); self.row2.addWidget(QLabel("До:"))
        self.v2 = QLineEdit(); self.row2.addWidget(self.v2); layout.addLayout(self.row2)
        self.v2.setEnabled(False)

        self.type.currentIndexChanged.connect(lambda i: self.v2.setEnabled(i == 4))
        if current:
            self.type.setCurrentText(current[0]); self.v1.setText(str(current[1]))
            if current[2] is not None:
                self.v2.setText(str(current[2]))

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        layout.addWidget(box)

    def result_filter(self):
        """(тип, значение1, значение2|None) или None если «Все значения»/пусто."""
        t = self.type.currentText()
        if t == "Все значения" or not self.v1.text().strip():
            return None
        try:
            v1 = float(self.v1.text())
            v2 = float(self.v2.text()) if (t == "Между" and self.v2.text().strip()) else None
        except ValueError:
            return None
        return (t, v1, v2)


class SubjectFilterDialog(QDialog):
    def __init__(self, current_text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Фильтр по предметам")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Фильтр по коду/имени предмета:"))
        self.edit = QLineEdit(current_text)
        self.edit.setPlaceholderText("Введите часть кода предмета…")
        layout.addWidget(self.edit)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        layout.addWidget(box)

    def text(self) -> str:
        return self.edit.text().strip()
