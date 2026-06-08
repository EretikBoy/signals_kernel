"""
Собирает лёгкий онлайн-бандл: install.exe + app/ + requirements-qt{5,6}.txt +
tekvisa/ + hantek_driver/. Сам install.exe качает Python и зависимости на
машине пользователя (см. dist_tools/installer/steps.py) — отсюда и лёгкость.

    python -m dist_tools.online_bundle.build_bundle --out build/online --installer dist/install.exe
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .. import bundle_common

REQUIREMENTS_FILES = ["requirements-qt5.txt", "requirements-qt6.txt"]


def copy_requirements(out_dir: Path) -> None:
    print("\n=== requirements-*.txt ===")
    src_dir = bundle_common.REPO_ROOT / "dist_tools" / "installer"
    for name in REQUIREMENTS_FILES:
        shutil.copy2(src_dir / name, out_dir / name)
    print(f"  скопировано: {', '.join(REQUIREMENTS_FILES)}")


def build(out_dir: Path, installer_exe: Path | None) -> Path:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle_common.copy_app(out_dir)
    copy_requirements(out_dir)
    bundle_common.copy_vendor_folders(out_dir)
    bundle_common.copy_installer_exe(out_dir, installer_exe)
    return bundle_common.make_archive(out_dir, "signals-online")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True,
                        help="рабочая папка сборки — туда лягут app/, requirements-*.txt, "
                             "tekvisa/, hantek_driver/")
    parser.add_argument("--installer", type=Path, default=None,
                        help="путь к собранному install.exe — кладётся в корень бандла")
    args = parser.parse_args(argv)
    build(args.out, args.installer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
