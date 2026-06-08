"""
Шаги онлайн-установки: найти подходящий Python и сделать на его основе venv
(а если на машине ничего подходящего нет — поставить приватную копию с
python.org), поставить зависимости под Qt-биндинг, разложить app/ и
запустить TekVISA.

Шаг — функция (ctx, report), report(fraction, text) двигает прогресс-бар
в [0..1]. Выполняются в фоновом потоке (см. ui.py) — Tk трогать нельзя,
только через очередь.
"""
from __future__ import annotations

import shutil
import subprocess
import urllib.request
import winreg
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
    existing_python: Path | None = field(default=None, init=False)
    venv_created: bool = field(default=False, init=False)

    @property
    def python_dir(self) -> Path:
        return self.install_dir / "pyruntime"

    @property
    def python_exe(self) -> Path:
        # venv кладёт интерпретатор в Scripts/, приватная копия — прямо в корень
        if self.venv_created:
            return self.python_dir / "Scripts" / "python.exe"
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


def _registered_python(profile: detect.TargetProfile) -> Path | None:
    """PEP 514: оф. инсталлятор python.org регистрирует себя в
    SOFTWARE\\Python\\PythonCore\\<major.minor>[-32]\\InstallPath (HKCU — для
    текущего пользователя, HKLM — для всех). Если нужная версия уже стоит,
    используем её — повторный запуск инсталлятора с той же версией не сработает:
    Burn-бутстрэппер определяет «уже установлено» и игнорирует TargetDir,
    тихо завершаясь успехом без копирования файлов в приватную папку."""
    major_minor = ".".join(profile.python_version.split(".")[:2])
    tag = major_minor + ("-32" if profile.python_arch == "win32" else "")
    wow_flag = winreg.KEY_WOW64_32KEY if profile.python_arch == "win32" else winreg.KEY_WOW64_64KEY
    for hive, flags in ((winreg.HKEY_CURRENT_USER, 0), (winreg.HKEY_LOCAL_MACHINE, wow_flag)):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Python\PythonCore\{tag}\InstallPath",
                                0, winreg.KEY_READ | flags) as key:
                install_path, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        exe = Path(install_path) / "python.exe"
        if exe.exists():
            return exe
    return None


def _run_silent(args: list[str], *, step_label: str, report: ProgressFn) -> None:
    report(0.0, step_label)
    proc = subprocess.run(args, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"{step_label}: код возврата {proc.returncode}\n"
                           f"{proc.stdout}\n{proc.stderr}")


# ---- шаги конвейера -----------------------------------------------------------

def step_find_python(ctx: InstallContext, report: ProgressFn) -> None:
    report(0.0, "Поиск установленного Python…")
    found = _registered_python(ctx.profile)
    if found is not None:
        ctx.existing_python = found
        report(1.0, f"Найден подходящий Python: {found} — сделаем venv на его основе")
    else:
        report(1.0, "Подходящий Python не найден — будет установлена приватная копия")


def step_download_python(ctx: InstallContext, report: ProgressFn) -> None:
    if ctx.existing_python is not None:
        report(1.0, "пропуск — venv будет создано на основе найденного Python")
        return
    url = detect.python_installer_url(ctx.profile)
    dest = ctx.install_dir / f"python-{ctx.profile.python_version}-{ctx.profile.python_arch}.exe"
    report(0.0, f"Скачивание Python {ctx.profile.python_version} ({ctx.profile.python_arch})…")
    _download(url, dest, report, label="Python")
    ctx.python_installer = dest


def step_install_python(ctx: InstallContext, report: ProgressFn) -> None:
    """Тихая установка в приватную папку — не «для всех», без PATH, изолированно от системного
    Python. Только запасной путь на случай, если на машине вообще нет подходящего Python
    (если есть — см. step_create_venv: повторный запуск инсталлятора с той же версией не
    срабатывает, Burn-бутстрэппер определяет «уже установлено» и игнорирует TargetDir)."""
    if ctx.existing_python is not None:
        report(1.0, "пропуск — venv будет создано на основе найденного Python")
        return
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


def step_create_venv(ctx: InstallContext, report: ProgressFn) -> None:
    """Изолируем зависимости приложения от системного Python через venv —
    создаётся один раз на месте и никуда не переносится, так что абсолютные
    пути в его скриптах не проблема."""
    if ctx.existing_python is None:
        report(1.0, "пропуск — используется приватная копия Python")
        return
    report(0.0, f"Создание окружения на основе {ctx.existing_python}…")
    _run_silent([str(ctx.existing_python), "-m", "venv", str(ctx.python_dir)],
                step_label="Создание окружения", report=report)
    ctx.venv_created = True
    if not ctx.python_exe.exists():
        raise RuntimeError("venv создано, но python.exe не появился — "
                           f"ожидался путь {ctx.python_exe}")
    report(1.0, "Окружение создано")


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
    ("Поиск Python", step_find_python),
    ("Скачивание Python", step_download_python),
    ("Установка Python", step_install_python),
    ("Создание окружения", step_create_venv),
    ("Обновление pip", step_upgrade_pip),
    ("Установка библиотек", step_install_requirements),
    ("Копирование приложения", step_copy_app),
    ("Драйвер Hantek", step_install_driver),
    ("Установщик TekVISA", step_run_tekvisa),
]
