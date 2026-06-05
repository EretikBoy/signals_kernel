"""
Регистрация существующих приборов (Tektronix-осциллограф, Rigol-генератор) как
плагинов. Тяжёлые зависимости (pyvisa / tm_devices) импортируются лениво внутри
connect(), чтобы модуль грузился где угодно. Сами драйверы переносятся из
app/modules/* на этапе 4 — здесь показано, что они сосуществуют в каталоге.
"""
from __future__ import annotations

from ..extpoints import INSTRUMENTS
from ..instruments import InstrumentBase
from ..plugins.capabilities import Cap


@INSTRUMENTS.register(
    "tektronix",
    label="Tektronix MDO/DPO/TDS",
    kind="oscilloscope",
    caps={Cap.READ_WAVEFORM, Cap.SET_TIMEBASE, Cap.SET_ACQ_MODE, Cap.READ_LABEL},
)
class TektronixScope(InstrumentBase):
    CAPABILITIES = frozenset(
        {Cap.READ_WAVEFORM, Cap.SET_TIMEBASE, Cap.SET_ACQ_MODE, Cap.READ_LABEL}
    )
    USES_VISA = True
    IDN_KEYWORDS = ("TEKTRONIX", "TEKTRONIK", "TEK ")

    @classmethod
    def matches_idn(cls, idn: str) -> bool:
        up = (idn or "").upper()
        return any(k in up for k in cls.IDN_KEYWORDS)

    def __init__(self, resource: str) -> None:
        self.resource = resource
        self._scope = None

    def connect(self) -> None:
        from tm_devices import DeviceManager  # ленивый импорт тяжёлой зависимости
        self._dm = DeviceManager()
        self._scope = self._dm.add_scope(self.resource)

    def disconnect(self) -> None:
        if self._scope is not None:
            self._dm.close()


@INSTRUMENTS.register(
    "rigol",
    label="Rigol DG (генератор)",
    kind="generator",
    caps={Cap.GENERATOR, Cap.SWEEP},
)
class RigolGenerator(InstrumentBase):
    CAPABILITIES = frozenset({Cap.GENERATOR, Cap.SWEEP})
    USES_VISA = True
    IDN_KEYWORDS = ("RIGOL",)

    @classmethod
    def matches_idn(cls, idn: str) -> bool:
        return any(k in (idn or "").upper() for k in cls.IDN_KEYWORDS)

    def __init__(self, resource: str) -> None:
        self.resource = resource
        self._inst = None

    def connect(self) -> None:
        import pyvisa  # ленивый импорт
        self._inst = pyvisa.ResourceManager().open_resource(self.resource)

    def disconnect(self) -> None:
        if self._inst is not None:
            self._inst.close()
