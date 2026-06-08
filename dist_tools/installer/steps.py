"""
Шаги онлайн-установки: скачать Python, поставить приватную копию (без venv —
его скрипты хранят абсолютные пути и ломаются при переносе), поставить
зависимости под Qt-биндинг, разложить app/ и запустить TekVISA.

Шаг — функция (ctx, report), report(fraction, text) двигает прогресс-бар
в [0..1]. Выполняются в фоновом потоке (см. ui.py) — Tk трогать нельзя,
только через очередь.
"""
from __future__ import annotations

import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import detect, drivers, tekvisa

ProgressFn = Callable[[float, str], None]
Step = Callable[["InstallContext", ProgressFn], None]

#: На Windows подавляет всплывающие консольные окна дочерних процессов;
#: на других платформах (тесты/отладка) такого флага нет.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class InstallContext:
    profile: detect.TargetProfile
    install_dir: Path     # куда раскладываем рабочее окружение и приложение
    payload_dir: Path     # папка рядом с installer.exe: app/, requirements-*.txt, tekvisa/
    python_installer: Path | None = field(default=None, init=False)

    @property
    def python_dir(self) -> Path:
        return self.install_dir / "pyruntime"

    @property
    def python_exe(self) -> Path:
        return self.python_dir / "python.exe"

    @property
    def app_dir(self) -> Path:
        return self.install_dir / "app"


# ---- низкоуровневые помощники ------------------------------------------------

def _download(url: str, dest: Path, report: ProgressFn, *, label: str) -> None:
    """Скачать файл с прогрессом; report получает долю [0..1] текущего шага."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as resp:        # noqa: S310 — фиксированный https URL из detect.py, не пользовательский ввод
        total = int(resp.headers.get("Content-Length", 0)) or None
        read = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                read += len(chunk)
                if total:
                    report(read / total, f"{label}: {read // 1024} / {total // 1024} КиБ")
                else:
                    report(0.0, f"{label}: {read // 1024} КиБ")


def _run_silent(args: list[str], *, step_label: str, report: ProgressFn) -> None:
    report(0.0, step_label)
    proc = subprocess.run(args, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"{step_label}: код возврата {proc.returncode}\n"
                           f"{proc.stdout}\n{proc.stderr}")


# ---- шаги конвейера -----------------------------------------------------------

def step_download_python(ctx: InstallContext, report: ProgressFn) -> None:
    url = detect.python_installer_url(ctx.profile)
    dest = ctx.install_dir / f"python-{ctx.profile.python_version}-{ctx.profile.python_arch}.exe"
    report(0.0, f"Скачивание Python {ctx.profile.python_version} ({ctx.profile.python_arch})…")
    _download(url, dest, report, label="Python")
    ctx.python_installer = dest


def step_install_python(ctx: InstallContext, report: ProgressFn) -> None:
    """Тихая установка в приватную папку — не «для всех», без PATH, изолированно от системного Python."""
    assert ctx.python_installer is not None
    _run_silent([
        str(ctx.python_installer), "/quiet",
        "InstallAllUsers=0", "PrependPath=0", "Include_launcher=0", "Include_test=0",
        f"TargetDir={ctx.python_dir}",
    ], step_label="Установка Python", report=report)
    if not ctx.python_exe.exists():
        raise RuntimeError("Установщик Python отработал, но python.exe не появился — "
                           f"ожидался путь {ctx.python_exe}")
    report(1.0, "Python установлен")


def step_upgrade_pip(ctx: InstallContext, report: ProgressFn) -> None:
    _run_silent([str(ctx.python_exe), "-m", "pip", "install", "--upgrade", "pip"],
                step_label="Обновление pip", report=report)
    report(1.0, "pip обновлён")


def step_install_requirements(ctx: InstallContext, report: ProgressFn) -> None:
    req = ctx.payload_dir / detect.requirements_filename(ctx.profile)
    if not req.exists():
        raise RuntimeError(f"Не найден файл зависимостей рядом с установщиком: {req}")
    report(0.0, f"Установка библиотек ({ctx.profile.qt_binding}) — это займёт несколько минут…")
    _run_silent([str(ctx.python_exe), "-m", "pip", "install", "-r", str(req)],
                step_label="Установка библиотек", report=report)
    report(1.0, "Библиотеки установлены")


def step_copy_app(ctx: InstallContext, report: ProgressFn) -> None:
    src = ctx.payload_dir / "app"
    if not src.exists():
        raise RuntimeError(f"Не найдена папка приложения рядом с установщиком: {src}")
    report(0.0, "Копирование файлов приложения…")
    if ctx.app_dir.exists():
        shutil.rmtree(ctx.app_dir)
    shutil.copytree(src, ctx.app_dir)
    report(1.0, "Файлы приложения на месте")


def step_install_driver(ctx: InstallContext, report: ProgressFn) -> None:
    drivers.install_pnp_driver(ctx.payload_dir, report)


def step_run_tekvisa(ctx: InstallContext, report: ProgressFn) -> None:
    tekvisa.launch_installer(ctx.payload_dir, report)


PIPELINE: list[tuple[str, Step]] = [
    ("Скачивание Python", step_download_python),
    ("Установка Python", step_install_python),
    ("Обновление pip", step_upgrade_pip),
    ("Установка библиотек", step_install_requirements),
    ("Копирование приложения", step_copy_app),
    ("Драйвер Hantek", step_install_driver),
    ("Установщик TekVISA", step_run_tekvisa),
]
