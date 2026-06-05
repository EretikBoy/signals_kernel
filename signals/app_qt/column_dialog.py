"""
signals.app_qt.column_dialog
============================

Диалог «Настройка столбцов» как в оригинале: два списка «Доступные параметры» и
«Текущие столбцы», кнопки Добавить →, ← Удалить, Вверх, Вниз и «По умолчанию».
Столбцы — стандартные из процессора (services.columns) + пользовательские формулы.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QVBoxLayout,
)

from ..services import DEFAULT_COLUMN_KEYS, available_columns


class ColumnConfigDialog(QDialog):
    def __init__(self, current_columns: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройка столбцов")
        self.setModal(True)
        self.resize(420, 520)
        self.available = available_columns()
        self.current = [dict(c) for c in current_columns]
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Выберите отображаемые столбцы:"))
        layout.addWidget(QLabel("Доступные параметры:"))
        self.available_list = QListWidget(); layout.addWidget(self.available_list)
        layout.addWidget(QLabel("Текущие столбцы:"))
        self.selected_list = QListWidget(); layout.addWidget(self.selected_list)

        btns = QHBoxLayout()
        for text, slot in (("Добавить →", self._add), ("← Удалить", self._remove),
                           ("Вверх", self._up), ("Вниз", self._down)):
            b = QPushButton(text); b.clicked.connect(slot); btns.addWidget(b)
        layout.addLayout(btns)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel
                               | QDialogButtonBox.StandardButton.RestoreDefaults)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)
        layout.addWidget(box)

    def _load(self) -> None:
        self.available_list.clear(); self.selected_list.clear()
        current_keys = [c["key"] for c in self.current]
        for col in self.available:
            if col["key"] not in current_keys:
                it = self.available_list.addItem(f"{col['title']} ({col['key']})")
                self.available_list.item(self.available_list.count() - 1).setData(
                    Qt.ItemDataRole.UserRole, col)
        for col in self.current:
            self.selected_list.addItem(f"{col['title']} ({col['key']})")
            self.selected_list.item(self.selected_list.count() - 1).setData(
                Qt.ItemDataRole.UserRole, col)

    def _add(self) -> None:
        for it in self.available_list.selectedItems():
            self.current.append(it.data(Qt.ItemDataRole.UserRole))
        self._load()

    def _remove(self) -> None:
        for it in self.selected_list.selectedItems():
            key = it.data(Qt.ItemDataRole.UserRole)["key"]
            self.current = [c for c in self.current if c["key"] != key]
        self._load()

    def _up(self) -> None:
        r = self.selected_list.currentRow()
        if r > 0:
            self.current.insert(r - 1, self.current.pop(r))
            self._load(); self.selected_list.setCurrentRow(r - 1)

    def _down(self) -> None:
        r = self.selected_list.currentRow()
        if 0 <= r < len(self.current) - 1:
            self.current.insert(r + 1, self.current.pop(r))
            self._load(); self.selected_list.setCurrentRow(r + 1)

    def _defaults(self) -> None:
        by_key = {c["key"]: c for c in self.available}
        self.current = [by_key[k] for k in DEFAULT_COLUMN_KEYS if k in by_key]
        self._load()

    def get_columns(self) -> list[dict]:
        return self.current
