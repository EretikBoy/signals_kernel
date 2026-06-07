# Сценарии расширения signals (рецепты)

Готовые пошаговые инструкции «как добавить X». Сигнатуры и контракты — в
[`plugins.md`](plugins.md). Общий принцип: создаёте отдельный модуль-плагин и
кладёте его одним из трёх способов (встроенный пакет `signals/contrib/`,
drop-in `~/.signals/plugins/`, или pip-пакет с entry point `signals.plugins`).
Ядро при этом не меняется.

---

## A. Новый осциллограф (VISA / SCPI)

1. Создайте файл, напр. `~/.signals/plugins/scope_acme.py` (drop-in — без
   перекомпиляции) или `signals/contrib/inst_acme.py` (встроенный).
2. Вставьте шаблон и допишите общение с прибором в `connect/read_all`:

```python
from signals.extpoints import INSTRUMENTS
from signals.instruments import InstrumentBase
from signals.plugins.capabilities import Cap
from signals.domain import Channel, ChannelMetadata
import numpy as np

@INSTRUMENTS.register("acme", label="ACME DSO-1000", kind="oscilloscope",
                      caps={Cap.READ_WAVEFORM, Cap.SET_TIMEBASE})
class AcmeScope(InstrumentBase):
    CAPABILITIES = frozenset({Cap.READ_WAVEFORM, Cap.SET_TIMEBASE})
    USES_VISA = True
    IDN_KEYWORDS = ("ACME",)                     # для сопоставления ответа *IDN?

    @classmethod
    def matches_idn(cls, idn: str) -> bool:
        return any(k in (idn or "").upper() for k in cls.IDN_KEYWORDS)

    def __init__(self, resource: str) -> None:
        self.resource = resource
        self._inst = None

    def connect(self) -> None:
        import pyvisa                              # ленивый импорт тяжёлой зависимости
        self._inst = pyvisa.ResourceManager().open_resource(self.resource)

    def disconnect(self) -> None:
        if self._inst is not None:
            self._inst.close()

    @property
    def channel_count(self) -> int:
        return 2

    def read_channel(self, n: int) -> Channel | None:
        # self._inst.write(f"DATA:SOURCE CH{n}") ; raw = self._inst.query_binary_values(...)
        t = np.linspace(0, 1, 1000); a = np.zeros_like(t)   # ← замените реальным чтением
        return Channel(name=f"CH{n}", time=t, amplitude=a,
                       metadata=ChannelMetadata(record_length=t.size, source_label=f"CH{n}"))

    def read_all(self) -> dict[str, Channel]:
        return {f"CH{n}": ch for n in range(1, self.channel_count + 1)
                if (ch := self.read_channel(n)) is not None}

    def set_timebase(self, seconds_per_div: float) -> None:
        self._inst.write(f"HORizontal:SCAle {seconds_per_div}")
```

3. Перезапустите приложение → прибор появится при сканировании (по `*IDN?`).
   Проверка подключения плагина — раздел **I**.

Если прибор должен уметь работать в свип-измерении одним длинным захватом (как
Hantek — генератор и осциллограф совмещены, и проще снять весь свип за один раз,
чем гонять отдельные кадры) — добавьте ещё `set_timebase_for_window`,
`set_peak_detect`, `start_acquisition`, `read_captured` и атрибут `window_seconds`.
`MeasurementService` сам обнаружит их через `hasattr` и пойдёт по быстрому пути;
не реализуете — будет работать через базовый протокол. Подробнее — `plugins.md`
§4, готовый пример — `signals/contrib/inst_hantek.py`.

---

## B. Новый генератор

Аналогично, но реализуется протокол `Generator`:

```python
from signals.extpoints import INSTRUMENTS
from signals.instruments import InstrumentBase
from signals.plugins.capabilities import Cap

@INSTRUMENTS.register("acme_gen", label="ACME AWG", kind="generator",
                      caps={Cap.GENERATOR, Cap.SWEEP})
class AcmeGenerator(InstrumentBase):
    CAPABILITIES = frozenset({Cap.GENERATOR, Cap.SWEEP})
    USES_VISA = True
    IDN_KEYWORDS = ("ACME",)

    @classmethod
    def matches_idn(cls, idn: str) -> bool:
        return any(k in (idn or "").upper() for k in cls.IDN_KEYWORDS)

    def __init__(self, resource: str) -> None:
        self.resource = resource; self._inst = None

    def connect(self) -> None:
        import pyvisa
        self._inst = pyvisa.ResourceManager().open_resource(self.resource)

    def disconnect(self) -> None:
        if self._inst is not None:
            self._inst.close()

    def configure_sweep(self, *, start, stop, seconds, amplitude, offset, function="SIN") -> None:
        self._inst.write(f"SOUR:SWE:STAT ON")
        self._inst.write(f"SOUR:FREQ:STAR {start}")
        self._inst.write(f"SOUR:FREQ:STOP {stop}")
        self._inst.write(f"SOUR:SWE:TIME {seconds}")
        self._inst.write(f"SOUR:VOLT {amplitude}")
        self._inst.write(f"SOUR:VOLT:OFFS {offset}")

    def set_output(self, on: bool) -> None:
        self._inst.write(f"OUTP {'ON' if on else 'OFF'}")
```

Если прибор без VISA (USB-DLL, как Hantek) — вместо `USES_VISA`/`matches_idn`
экспортируйте в модуле функцию `discover(log=None) -> list[dict]` (см. `plugins.md` §4).

---

## C. Вычисляемый столбец (код)

Файл `~/.signals/plugins/col_shape.py`:

```python
from signals.extpoints import COLUMNS
from signals.engine import channel_metrics

def col_resonance_q(result, channel):
    m = channel_metrics(result, channel, 0.707)
    return m["resonance_frequency"] / max(m["q_factor"], 1e-9)

COLUMNS.add("res_over_q", col_resonance_q, source="runtime",
            label="Резонанс / Q", unit="Гц")
```

Функция столбца получает `(result: AnalysisResult, channel: str)` и возвращает
число. После запуска столбец доступен в диалоге настройки столбцов (он берёт все
записи `COLUMNS` с `source="runtime"`).

---

## D. Столбец-формула без кода (из приложения)

Если писать код не хочется — зарегистрируйте формулу строкой:

```python
from signals.runtime_ext import register_user_column
register_user_column("amp_ratio", "Пик/среднее", "max(amp) / mean(amp)")
```

Доступные имена в формуле: `freqs`, `amp` (массивы канала), `pi`, функции
реестра `FUNCTIONS` (`max, min, mean, std, sum, abs, sqrt, log10`, плюс ваши из
сценария **E**). Это тот же механизм, что используется в UI при добавлении
пользовательской колонки.

---

## E. Своя функция для выражений

Файл `~/.signals/plugins/func_rms.py`:

```python
from signals.extpoints import FUNCTIONS
import numpy as np

@FUNCTIONS.register("rms", label="RMS")
def rms(a):
    return float(np.sqrt(np.mean(np.square(np.asarray(a, float)))))
```

Теперь `rms(amp)` доступно в столбцах-формулах и в сводке. В рантайме из кода UI —
`register_user_function("rms", rms)`.

---

## F. Стратегия поиска фронта как drop-in (без перекомпиляции)

Самый наглядный случай, когда один файл, брошенный в папку плагинов, добавляет
целый алгоритм: положили — и в параметрах анализа можно выбрать новый способ
определения начала сигнала, без перезапуска IDE и пересборки чего-либо.

Файл `~/.signals/plugins/edge_derivative.py`:

```python
from signals.extpoints import EDGE_STRATEGIES
from signals.domain import MeasurementParams
import numpy as np

@EDGE_STRATEGIES.register("max_derivative", label="По максимуму производной")
def by_max_derivative(smoothed: np.ndarray, dt: float, params: MeasurementParams) -> int:
    if smoothed.size < 2:
        return 0
    start = int(np.argmax(np.gradient(smoothed)))        # самый крутой рост
    off = int(params.cut_second / dt) if dt > 0 else 0
    return max(0, min(start + off, smoothed.size - 1))
```

После перезапуска стратегия `max_derivative` появится в выборе и применяется,
когда `analysis.params.edge_strategy == "max_derivative"`.

---

## G. Парсер нового формата файла

Файл `~/.signals/plugins/parse_tek_isf.py` (пример — упрощённо):

```python
from signals.extpoints import PARSERS
from signals.domain import Channel, ChannelMetadata
import numpy as np

@PARSERS.register("twocol", label="Две колонки t;A", extensions=[".dat"])
def parse_twocol(path: str) -> dict[str, Channel]:
    arr = np.loadtxt(path, delimiter=";")
    t, a = arr[:, 0], arr[:, 1]
    ch = Channel(name="CH1", time=t, amplitude=a,
                 metadata=ChannelMetadata(record_length=t.size, source_label="CH1"))
    return {"CH1": ch}
```

`parse_file(path)` сам выберет парсер по расширению из `meta["extensions"]`.
Возвращайте словарь `{"CH1": Channel, "CH2": Channel, ...}`.

---

## H. Оформить плагины как pip-пакет

Чтобы фича ставилась через `pip install` и подхватывалась автоматически:

1. Структура пакета:

```
my-signals-acme/
  pyproject.toml
  signals_acme/
    __init__.py
    scope.py        # содержит @INSTRUMENTS.register(...)
```

2. В `pyproject.toml` объявите entry point группы **`signals.plugins`**:

```toml
[project]
name = "signals-acme"
version = "0.1.0"
dependencies = ["pyvisa"]

[project.entry-points."signals.plugins"]
acme = "signals_acme.scope"      # модуль, который импортируется → срабатывают регистрации
```

3. `pip install .` → при следующем запуске `discover()` загрузит модуль через
   entry point, и прибор появится. Правок в `signals` не требуется.

---

## I. Проверить, что плагин подключился

Отчёт автообнаружения и содержимое реестров:

```python
from signals.plugins import discover
from signals.extpoints import INSTRUMENTS, EDGE_STRATEGIES, COLUMNS
from pathlib import Path

report = discover(builtin_packages=("signals.contrib",),
                  folders=(Path.home()/".signals"/"plugins",))
print("Загружено:", report)                 # {'builtin': [...], 'dropin': [...], 'entrypoint': [...]}

print("Приборы:", INSTRUMENTS.keys())
print("Стратегии фронта:")
for e in EDGE_STRATEGIES.describe():
    print(" ", e["key"], "—", e["label"], f"({e['source']})")
print("Столбцы-плагины:", [e["key"] for e in COLUMNS.describe()])
```

Если вашего ключа нет в списке — проверьте: файл лежит в нужной папке и не
начинается с `_`; декоратор `@REG.register(...)` действительно выполняется при
импорте; нет ошибки импорта (она логируется через `logging` на уровне `INFO`/
`ERROR` каналом `signals`).

То же самое видно и без отдельного скрипта: при старте программы в журнале есть
строка «Плагины загружены: builtin=…, dropin=…, entrypoint=…», а появившийся
плагин сразу всплывает в меню и диалогах — они ведь строятся из тех же реестров.
