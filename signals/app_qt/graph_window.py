"""
signals.app_qt.graph_window
===========================

Окно настройки измерения и графиков (восстановление + переработка оригинала):

* Три графика ОДНОВРЕМЕННО: исходные сигналы со «стробом» анализируемого окна,
  сглаженные, АЧХ с маркерами (резонанс, 0.707, пороговый уровень) — не нужно
  прыгать между режимами.
* ЖИВОЙ предпросмотр: любое изменение поля сразу перерисовывает графики (оси
  автоподстраиваются), но работает с РАБОЧЕЙ КОПИЕЙ параметров.
* Кнопка «Применить» фиксирует параметры в измерении (и обновляет дерево);
  «Сбросить» возвращает к сохранённым; закрытие без «Применить» НЕ меняет данные —
  именно ради этого кнопка и нужна.
* Немодальное плавающее окно: можно открыть несколько и сравнивать.
* Каждое поле снабжено подсказкой о назначении.
"""
from __future__ import annotations

from dataclasses import replace

import matplotlib
matplotlib.use("QtAgg")
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ..domain import Analysis
from ..engine import analyze, channel_metrics, frequency_forecast
from ..extpoints import EDGE_STRATEGIES


def _spin(value, lo, hi, step, decimals, tip) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi); s.setSingleStep(step); s.setDecimals(decimals); s.setValue(value)
    s.setToolTip(tip)
    return s


class GraphWindow(QWidget):
    changed = pyqtSignal()
    closed = pyqtSignal(object)

    def __init__(self, analysis: Analysis, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.analysis = analysis
        self.setWindowTitle(f"Настройка измерения — {analysis.label or analysis.id}")
        self.resize(1240, 820)
        self._build_ui()
        self._load_from_model()
        self._preview()

    # ---- интерфейс ---------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        # ЛЕВО: настройки
        box = QGroupBox("Настройки параметров")
        grid = QGridLayout(box)
        r = 0
        names = list(self.analysis.channels)

        grid.addWidget(QLabel("Метка измерения:"), r, 0)
        self.label_edit = QLineEdit(); self.label_edit.setToolTip("Короткое имя измерения.")
        grid.addWidget(self.label_edit, r, 1); r += 1
        grid.addWidget(QLabel("Описание:"), r, 0)
        self.description_edit = QTextEdit(); self.description_edit.setMaximumHeight(56)
        self.description_edit.setToolTip("Произвольное описание измерения.")
        grid.addWidget(self.description_edit, r, 1); r += 1

        grid.addWidget(QLabel("Канал начала сигнала:"), r, 0)
        self.signal_start = QComboBox(); self.signal_start.addItems(names)
        self.signal_start.setToolTip("По этому каналу ищется момент начала сигнала (строб).")
        self.signal_start.currentTextChanged.connect(self._preview)
        grid.addWidget(self.signal_start, r, 1); r += 1

        grid.addWidget(QLabel("Канал для АЧХ:"), r, 0)
        self.selected = QComboBox(); self.selected.addItems(names)
        self.selected.setToolTip("Канал, по которому строится АЧХ и считаются параметры.")
        self.selected.currentTextChanged.connect(self._preview)
        grid.addWidget(self.selected, r, 1); r += 1

        self.start = _spin(100, 0, 1e9, 10, 0, "Начальная частота свипа, Гц.")
        grid.addWidget(QLabel("Стартовая частота, Гц:"), r, 0); grid.addWidget(self.start, r, 1); r += 1
        self.end = _spin(1000, 0, 1e9, 10, 0, "Конечная частота свипа, Гц.")
        grid.addWidget(QLabel("Конечная частота, Гц:"), r, 0); grid.addWidget(self.end, r, 1); r += 1
        self.record = _spin(1.0, 0.001, 1e6, 0.1, 3, "Длина анализируемого окна (строба), с.")
        grid.addWidget(QLabel("Время записи, с:"), r, 0); grid.addWidget(self.record, r, 1); r += 1
        self.cut = _spin(0.0, -1e6, 1e6, 0.1, 3, "Сдвиг строба относительно найденного начала, с.")
        grid.addWidget(QLabel("Сдвиг строба, с:"), r, 0); grid.addWidget(self.cut, r, 1); r += 1
        self.gain = _spin(7.0, 0, 1e6, 0.1, 2, "Коэффициент усиления АЧХ.")
        grid.addWidget(QLabel("Усиление:"), r, 0); grid.addWidget(self.gain, r, 1); r += 1
        self.level = _spin(0.6, 0, 1e6, 0.01, 2, "Пороговый уровень для полосы по фикс. уровню, В.")
        grid.addWidget(QLabel("Пороговый уровень, В:"), r, 0); grid.addWidget(self.level, r, 1); r += 1

        grid.addWidget(QLabel("Поиск фронта:"), r, 0)
        self.edge = QComboBox()
        for e in EDGE_STRATEGIES:
            self.edge.addItem(e.label, e.key)
        self.edge.setToolTip("Способ определения начала сигнала.")
        self.edge.currentIndexChanged.connect(self._preview)
        grid.addWidget(self.edge, r, 1); r += 1

        self.normalize = QPushButton("Максимум → 1: выкл")
        self.normalize.setCheckable(True)
        self.normalize.setToolTip("Нормировать АЧХ так, чтобы максимум был равен 1.")
        self.normalize.toggled.connect(self._on_normalize)
        grid.addWidget(self.normalize, r, 0, 1, 2); r += 1

        # кнопки действий — заметные
        self.apply_btn = QPushButton("Применить"); self.apply_btn.setProperty("accent", True)
        self.apply_btn.setToolTip("Зафиксировать параметры в измерении и обновить таблицу.")
        self.apply_btn.clicked.connect(self.apply)
        grid.addWidget(self.apply_btn, r, 0, 1, 2); r += 1
        self.revert_btn = QPushButton("Сбросить к сохранённым")
        self.revert_btn.setToolTip("Вернуть поля к последним применённым значениям.")
        self.revert_btn.clicked.connect(self.revert)
        grid.addWidget(self.revert_btn, r, 0, 1, 2); r += 1
        close_btn = QPushButton("Закрыть"); close_btn.clicked.connect(self.close)
        grid.addWidget(close_btn, r, 0, 1, 2); r += 1
        grid.setRowStretch(r, 1)

        # ЦЕНТР: три графика
        center = QVBoxLayout()
        self.figure = Figure(figsize=(8, 8))
        self.canvas = FigureCanvasQTAgg(self.figure)
        center.addWidget(NavigationToolbar2QT(self.canvas, self))
        center.addWidget(self.canvas, 1)
        self.ax1 = self.figure.add_subplot(311)
        self.ax2 = self.figure.add_subplot(312)
        self.ax3 = self.figure.add_subplot(313)

        # ПРАВО: параметры и прогноз
        right = QVBoxLayout()
        params_box = QGroupBox("Параметры канала")
        pv = QVBoxLayout(params_box)
        self.params_view = QTextEdit(); self.params_view.setReadOnly(True)
        pv.addWidget(self.params_view)
        forecast_box = QGroupBox("Прогноз полосы для проверки")
        fv = QVBoxLayout(forecast_box)
        crit_row = QHBoxLayout(); crit_row.addWidget(QLabel("Критерий, Гц/с:"))
        self.criterion = _spin(1.0, 0.1, 1000, 0.1, 2, "Критерий достаточности, Гц/с.")
        self.criterion.valueChanged.connect(self._update_forecast)
        crit_row.addWidget(self.criterion); fv.addLayout(crit_row)
        self.forecast_view = QTextEdit(); self.forecast_view.setReadOnly(True)
        fv.addWidget(self.forecast_view)
        right.addWidget(params_box, 1); right.addWidget(forecast_box)

        root.addWidget(box, 0)
        root.addLayout(center, 1)
        right_w = QWidget(); right_w.setLayout(right); right_w.setMaximumWidth(320)
        root.addWidget(right_w, 0)

        # живой предпросмотр для частотно-зависимых полей
        for w in (self.start, self.end, self.record, self.cut, self.gain, self.level):
            w.valueChanged.connect(self._preview)

    # ---- модель <-> поля ---------------------------------------------------
    def _load_from_model(self) -> None:
        p = self.analysis.params
        self.label_edit.setText(self.analysis.label)
        self.description_edit.setPlainText(self.analysis.description)
        self.start.setValue(p.start_freq); self.end.setValue(p.end_freq)
        self.record.setValue(p.record_time); self.cut.setValue(p.cut_second)
        self.gain.setValue(p.gain); self.level.setValue(p.fixedlevel)
        self.normalize.setChecked(p.normalize)
        if self.analysis.signal_start_channel:
            self.signal_start.setCurrentText(self.analysis.signal_start_channel)
        if self.analysis.selected_channel:
            self.selected.setCurrentText(self.analysis.selected_channel)
        i = self.edge.findData(p.edge_strategy)
        if i >= 0:
            self.edge.setCurrentIndex(i)

    def _working(self) -> Analysis:
        """Рабочая копия (НЕ меняет модель) для предпросмотра."""
        work_params = replace(
            self.analysis.params,
            start_freq=self.start.value(), end_freq=self.end.value(),
            record_time=self.record.value(), cut_second=self.cut.value(),
            gain=self.gain.value(), fixedlevel=self.level.value(),
            normalize=self.normalize.isChecked(), edge_strategy=self.edge.currentData(),
        )
        return Analysis(params=work_params, channels=self.analysis.channels,
                        signal_start_channel=self.signal_start.currentText(),
                        selected_channel=self.selected.currentText())

    def _on_normalize(self, on: bool) -> None:
        self.normalize.setText(f"Максимум → 1: {'вкл' if on else 'выкл'}")
        self._preview()

    # ---- применение / сброс ------------------------------------------------
    def apply(self) -> None:
        p = self.analysis.params
        p.start_freq = self.start.value(); p.end_freq = self.end.value()
        p.record_time = self.record.value(); p.cut_second = self.cut.value()
        p.gain = self.gain.value(); p.fixedlevel = self.level.value()
        p.normalize = self.normalize.isChecked(); p.edge_strategy = self.edge.currentData()
        self.analysis.signal_start_channel = self.signal_start.currentText()
        self.analysis.selected_channel = self.selected.currentText()
        self.analysis.label = self.label_edit.text().strip()
        self.analysis.description = self.description_edit.toPlainText().strip()
        self.analysis.dirty = True
        self.changed.emit()
        self.apply_btn.setText("Применено ✓")

    def revert(self) -> None:
        self._load_from_model(); self._preview()
        self.apply_btn.setText("Применить")

    # ---- расчёт и отрисовка (на рабочей копии) -----------------------------
    def _preview(self) -> None:
        self.apply_btn.setText("Применить *")
        work = self._working()
        self.result = analyze(work)
        self._redraw(work)
        self._update_params(work)
        self._update_forecast()

    def _redraw(self, work: Analysis) -> None:
        for ax in (self.ax1, self.ax2, self.ax3):
            ax.clear()
        res = self.result
        # исходные + строб
        ymin, ymax = float("inf"), float("-inf")
        for name, s in res.series.items():
            self.ax1.plot(s.time, s.raw, label=name, linewidth=0.6)
            ymin = min(ymin, res.raw_min.get(name, 0.0))
            ymax = max(ymax, res.raw_max.get(name, 0.0))
        if ymin != float("inf"):
            self.ax1.add_patch(Rectangle((res.start_time, ymin), work.params.record_time,
                                         ymax - ymin, edgecolor="r", facecolor="r", alpha=0.18))
            self.ax1.axvline(res.start_time, color="r", linewidth=1)
            self.ax1.plot([], [], color="r", alpha=0.3, linewidth=8, label="Строб")
        # сглаженные
        for name, s in res.series.items():
            self.ax2.plot(s.time, s.smoothed, label=name, linewidth=0.8)
        # АЧХ + маркеры
        ch = work.selected_channel
        amp = res.amplitude.get(ch, np.array([]))
        if amp.size and res.freqs.size:
            self.ax3.plot(res.freqs, amp, color="red", label=ch)
            m = channel_metrics(res, ch, work.params.fixedlevel)
            if m:
                self.ax3.axvline(m["resonance_frequency"], color="green", linestyle="--",
                                 label=f"Резонанс {m['resonance_frequency']:.0f} Гц")
                self.ax3.axhline(m["max_amplitude"] * 0.707, color="blue", linestyle="--",
                                 label="0.707")
                self.ax3.axhline(work.params.fixedlevel, color="orange", linestyle="--",
                                 label=f"Уровень {work.params.fixedlevel:.2f}")

        for ax, title, xl, yl in (
            (self.ax1, "Исходные сигналы", "Время, с", "Напряжение, В"),
            (self.ax2, "Сглаженные", "Время, с", "Напряжение, В"),
            (self.ax3, "АЧХ (линейная, с усилением)", "Частота, Гц", "Амплитуда"),
        ):
            ax.set_title(title); ax.set_xlabel(xl); ax.set_ylabel(yl)
            ax.grid(True, alpha=0.3); ax.legend(loc="upper right", fontsize="small")
        self.figure.tight_layout(pad=1.5)
        self.canvas.draw_idle()

    def _update_params(self, work: Analysis) -> None:
        ch = work.selected_channel
        m = channel_metrics(self.result, ch, work.params.fixedlevel)
        if not m:
            self.params_view.setPlainText("Параметры не рассчитаны"); return
        lo7, hi7 = m["bandwidth_707_range"]; lof, hif = m["bandwidth_fixed_range"]
        self.params_view.setPlainText(
            f"Канал {ch}:\n\n"
            f"Макс. амплитуда: {m['max_amplitude'] * 2:.2f} В\n"
            f"Резонансная частота: {m['resonance_frequency']:.2f} Гц\n"
            f"Полоса (0.707): {m['bandwidth_707']:.2f} Гц\n  ({lo7:.2f}…{hi7:.2f} Гц)\n"
            f"Полоса (уровень {work.params.fixedlevel:.2f}): {m['bandwidth_fixed']:.2f} Гц\n"
            f"  ({lof:.2f}…{hif:.2f} Гц)\n"
            f"Добротность Q: {m['q_factor']:.2f}"
        )

    def _update_forecast(self) -> None:
        ch = self.selected.currentText()
        m = channel_metrics(self.result, ch, self.level.value())
        if not m:
            self.forecast_view.setPlainText("Прогноз не рассчитан"); return
        lo, hi = frequency_forecast(m["resonance_frequency"], self.criterion.value(),
                                    self.record.value())
        self.forecast_view.setPlainText(
            f"Нижняя граница: {lo:.2f} Гц\nВерхняя граница: {hi:.2f} Гц\n"
            f"Центр: {(lo + hi) / 2:.2f} Гц"
        )

    def closeEvent(self, event) -> None:
        self.closed.emit(self)
        super().closeEvent(event)
