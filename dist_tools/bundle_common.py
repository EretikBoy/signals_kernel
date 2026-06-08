"""Общие куски сборки online- и offline-бандлов: app/, vendor-папки, install.exe, zip."""
from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

APP_INCLUDE = ["main.py", "signals"]
APP_EXCLUDE_DIR_NAMES = {"__pycache__", ".git"}

#: vendor/<имя> -> <имя в бандле>; см. vendor/*/README.md про их происхождение.
VENDOR_FOLDERS = {
    "tekvisa": "tekvisa",
    "hantek_driver": "hantek_driver",
}


def copy_app(out_dir: Path) -> None:
    print("\n=== Файлы приложения ===")
    app_dir = out_dir / "app"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    for name in APP_INCLUDE:
        src = REPO_ROOT / name
        dst = app_dir / name
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*APP_EXCLUDE_DIR_NAMES))
        else:
            shutil.copy2(src, dst)
    print(f"  скопировано: {', '.join(APP_INCLUDE)}")


def copy_vendor_folders(out_dir: Path) -> None:
    """Переносит vendor/{tekvisa,hantek_driver} в бандл; если папки нет — предупреждает и продолжает."""
    print("\n=== Сторонние пакеты (TekVISA / драйвер Hantek) ===")
    for vendor_name, dest_name in VENDOR_FOLDERS.items():
        src = REPO_ROOT / "vendor" / vendor_name
        dst = out_dir / dest_name
        if not src.exists() or not any(src.iterdir()):
            print(f"  ⚠ vendor/{vendor_name}/ пуст или не найден — бандл соберётся БЕЗ него "
                  f"(см. vendor/{vendor_name}/README.md)")
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"  vendor/{vendor_name}/ → {dest_name}/")


def copy_installer_exe(out_dir: Path, installer_exe: Path | None) -> None:
    print("\n=== install.exe ===")
    if installer_exe is None or not installer_exe.exists():
        print(f"  ⚠ {installer_exe} не найден — бандл соберётся без install.exe "
              f"(добавьте --installer <путь> с собранным install.exe)")
        return
    shutil.copy2(installer_exe, out_dir / "install.exe")
    print(f"  {installer_exe} → install.exe")


def make_archive(out_dir: Path, archive_name: str) -> Path:
    archive_base = out_dir.parent / archive_name
    archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=out_dir)
    print(f"\nГотово: {archive_path}")
    return Path(archive_path)
