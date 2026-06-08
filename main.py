"""
Точка входа приложения. Запуск:  python main.py

Поднимает автообнаружение плагинов (встроенные + пользовательская папка
~/.signals/plugins), инициализирует парсеры/сервисы и показывает главное окно.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from signals import qtcompat             # noqa: F401 — подмена PyQt6→PyQt5 на старых системах, должна идти первой
from PyQt6.QtWidgets import QApplication

from signals.plugins import discover
import signals.io          # noqa: F401 — регистрирует парсеры
import signals.services    # noqa: F401
from signals.app_qt import theme
from signals.app_qt.log_widget import QtLogHandler
from signals.app_qt.main_window import MainWindow


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    user_plugins = Path.home() / ".signals" / "plugins"
    discover(builtin_packages=("signals.contrib",), folders=(user_plugins,))

    app = QApplication(sys.argv)
    settings = theme.load_settings()
    theme.apply_style(app, settings.get("style"))      # Fusion по умолчанию (не Win11)
    theme.apply_theme(app, settings.get("theme", "Тёмная"))
    window = MainWindow()

    handler = QtLogHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s",
                                           datefmt="%H:%M:%S"))
    handler.bridge.message.connect(window.logw.append_line)
    logging.getLogger("signals").addHandler(handler)

    window.show()

    from signals.app_qt.onboarding import WelcomeDialog, should_show_onboarding
    if should_show_onboarding():
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(400, lambda: WelcomeDialog(window).run())

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
