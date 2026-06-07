# Точки расширения signals

Идея простая: любая новая фича — прибор, столбец, формат файла, алгоритм,
функция в выражениях — оформляется отдельным модулем и регистрируется в
соответствующем *реестре*, а не вписывается в код GUI или ядра. GUI, в свою
очередь, не хранит списков «какие приборы бывают» — он спрашивает реестры
(`.describe()`) и строит меню/столбцы/панели по тому, что там нашлось. Поэтому
добавление прибора не требует трогать ничего, кроме одного нового файла.

Ниже — что где лежит и как этим пользоваться. Готовые рецепты «как добавить X»
см. в [`scenarios.md`](scenarios.md) — там меньше теории и больше copy-paste.

---

## 1. Реестры

Объявлены в одном месте — `signals/extpoints.py`:

| Реестр | Что регистрируем |
|--------|------------------|
| `INSTRUMENTS` | приборы — осциллографы и генераторы |
| `COLUMNS` | вычисляемые столбцы дерева / метрики |
| `FUNCTIONS` | функции языка выражений (сводка, столбцы-формулы) |
| `PARSERS` | форматы входных файлов |
| `EXPORTERS` | форматы выгрузки (зарезервировано) |
| `EDGE_STRATEGIES` | алгоритмы поиска начала сигнала |

Каждый реестр — экземпляр `Registry` (`signals/plugins/registry.py`). API:

```python
REG.register("key", label="...", **meta)   # декоратор; key по умолчанию = __name__ цели
REG.add("key", target, *, source="builtin", **meta)   # прямая регистрация (в т.ч. в рантайме)
REG.get("key") -> Entry        REG.target("key") -> сам объект
"key" in REG                   list(REG) -> Entry'ы        REG.keys()
REG.describe() -> [ {key,label,source,meta}, ... ]    # само-описание для UI/диагностики
REG.on_change(cb)              # подписка (GUI перерисовывается при появлении плагина)
```

`Entry` хранит: `key`, `target`, `meta` (словарь: `label`, `unit`, `caps`, `extensions`…)
и `source` (`builtin | dropin | entrypoint | runtime`). `Entry.label` берётся из
`meta["label"]`, а если его нет — равен ключу.

Легко перепутать: `source` лежит прямо в `Entry.source`, а не внутри `meta` —
если будете писать что-то с реестрами, не ищите его там.

---

## 2. Автообнаружение плагинов

`signals/plugins/discovery.py` → функция `discover(...)`. Приложение вызывает её в
`main.py`:

```python
discover(builtin_packages=("signals.contrib",), folders=(Path.home()/".signals"/"plugins",))
```

Три равноправных способа подключить плагин (ни один не требует правок ядра):

1. **Встроенный** — модуль в пакете `signals/contrib/`. Импортируется при старте,
   срабатывают его декораторы `@REG.register(...)`.
2. **Drop-in** — `.py`-файл в папке `~/.signals/plugins/`. Сканируется и импортируется
   при запуске. Перекомпиляция не нужна. Файлы с `_` в начале имени пропускаются.
3. **Pip-пакет** — сторонний пакет объявляет entry point группы **`signals.plugins`**;
   после `pip install` фича появляется сама.

`discover()` возвращает отчёт `{"builtin": [...], "dropin": [...], "entrypoint": [...]}`
— удобно логировать, что подключилось.

---

## 3. Возможности (capabilities)

`signals/plugins/capabilities.py`. Объект сам сообщает, что умеет; потребитель
спрашивает — никаких `if model in [...]`.

Константы `Cap`:

```
READ_WAVEFORM  SET_TIMEBASE  SET_ACQ_MODE  SET_POINTS  READ_LABEL   # осциллограф
GENERATOR      SWEEP         BURST                                   # генератор/источник
```

Объявление и проверка:

```python
class MyScope(InstrumentBase):
    CAPABILITIES = frozenset({Cap.READ_WAVEFORM, Cap.SET_TIMEBASE})

from signals.plugins.capabilities import supports
supports(scope, Cap.GENERATOR)   # -> bool
```

`InstrumentBase.capabilities()` отдаёт `CAPABILITIES` наружу. GUI рисует панель
генератора только если `supports(scope, Cap.GENERATOR)`.

---

## 4. Контракт прибора

`signals/instruments.py`. Прибор реализует один или оба протокола.

### Осциллограф (`Oscilloscope`)

Обязательно:

```python
def connect(self) -> None: ...
def disconnect(self) -> None: ...
def capabilities(self) -> frozenset[str]: ...     # даёт InstrumentBase
@property
def channel_count(self) -> int: ...
def read_channel(self, n: int) -> Channel | None: ...
def read_all(self) -> dict[str, Channel]: ...     # {"CH1": Channel, ...}
```

Опционально (наличие объявляется через `capabilities()`):
`set_timebase(seconds_per_div)`, `set_acquisition_mode(mode)`, `set_record_length(points)`.

### Генератор (`Generator`)

```python
def connect(self) -> None: ...
def disconnect(self) -> None: ...
def capabilities(self) -> frozenset[str]: ...
def configure_sweep(self, *, start: float, stop: float, seconds: float,
                    amplitude: float, offset: float, function: str = "SIN") -> None: ...
def set_output(self, on: bool) -> None: ...
```

### Расширенные методы для свип-измерения

`MeasurementService` (`signals/services/measurement.py`) вызывает эти методы, если
они **есть** (через `hasattr`) — так прибор с одним длинным захватом (Hantek)
работает оптимально, а простой прибор обходится базовым контрактом:

- осциллограф: `set_timebase_for_window(seconds)`, `set_peak_detect(on: bool)`,
  `start_acquisition()`, `read_captured()`, атрибут `window_seconds`;
- генератор: `set_frequency(hz)` (программный свип частоты).

Образцы: `signals/contrib/inst_hantek.py` (USB-DLL, со встроенным генератором и
расширенными методами) и `signals/contrib/inst_tektronix.py` (VISA).

### Чтобы прибор находился сканером

GUI сканирует приборы (`signals/app_qt/workers.py`) двумя путями:

- **VISA-приборы** — класс объявляет `USES_VISA = True`, кортеж `IDN_KEYWORDS` и
  classmethod `matches_idn(idn) -> bool` (сопоставление ответа `*IDN?`).
- **не-VISA (USB/DLL)** — модуль плагина экспортирует функцию
  `discover(log=None) -> list[dict]` с элементами `{kind, label, resource, idn, caps}`
  (скан шины). См. `inst_hantek.discover`.

### Регистрация прибора

```python
from signals.extpoints import INSTRUMENTS
from signals.instruments import InstrumentBase
from signals.plugins.capabilities import Cap

@INSTRUMENTS.register("acme", label="ACME DSO", kind="oscilloscope",
                      caps={Cap.READ_WAVEFORM, Cap.SET_TIMEBASE})
class AcmeScope(InstrumentBase):
    CAPABILITIES = frozenset({Cap.READ_WAVEFORM, Cap.SET_TIMEBASE})
    ...
```

`kind` — `"oscilloscope"` или `"generator"`; `caps` дублирует возможности в `meta`
для UI.

---

## 5. Столбцы дерева и метрики

`signals/services/columns.py`. Стандартный столбец — словарь
`{"key", "title", "source"}`. `column_value(analysis, result, col)` резолвит
значение по `source`:

| `source` | Откуда значение |
|----------|-----------------|
| `params` | `analysis.params.<key>` (параметр обработки) |
| `channel` | метрика канала: `channel_metrics(result, ch, fixedlevel)[key]` |
| `raw_max` / `raw_min` | сырые экстремумы канала |
| `processor` | служебное (напр. время начала анализа) |
| `formula` / `runtime` | вызов `COLUMNS.target(key)(result, channel)` |

Доступные метрики канала (`source="channel"`): `max_amplitude`,
`resonance_frequency`, `bandwidth_707`, `bandwidth_fixed`, `q_factor`.

### Вычисляемый столбец-плагин (код)

Зарегистрируйте функцию `(result: AnalysisResult, channel: str) -> value` и
добавьте описание в доступные столбцы:

```python
from signals.extpoints import COLUMNS

def col_peak_over_q(result, channel):
    from signals.engine import channel_metrics
    m = channel_metrics(result, channel, 0.707)
    return m["max_amplitude"] / max(m["q_factor"], 1e-9)

COLUMNS.add("peak_over_q", col_peak_over_q, source="runtime",
            label="Пик / Q", unit="")
```

`available_columns()` подхватывает все записи `COLUMNS` с `source == "runtime"`
(включая формульные) и показывает их в диалоге столбцов.

### Столбец-формула без кода (рантайм / из UI)

`signals/runtime_ext.py`:

```python
from signals.runtime_ext import register_user_column
register_user_column("ratio", "Отношение", "max(amp) / mean(amp)", unit="")
```

В выражении доступны имена: `freqs`, `amp` (массивы частоты/амплитуды канала),
`pi`, и все функции реестра `FUNCTIONS`. Выражение исполняется в **песочнице**
(AST-проверка `_check_safe`: запрещены импорты, доступ к атрибутам, вызовы
опасных встроенных; разрешены арифметика, сравнения, тернарник, срезы, вызовы
зарегистрированных функций).

---

## 6. Функции языка выражений

`FUNCTIONS` используется и в сводке, и в столбцах-формулах. Встроенные
(`signals/contrib/funcs.py`): `max, min, mean, std, sum, abs, sqrt, log10`.

Добавить свою:

```python
from signals.extpoints import FUNCTIONS
import numpy as np
FUNCTIONS.add("rms", lambda a: float(np.sqrt(np.mean(np.square(a)))), source="builtin")
# в рантайме из UI:
from signals.runtime_ext import register_user_function
register_user_function("rms", my_rms)
```

(У «Набора кривых» — `signals/app_qt/curve_expr.py` — свой, отдельный язык
выражений со своими функциями вроде `band`, `tangent`, `integral` и срезом
`g1[a:b]`; с `FUNCTIONS` он не пересекается.)

---

## 7. Стратегии поиска начала сигнала

`EDGE_STRATEGIES`. Сигнатура — `(smoothed, dt, params) -> int` (индекс старта
строба). Выбор стратегии — в `analysis.params.edge_strategy`.

```python
from signals.extpoints import EDGE_STRATEGIES
from signals.domain import MeasurementParams
import numpy as np

@EDGE_STRATEGIES.register("first_rise", label="Первый подъём 50 %")
def first_rise(smoothed: np.ndarray, dt: float, params: MeasurementParams) -> int:
    if smoothed.size == 0:
        return 0
    thr = 0.5 * float(np.max(smoothed))
    idx = np.where(smoothed >= thr)[0]
    start = int(idx[0]) if idx.size else 0
    off = int(params.cut_second / dt) if dt > 0 else 0
    return max(0, min(start + off, smoothed.size - 1))
```

Встроенные: `level_jump` (по умолчанию — скачок на новый уровень/фронт),
`adaptive`, `max_amplitude`, `threshold_crossing` (см. `signals/contrib/edge.py`).

---

## 8. Парсеры входных файлов

`PARSERS`. Сигнатура — `(path: str) -> dict[str, Channel]`. Расширения задаются в
`meta["extensions"]`; `parse_file()` (`signals/io/parsers.py`) выбирает парсер по
расширению.

```python
from signals.extpoints import PARSERS
from signals.domain import Channel, ChannelMetadata
import numpy as np

@PARSERS.register("tsv", label="TSV", extensions=[".tsv"])
def parse_tsv(path: str) -> dict[str, Channel]:
    data = np.genfromtxt(path, delimiter="\t", names=True)
    t = data["CH1_time"]; a = data["CH1_amplitude"]
    ch = Channel(name="CH1", time=t, amplitude=a,
                 metadata=ChannelMetadata(record_length=t.size, source_label="CH1"))
    return {"CH1": ch}
```

Образец полей `Channel`/`ChannelMetadata` — функция-помощник `_channel()` в
`signals/io/parsers.py`.

---

## 9. Экспортёры (зарезервировано)

Реестр `EXPORTERS` существует, но пока не подключён к UI. Планируемая сигнатура —
`(data, path: str) -> None` с `meta["extensions"]`. Регистрация — как у парсеров:

```python
from signals.extpoints import EXPORTERS

@EXPORTERS.register("csv_out", label="CSV", extensions=[".csv"])
def export_csv(data, path: str) -> None:
    ...
```

(Текущая выгрузка в Excel реализована напрямую в сводке/окне графиков.)

---

## 10. Карта модулей

```
signals/
  extpoints.py            ← реестры INSTRUMENTS/COLUMNS/FUNCTIONS/PARSERS/EXPORTERS/EDGE_STRATEGIES
  plugins/
    registry.py           ← класс Registry, Entry
    capabilities.py       ← Cap, supports()
    discovery.py          ← discover() (builtin/dropin/entrypoint)
  instruments.py          ← протоколы Oscilloscope/Generator, InstrumentBase
  domain.py               ← Channel, MeasurementParams, Analysis, Subject, Project
  engine.py               ← analyze(), channel_metrics(), AnalysisResult
  runtime_ext.py          ← register_user_column/function, compile_expression/compile_safe
  services/
    columns.py            ← STANDARD_COLUMNS, column_value(), available_columns()
    measurement.py        ← MeasurementService (свип + захват)
    templates.py          ← шаблоны обработки
  io/
    parsers.py            ← парсеры (PARSERS)
    store.py              ← проект на диске (.sigproj / папка)
  contrib/                ← ВСТРОЕННЫЕ плагины (импортируются discover)
    inst_hantek.py, inst_tektronix.py, edge.py, funcs.py, hantek_dll/{x86,x64}/
  app_qt/                 ← GUI (Qt); ядро от Qt не зависит
```

Принцип: ядро (`signals/*` без `app_qt`) не знает о конкретных плагинах и о Qt.
Любая модификация — это новый модуль-плагин, который лишь регистрируется в реестре.
