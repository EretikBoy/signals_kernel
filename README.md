# signals — анализатор АЧХ

Приложение для измерения и анализа амплитудно-частотной характеристики
резонансных систем. Плагинная архитектура: приборы, колонки-метрики, функции
выражений и парсеры добавляются как плагины, без правок ядра.

Статус по этапам — см. `STAGES.md`. Сейчас готовы этап 1 (рефакторинг) и
этап 2 (полное восстановление функционала, GUI).

## Установка

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
```

## Запуск

```bash
python main.py
```

## Прибор Hantek DSO-6104BD (этап 3 — поддержка DLL)

Прибор управляется через `HTHardDll.dll` (USB, `__stdcall`). Чтобы приложение его
нашло, положите DLL Hantek, **разделив по разрядности Python**:

* 64-битный Python → `signals/contrib/hantek_dll/x64/`
* 32-битный Python → `signals/contrib/hantek_dll/x86/`

Кладите все DLL из SDK (`HTHardDll.dll`, `HTSoftDll.dll`, `HTDisplayDll.dll`,
`HTMeasDll.dll` и зависимости). Можно также указать папку через меню
**«Приборы → Указать папку с DLL Hantek…»** или переменную `HANTEK_DLL_DIR`.

**Важно про разрядность.** DLL и Python должны совпадать. SDK Hantek часто
32-битный — тогда либо возьмите 64-битную DLL, либо запустите 32-битный Python.
При несовпадении/отсутствии DLL в **журнале** будет понятное сообщение, а после
размещения DLL «Обновить список приборов» покажет, какая DLL загружена и какие
приборы откликнулись (удобно для снятия фингерпринтов).

Боевая проверка чтения/свипа на реальном приборе — на машине с прибором; в коде
отмечены `TODO(device)` (упаковка структур и частота на быстрых развёртках).

## Архитектура (без Qt — ядро; Qt только в app_qt)

```
signals/
  plugins/      реестр + автообнаружение + capabilities
  domain.py     Channel / Analysis / Subject / Project
  engine.py     расчёт АЧХ и временных рядов
  io/           парсеры + хранилище проекта (.sigproj)
  services/     analyze_full, MeasurementService (свип)
  instruments.py + contrib/inst_*   приборы (Hantek/Tektronix/Rigol)
  contrib/      встроенные плагины (метрики, функции, стратегии фронта)
  app_qt/       GUI (главное окно, графики, сводка, панель прибора)
main.py         точка входа
tools/make_sample.py   генератор тестовых данных
```
