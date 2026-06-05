"""
signals.extpoints
==================

Конкретные точки расширения приложения. Это «одно место», через которое
добавляется ЛЮБАЯ фича. Чтобы расширить программу, не нужно знать её внутренности
— достаточно зарегистрироваться в нужном реестре:

    INSTRUMENTS — приборы (осциллографы/генераторы)          (TODO #4, #8, #13)
    COLUMNS     — вычисляемые колонки дерева / метрики         (TODO #2, #6)
    FUNCTIONS   — функции языка выражений сводки               (расширение алгебры АЧХ)
    PARSERS     — форматы входных файлов
    EXPORTERS   — форматы выгрузки (Excel, CSV, PDF, ...)

GUI строит свои меню/колонки/панели, перечисляя эти реестры (`.describe()`),
а не из захардкоженных списков. Пользователь может добавлять колонки и выражения
в рантайме — см. signals.runtime_ext.
"""
from __future__ import annotations

from .plugins.registry import make_registry

INSTRUMENTS = make_registry("instruments")
COLUMNS = make_registry("columns")
FUNCTIONS = make_registry("functions")
PARSERS = make_registry("parsers")
EXPORTERS = make_registry("exporters")
EDGE_STRATEGIES = make_registry("edge_strategies")   # поиск начала сигнала (TODO #7)
