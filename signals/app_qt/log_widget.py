"""Виджет лога + logging-обработчик, потокобезопасно пишущий в него."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QPlainTextEdit


class _Bridge(QObject):
    message = pyqtSignal(str)


class QtLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.bridge = _Bridge()

    def emit(self, record: logging.LogRecord) -> None:
        self.bridge.message.emit(self.format(record))


class LogWidget(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)

    def append_line(self, text: str) -> None:
        self.appendPlainText(text)
