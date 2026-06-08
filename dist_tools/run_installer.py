"""
Отдельная точка входа для заморозки PyInstaller-ом в installer.exe.

Не часть пакета dist_tools.installer (там __main__.py использует
относительные импорты `from .. import detect` — PyInstaller хуже
анализирует пакетные __main__.py при запуске «по пути к файлу»).
Здесь — обычный скрипт с абсолютным импортом, который резолвится
без сюрпризов что при запуске из исходников, что при заморозке:

    pyinstaller --onefile --windowed --name installer dist_tools/run_installer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dist_tools.installer.__main__ import main          # noqa: E402 — после правки sys.path

if __name__ == "__main__":
    raise SystemExit(main())
