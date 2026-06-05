"""
signals.app_qt.tree_widget
==========================

Дерево с перетаскиванием анализа в другой предмет. Drop не двигает элементы сам
(в строках есть виджеты-кнопки), а сообщает модели через сигнал — окно
переносит анализ и перестраивает дерево.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QTreeWidget

NAME_ROLE = Qt.ItemDataRole.UserRole


class SignalsTree(QTreeWidget):
    analysis_dropped = pyqtSignal(object, object)   # (data_tuple, target_subject)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def dropEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        src = self.currentItem()
        if src is not None and target is not None:
            s = src.data(0, NAME_ROLE); t = target.data(0, NAME_ROLE)
            if s and s[0] == "analysis" and t:
                target_subject = t[1]                 # и для subject, и для analysis это Subject
                self.analysis_dropped.emit(s, target_subject)
        event.ignore()                                # перестроим из модели сами
