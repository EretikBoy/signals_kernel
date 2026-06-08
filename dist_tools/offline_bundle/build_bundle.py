"""
Собирает один тяжёлый оффлайн-бандл: pyruntime-amd64/ + pyruntime-win32/
(оба готовых окружения сразу), app/, tekvisa/, hantek_driver/, install.exe.
install.exe сам выбирает нужный pyruntime по разрядности ОС — см.
offline_steps.step_pick_runtime.

Запускать под Windows с интернетом (CI) — качает .exe/embed-архивы с
python.org и выполняет их. 32-битный python.exe собирается и тут же,
на 64-битном раннере, через WOW64 — отдельная машина под win32 не нужна.

    python -m dist_tools.offline_bundle.build_bundle --out build/offline [--installer dist/install.exe]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from .. import bundle_common

PYTHON_VERSION_AMD64 = "3.12.7"
PYTHON_VERSION_WIN32 = "3.8.10"   # потолок для возможной установки на Windows 7 32-бит

#: Порядок сборки окружений внутри одного бандла.
ARCHES = ("amd64", "win32")

GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

#: Базовый набор — общий для обеих архитектур и обоих Qt-биндингов.
BASE_PACKAGES = [
    "numpy>=1.24",
    "pandas>=2.0",
    "matplotlib>=3.7",
    "openpyxl>=3.1",
    "pyvisa>=1.13",
    "tm_devices>=2.0",
]
QT5_PACKAGES = ["PyQt5==5.15.10"]
QT6_PACKAGES = ["PyQt6>=6.5"]


def _python_version_for(arch: str) -> str:
    return PYTHON_VERSION_AMD64 if arch == "amd64" else PYTHON_VERSION_WIN32


def _pth_filename(version: str) -> str:
    """3.12.7 -> python312._pth (в имени файла версия без точек)."""
    major, minor, *_ = version.split(".")
    return f"python{major}{minor}._pth"


def _download(url: str, dest: Path) -> None:
    print(f"    ⇣ {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)        # noqa: S310 — фиксированные https-URL python.org/bootstrap.pypa.io


def _run(args: list[str]) -> None:
    print(f"    $ {' '.join(args)}")
    subprocess.run(args, check=True)


# ---- сборка одного окружения ---------------------------------------------------

def _fetch_embeddable_python(arch: str, pyruntime: Path) -> None:
    version = _python_version_for(arch)
    print(f"  [1/3] Embeddable Python {version} ({arch})")
    zip_path = pyruntime.parent / f"_python-{version}-embed-{arch}.zip"
    _download(f"https://www.python.org/ftp/python/{version}/python-{version}-embed-{arch}.zip", zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(pyruntime)
    zip_path.unlink()


def _enable_pip(pyruntime: Path, arch: str) -> Path:
    """Embeddable-сборка по умолчанию без pip и site-packages — раскомментировать
    `import site` в ._pth и прогнать get-pip.py (стандартный обход python.org)."""
    print("  [2/3] Включение site-packages и pip")
    version = _python_version_for(arch)
    pth = pyruntime / _pth_filename(version)
    text = pth.read_text(encoding="utf-8")
    pth.write_text(text.replace("#import site", "import site"), encoding="utf-8")

    get_pip = pyruntime / "get-pip.py"
    _download(GET_PIP_URL, get_pip)
    python_exe = pyruntime / "python.exe"
    _run([str(python_exe), str(get_pip), "--no-warn-script-location"])
    get_pip.unlink()

    # современный get-pip.py больше не тащит setuptools/wheel — а часть пакетов
    # (libusb-package и т.п.) собирается из sdist и требует setuptools.build_meta
    _run([str(python_exe), "-m", "pip", "install", "--no-warn-script-location", "setuptools", "wheel"])
    return python_exe


def _install_packages(python_exe: Path, arch: str) -> None:
    packages = list(BASE_PACKAGES) + list(QT5_PACKAGES)
    if arch == "amd64":
        packages += QT6_PACKAGES   # PyQt6 не публикует колёса под win32
    qt_label = "PyQt5+PyQt6" if arch == "amd64" else "только PyQt5 (нет колёс PyQt6 под win32)"
    print(f"  [3/3] Установка библиотек ({len(packages)} пакетов, {qt_label})")
    _run([str(python_exe), "-m", "pip", "install", "--no-warn-script-location", *packages])


def build_runtime(arch: str, out_dir: Path) -> None:
    """Собрать готовое окружение pyruntime-{arch}/ внутри бандла."""
    pyruntime = out_dir / f"pyruntime-{arch}"
    if pyruntime.exists():
        shutil.rmtree(pyruntime)
    pyruntime.mkdir(parents=True)

    print(f"\n=== Окружение «{arch}» ({_python_version_for(arch)}) ===")
    _fetch_embeddable_python(arch, pyruntime)
    python_exe = _enable_pip(pyruntime, arch)
    _install_packages(python_exe, arch)


def build(out_dir: Path, installer_exe: Path | None) -> Path:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for arch in ARCHES:
        build_runtime(arch, out_dir)
    bundle_common.copy_app(out_dir)
    bundle_common.copy_vendor_folders(out_dir)
    bundle_common.copy_installer_exe(out_dir, installer_exe)
    return bundle_common.make_archive(out_dir, "signals-offline")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True,
                        help="рабочая папка сборки — туда лягут pyruntime-amd64/, "
                             "pyruntime-win32/, app/, tekvisa/, hantek_driver/")
    parser.add_argument("--installer", type=Path, default=None,
                        help="путь к собранному install.exe — кладётся в корень бандла")
    args = parser.parse_args(argv)
    bundle_common.force_utf8_console()

    if sys.platform != "win32":
        print("Сборка оффлайн-бандла рассчитана на запуск под Windows "
              "(используются .exe-установщики и embeddable-дистрибутивы python.org).",
              file=sys.stderr)
        return 1

    build(args.out, args.installer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
