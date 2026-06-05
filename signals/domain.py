"""
signals.domain
==============

Доменная модель — типизированные dataclass-ы вместо вложенных словарей с
магическими строковыми ключами. Это единственный источник правды; Qt-дерево
лишь отражает `Project`.

Пользовательские правки (свои имена, метки) — это просто поля модели
(`Subject.name`, `Analysis.label`), которые UI редактирует, а персистентность
сохраняет. Никакого программиста для переименования не требуется.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class ChannelMetadata:
    record_length: int = 0
    sample_interval: float = 0.0
    vertical_scale: float = 1.0
    vertical_offset: float = 0.0
    vertical_units: str = "V"
    horizontal_units: str = "s"
    probe: float = 1.0
    source_label: str = ""        # LABEL из меню осциллографа (TODO #1)


@dataclass
class Channel:
    name: str
    time: np.ndarray
    amplitude: np.ndarray
    metadata: ChannelMetadata = field(default_factory=ChannelMetadata)

    @property
    def display_label(self) -> str:
        """Что показывать на графике: пользовательский LABEL прибора или имя канала."""
        return self.metadata.source_label or self.name


@dataclass
class MeasurementParams:
    # Значения по умолчанию специально подобраны (как в оригинале), чтобы при
    # типовой работе ничего переключать не требовалось.
    start_freq: float = 100.0
    end_freq: float = 1000.0
    sweep_time: float = 30.0      # длительность свипа генератора, с
    record_time: float = 1.0      # анализируемое окно (строб), с
    cut_second: float = 0.0       # относительный сдвиг строба, с
    fixedlevel: float = 0.6       # пороговый уровень, В
    gain: float = 7.0             # коэффициент усиления АЧХ
    amplitude: float = 1.0        # амплитуда генератора, В
    offset: float = 0.0           # смещение генератора, В
    normalize: bool = False       # привести максимум к единице (TODO #5)
    edge_strategy: str = "adaptive"        # стратегия поиска фронта (адаптивный порог)

    @property
    def bandwidth(self) -> float:
        return self.end_freq - self.start_freq


@dataclass
class Analysis:
    params: MeasurementParams = field(default_factory=MeasurementParams)
    channels: dict[str, Channel] = field(default_factory=dict)
    signal_start_channel: str = ""        # канал для поиска начала сигнала
    selected_channel: str = ""            # канал, по которому строится АЧХ
    source_file: Path | None = None
    label: str = ""                                  # пользовательская метка (TODO #2)
    description: str = ""                            # описание измерения
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    dirty: bool = True                               # для инкрементального автосейва

    def __post_init__(self) -> None:
        names = list(self.channels)
        if not self.signal_start_channel and names:
            # как в оригинале: начало сигнала ищем по CH1, если он есть
            self.signal_start_channel = "CH1" if "CH1" in names else names[0]
        if not self.selected_channel and names:
            # АЧХ по умолчанию строим по CH2, если он есть
            self.selected_channel = "CH2" if "CH2" in names else names[0]


@dataclass
class Subject:                                       # предмет
    code: str
    name: str = ""
    analyses: list[Analysis] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.code


@dataclass
class Project:                                       # единственный источник правды
    subjects: list[Subject] = field(default_factory=list)

    def subject(self, code: str) -> Subject | None:
        return next((s for s in self.subjects if s.code == code), None)

    def dirty_analyses(self) -> list[tuple[Subject, Analysis]]:
        """Только изменённые анализы — основа инкрементального сохранения."""
        return [(s, a) for s in self.subjects for a in s.analyses if a.dirty]
