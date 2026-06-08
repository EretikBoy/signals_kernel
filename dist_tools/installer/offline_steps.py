"""
Шаги оффлайн-установки. В отличие от steps.py тут ничего не качается —
бандл уже несёт готовые pyruntime-amd64/ и pyruntime-win32/ (см.
build_bundle.py); остаётся выбрать нужный, написать батник запуска и
прогнать общие шаги драйвера/TekVISA.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import detect, drivers, tekvisa

ProgressFn = Callable[[float, str], None]
Step = Callable[["OfflineContext", ProgressFn], None]


@dataclass
class OfflineContext:
    profile: detect.TargetProfile
    payload_dir: Path                          # папка распакованного бандла, рядом с install.exe
    runtime_dir: Path | None = field(default=None, init=False)


def step_pick_runtime(ctx: OfflineContext, report: ProgressFn) -> None:
    """Бандл несёт оба рантайма — берём тот, что под разрядность ЭТОЙ ОС."""
    arch = "amd64" if ctx.profile.os_is_64bit else "win32"
    candidate = ctx.payload_dir / f"pyruntime-{arch}"
    if not (candidate / "python.exe").exists():
        raise RuntimeError(f"В бандле нет окружения под эту архитектуру ({arch}): {candidate} "
                           f"— возможно, скачан не тот архив")
    ctx.runtime_dir = candidate
    report(1.0, f"Используется готовое окружение «{candidate.name}» — {ctx.profile.os_label}")


def step_write_launcher(ctx: OfflineContext, report: ProgressFn) -> None:
    """Батник рядом с распакованным бандлом — без ярлыков и реестра, переносимо."""
    assert ctx.runtime_dir is not None
    rel_python = ctx.runtime_dir.relative_to(ctx.payload_dir)
    launcher = ctx.payload_dir / "Запустить Signals.bat"
    launcher.write_text(
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        f'"{rel_python}\\python.exe" app\\main.py\r\n'
        "pause\r\n",
        encoding="cp866",
    )
    report(1.0, f"Готово: «{launcher.name}» — запускайте им приложение")


def step_install_driver(ctx: OfflineContext, report: ProgressFn) -> None:
    drivers.install_pnp_driver(ctx.payload_dir, report)


def step_run_tekvisa(ctx: OfflineContext, report: ProgressFn) -> None:
    tekvisa.launch_installer(ctx.payload_dir, report)


PIPELINE: list[tuple[str, Step]] = [
    ("Выбор окружения", step_pick_runtime),
    ("Создание ярлыка запуска", step_write_launcher),
    ("Драйвер Hantek", step_install_driver),
    ("Установщик TekVISA", step_run_tekvisa),
]
