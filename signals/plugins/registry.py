"""
signals.plugins.registry
=========================

Единый механизм точек расширения. Один и тот же класс `Registry` обслуживает
ВСЕ виды плагинов: приборы, вычисляемые колонки, функции выражений, парсеры,
экспортёры. Добавить фичу = зарегистрировать её в нужном реестре одной строкой
(декоратором при импорте) ИЛИ в рантайме (для пользовательских колонок/выражений).

Реестр не зависит от Qt. Он умеет уведомлять подписчиков об изменениях
(`on_change`), чтобы GUI мог перерисоваться, когда пользователь во время работы
добавил новую колонку или прибор появился из drop-in плагина.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class Entry:
    """Одна зарегистрированная единица расширения."""
    key: str                      # уникальный ключ внутри реестра, напр. "hantek"
    target: Any                   # класс / функция / объект, который зарегистрировали
    meta: dict[str, Any] = field(default_factory=dict)  # label, unit, caps, ...
    source: str = "builtin"       # builtin | dropin | entrypoint | runtime

    @property
    def label(self) -> str:
        return self.meta.get("label", self.key)


class Registry:
    """Именованный реестр одной точки расширения.

    Пример (регистрация декоратором при импорте модуля)::

        INSTRUMENTS = Registry("instruments")

        @INSTRUMENTS.register("hantek", label="Hantek", caps={"generator"})
        class HantekScope: ...

    Пример (регистрация в рантайме — пользовательская колонка из UI)::

        COLUMNS.add("my_ratio", my_func, label="Моё отношение", source="runtime")
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._entries: dict[str, Entry] = {}
        self._listeners: list[Callable[[Registry], None]] = []

    # ---- регистрация -------------------------------------------------------
    def register(self, key: str | None = None, **meta: Any) -> Callable[[Any], Any]:
        """Декоратор. `key` по умолчанию берётся из __name__ цели."""
        def deco(target: Any) -> Any:
            resolved = key or getattr(target, "__name__", None)
            if resolved is None:
                raise ValueError("Не удалось определить ключ для регистрации")
            self.add(resolved, target, source=meta.pop("source", "builtin"), **meta)
            return target
        return deco

    def add(self, key: str, target: Any, *, source: str = "builtin", **meta: Any) -> Entry:
        """Прямая регистрация (в т.ч. во время работы приложения)."""
        entry = Entry(key=key, target=target, meta=dict(meta), source=source)
        self._entries[key] = entry
        self._notify()
        return entry

    def remove(self, key: str) -> None:
        if key in self._entries:
            del self._entries[key]
            self._notify()

    # ---- доступ ------------------------------------------------------------
    def get(self, key: str) -> Entry:
        return self._entries[key]

    def target(self, key: str) -> Any:
        return self._entries[key].target

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __iter__(self) -> Iterator[Entry]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def keys(self) -> list[str]:
        return list(self._entries)

    def describe(self) -> list[dict[str, Any]]:
        """Само-описание реестра: что доступно. Удобно для UI и диагностики."""
        return [
            {"key": e.key, "label": e.label, "source": e.source, "meta": e.meta}
            for e in self._entries.values()
        ]

    # ---- подписка на изменения (для GUI; без Qt) ---------------------------
    def on_change(self, callback: Callable[[Registry], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb(self)


# Глобальный каталог всех реестров — чтобы автообнаружение и GUI могли
# перечислить точки расширения обобщённо, не зная их поimённо.
ALL_REGISTRIES: dict[str, Registry] = {}


def make_registry(name: str) -> Registry:
    reg = Registry(name)
    ALL_REGISTRIES[name] = reg
    return reg
