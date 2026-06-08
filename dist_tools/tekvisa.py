"""
Запуск установщика TekVISA — общий шаг для online/offline (vendor/tekvisa/).
Тихого режима у него нет — запускаем видимо и не ждём завершения, это
последний шаг конвейера; пользователь проходит мастер сам.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

ProgressFn = Callable[[float, str], None]


def launch_installer(payload_dir: Path, report: ProgressFn, *, folder_name: str = "tekvisa") -> None:
    candidates = sorted((payload_dir / folder_name).glob("*.exe"))
    if not candidates:
        report(1.0, f"Дистрибутив TekVISA не найден в {folder_name}/ — пропускаю этот шаг")
        return
    report(0.0, "Запуск установщика TekVISA…")
    subprocess.Popen([str(candidates[0])], cwd=str(candidates[0].parent))
    report(1.0, "Установщик TekVISA запущен — завершите его в открывшемся окне")
