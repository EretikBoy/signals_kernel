"""
Демонстрация ядра архитектуры. Запуск:  python -m examples.demo

Показывает:
1. Автообнаружение плагинов из трёх источников (встроенные / drop-in / pip).
2. Само-описание точек расширения (что доступно).
3. Интроспекцию возможностей прибора ("что ты умеешь").
4. Добавление пользовательской колонки и функции В РАНТАЙМЕ (без программиста).
5. Сквозной расчёт АЧХ на синтетическом сигнале + значения всех колонок.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from signals.plugins import discover, supports, Cap, ALL_REGISTRIES
from signals.extpoints import INSTRUMENTS, COLUMNS, FUNCTIONS, EDGE_STRATEGIES
from signals.domain import Analysis, Channel, ChannelMetadata, MeasurementParams
from signals.engine import analyze
from signals.runtime_ext import register_user_column


def banner(text: str) -> None:
    print(f"\n=== {text} ===")


def main() -> None:
    dropin = Path(__file__).resolve().parent.parent / "plugins_dropin"

    banner("1. Автообнаружение плагинов")
    report = discover(builtin_packages=("signals.contrib",), folders=(dropin,))
    for source, items in report.items():
        print(f"  {source}: {len(items)}")
        for it in items:
            print(f"     • {it}")

    banner("2. Точки расширения (само-описание)")
    for name, reg in ALL_REGISTRIES.items():
        keys = ", ".join(reg.keys())
        print(f"  {name:14} [{len(reg)}]: {keys}")

    banner("3. Приборы и их возможности (интроспекция)")
    for entry in INSTRUMENTS:
        caps = ", ".join(sorted(entry.meta.get("caps", set())))
        is_gen = "генератор ✔" if Cap.GENERATOR in entry.meta.get("caps", set()) else "генератора нет"
        print(f"  {entry.key:10} — {entry.label}")
        print(f"               возможности: {caps}")
        print(f"               GUI покажет панель генератора? {is_gen}")

    # Создаём прибор и спрашиваем его самого (а не таблицу моделей)
    hantek = INSTRUMENTS.target("hantek")(resource="0")
    print(f"\n  hantek.supports(GENERATOR) = {supports(hantek, Cap.GENERATOR)}")
    print(f"  hantek.supports(SET_TIMEBASE) = {supports(hantek, Cap.SET_TIMEBASE)}")

    banner("4. Пользовательское расширение В РАНТАЙМЕ (без программиста)")
    print(f"  Колонок до: {len(COLUMNS)}")
    register_user_column("amp_over_sqrt_f", label="A/√f (моя формула)",
                         expr="max(amp) / sqrt(max(freqs))")
    print(f"  Колонок после добавления пользовательской: {len(COLUMNS)}")
    print(f"  Новая колонка: {COLUMNS.get('amp_over_sqrt_f').label} "
          f"(источник={COLUMNS.get('amp_over_sqrt_f').source})")

    banner("5. Сквозной расчёт АЧХ на синтетическом резонансе")
    # синтетический отклик: резонанс ~ на середине окна
    fs = 250_000
    t = np.arange(0, 1.0, 1 / fs)
    f0_pos = 0.5
    envelope = 1.0 / (1 + ((t - f0_pos) / 0.02) ** 2)        # лоренцев пик
    carrier = np.sin(2 * np.pi * (100 + 900 * t) * t)
    signal = envelope * carrier
    ch = Channel("CH1", time=t, amplitude=signal, metadata=ChannelMetadata(source_label="Вход"))
    analysis = Analysis(
        params=MeasurementParams(start_freq=100, end_freq=1000, record_time=1.0,
                                 gain=1.0, edge_strategy="threshold_crossing"),
        channels={"CH1": ch},
    )
    result = analyze(analysis)

    print(f"  Стратегия фронта: {analysis.params.edge_strategy} "
          f"(доступно: {', '.join(EDGE_STRATEGIES.keys())})")
    print(f"  Точек АЧХ: {result.freqs.size}, "
          f"диапазон частот: {result.freqs.min():.0f}–{result.freqs.max():.0f} Гц")
    print("\n  Значения всех колонок (включая drop-in и пользовательскую):")
    for entry in COLUMNS:
        try:
            value = entry.target(result, "CH1")
            print(f"     {entry.label:24} = {value:.4g}")
        except Exception as exc:                       # noqa: BLE001 — демо
            print(f"     {entry.label:24} = <ошибка: {exc}>")


if __name__ == "__main__":
    main()
