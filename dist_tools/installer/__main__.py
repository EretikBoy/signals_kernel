"""
Точка входа онлайн-установщика. Рядом с installer.exe (или с этим
пакетом — при запуске из исходников) ожидается «полезная нагрузка»:

    app/                     — файлы приложения (main.py, signals/, …)
    requirements-qt5.txt     — зависимости для Windows 7 (PyQt5)
    requirements-qt6.txt     — зависимости для Windows 8.1/10/11 (PyQt6)
    tekvisa/*.exe            — дистрибутив TekVISA (необязательно)

Запуск из исходников:  python -m dist_tools.installer
"""
from __future__ import annotations

import sys
from pathlib import Path


def _payload_dir() -> Path:
    """Папка с полезной нагрузкой — рядом с замороженным .exe или с пакетом."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def main() -> int:
    from .ui import InstallerWindow
    window = InstallerWindow(payload_dir=_payload_dir())
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
