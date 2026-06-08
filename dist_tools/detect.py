"""
Определяет целевую машину: версия/разрядность Windows, нужный Python и
биндинг Qt. Только stdlib — выполняется внутри install.exe до появления
рабочего окружения. Win7 ограничен Python 3.8.x + PyQt5 (Qt6 требует Win10).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

#: Последний патч Python 3.8 с официальным установщиком под Windows —
#: потолок для Windows 7 (3.9+ требует Windows 8.1 API-Set, см. PEP 11).
LEGACY_PYTHON = "3.8.10"

#: Актуальная версия для Windows 8.1/10/11.
MODERN_PYTHON = "3.12.7"


@dataclass(frozen=True)
class TargetProfile:
    """Что и как ставить на эту машину."""

    os_label: str        # для прогресс-окна, напр. "Windows 7 (64-бит)"
    is_legacy: bool      # True — Windows 7 и старше (нет Qt6, потолок Python 3.8)
    os_is_64bit: bool    # разрядность САМОЙ ОС (не текущего процесса!)
    python_version: str  # напр. "3.8.10" или "3.12.7"
    python_arch: str     # "amd64" или "win32" — суффикс установщика на python.org
    qt_binding: str      # "PyQt5" или "PyQt6" — какой пакет ставить пипом


def _windows_version() -> tuple[int, int, int]:
    """(major, minor, build); вне Windows возвращаем условную «Windows 10»."""
    getter = getattr(sys, "getwindowsversion", None)
    if getter is not None:
        v = getter()
        return (v.major, v.minor, v.build)
    return (10, 0, 19041)


def _os_is_64bit() -> bool:
    """Разрядность ОС, не процесса — sys.maxsize лжёт под WOW64. WOW64 выставляет
    PROCESSOR_ARCHITEW6432/ProgramW6432, на чистой 32-битной системе их нет."""
    env = {k.upper(): v for k, v in os.environ.items()}
    if env.get("PROCESSOR_ARCHITECTURE", "").upper() == "AMD64":
        return True
    if env.get("PROCESSOR_ARCHITEW6432", "").upper() == "AMD64":
        return True
    return bool(env.get("PROGRAMW6432") or env.get("PROGRAMFILES(X86)"))


def _os_label(major: int, minor: int, build: int, os_64: bool) -> str:
    bits = "64" if os_64 else "32"
    if (major, minor) == (6, 1):
        name = "Windows 7"
    elif (major, minor) == (6, 2):
        name = "Windows 8"
    elif (major, minor) == (6, 3):
        name = "Windows 8.1"
    elif major == 10 and build >= 22000:
        name = "Windows 11"
    elif major == 10:
        name = "Windows 10"
    else:
        name = f"Windows {major}.{minor}"
    return f"{name} ({bits}-бит)"


def detect_target() -> TargetProfile:
    """Снимок «что ставить на эту машину» — вызывается один раз при старте."""
    major, minor, build = _windows_version()
    os_64 = _os_is_64bit()
    is_legacy = (major, minor) < (6, 2)          # старше Windows 8 ⇒ нет Qt6

    if is_legacy:
        return TargetProfile(
            os_label=_os_label(major, minor, build, os_64),
            is_legacy=True,
            os_is_64bit=os_64,
            python_version=LEGACY_PYTHON,
            python_arch="amd64" if os_64 else "win32",
            qt_binding="PyQt5",
        )
    return TargetProfile(
        os_label=_os_label(major, minor, build, os_64),
        is_legacy=False,
        os_is_64bit=os_64,
        python_version=MODERN_PYTHON,
        python_arch="amd64" if os_64 else "win32",
        qt_binding="PyQt6",
    )


def python_installer_url(profile: TargetProfile) -> str:
    """Прямая ссылка на оф. установщик python.org, подобранную под машину."""
    v = profile.python_version
    return f"https://www.python.org/ftp/python/{v}/python-{v}-{profile.python_arch}.exe"


def requirements_filename(profile: TargetProfile) -> str:
    """Какой requirements-файл из пакета установщика подойдёт этой машине."""
    return "requirements-qt5.txt" if profile.qt_binding == "PyQt5" else "requirements-qt6.txt"
