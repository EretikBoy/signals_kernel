"""
signals.plugins.discovery
==========================

Подключить плагин можно тремя путями, и ядро не делает между ними разницы:

* встроенный — модуль лежит в пакете `signals.contrib` (или другом указанном
  пакете), импортируется при старте, и тогда срабатывают его декораторы
  `@REGISTRY.register(...)`;
* drop-in — обычный `.py`-файл в пользовательской папке плагинов
  (например, `~/.signals/plugins`); при запуске приложение само сканирует её
  и импортирует всё, что найдёт, — пересобирать ничего не нужно;
* pip-пакет — сторонний пакет с entry point группы `signals.plugins`; после
  `pip install` фича подхватывается сама на следующем запуске.

Во всех трёх случаях эта функция лишь импортирует модуль — дальше всё делают
декораторы реестров: регистрация происходит прямо при импорте, поэтому ядро
понятия не имеет, какие плагины вообще существуют.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from importlib import metadata
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "signals.plugins"


def _import_package_modules(package_name: str) -> list[str]:
    loaded: list[str] = []
    try:
        pkg = importlib.import_module(package_name)
    except ModuleNotFoundError:
        logger.debug("Пакет плагинов %s не найден — пропускаю", package_name)
        return loaded
    for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        try:
            importlib.import_module(info.name)
            loaded.append(info.name)
        except Exception:
            logger.exception("Ошибка импорта встроенного плагина %s", info.name)
    return loaded


def _import_folder(folder: Path) -> list[str]:
    loaded: list[str] = []
    if not folder.is_dir():
        return loaded
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"signals_dropin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec and spec.loader:
                module: ModuleType = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                loaded.append(str(path))
        except Exception:
            logger.exception("Ошибка загрузки drop-in плагина %s", path)
    return loaded


def _load_entry_points() -> list[str]:
    loaded: list[str] = []
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        logger.exception("Не удалось прочитать entry points")
        return loaded
    for ep in eps:
        try:
            ep.load()  # импорт модуля плагина → срабатывают его регистрации
            loaded.append(f"{ep.name} ({ep.value})")
        except Exception:
            logger.exception("Ошибка загрузки entry-point плагина %s", ep.name)
    return loaded


def discover(
    builtin_packages: tuple[str, ...] = ("signals.contrib",),
    folders: tuple[Path, ...] = (),
    use_entry_points: bool = True,
) -> dict[str, list[str]]:
    """Загрузить все плагины. Возвращает отчёт «что откуда подключилось»."""
    report = {"builtin": [], "dropin": [], "entrypoint": []}
    for pkg in builtin_packages:
        report["builtin"] += _import_package_modules(pkg)
    for folder in folders:
        report["dropin"] += _import_folder(Path(folder))
    if use_entry_points:
        report["entrypoint"] += _load_entry_points()
    logger.info(
        "Плагины загружены: builtin=%d, dropin=%d, entrypoint=%d",
        len(report["builtin"]), len(report["dropin"]), len(report["entrypoint"]),
    )
    return report
