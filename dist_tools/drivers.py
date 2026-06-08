"""
Установка PnP-драйвера Hantek через pnputil — общий шаг для online/offline
(vendor/hantek_driver/). Требует админ-прав — поднимаем через UAC
(ShellExecute "runas"), не ждём и не считаем отказ от UAC фатальным:
донастроить можно и позже, как и TekVISA.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

ProgressFn = Callable[[float, str], None]

_SW_SHOWNORMAL = 1


def install_pnp_driver(payload_dir: Path, report: ProgressFn, *,
                        folder_name: str = "hantek_driver", inf_glob: str = "*.inf") -> None:
    folder = payload_dir / folder_name
    candidates = sorted(folder.glob(inf_glob))
    if not candidates:
        report(1.0, f"Драйвер в {folder_name}/ не найден рядом с установщиком — пропускаю")
        return
    inf_path = candidates[0]

    if sys.platform != "win32":
        report(1.0, f"Установка драйверов поддерживается только на Windows — пропускаю ({inf_path.name})")
        return

    report(0.0, "Установка USB-драйвера Hantek (потребуется подтверждение в окне UAC)…")
    import ctypes                                            # импорт здесь — модуль есть только на Windows
    args = f'/add-driver "{inf_path}" /install'
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "pnputil.exe", args, None, _SW_SHOWNORMAL)
    if result <= 32:
        report(1.0, f"Не удалось запустить установку драйвера (код {result}) — поставьте "
                    f"вручную через Диспетчер устройств → «Обновить драйвер», указав на {folder_name}/ "
                    f"(см. {folder_name}/README.md)")
        return
    report(1.0, "Установка драйвера запущена — подтвердите запрос UAC, если он появился")
