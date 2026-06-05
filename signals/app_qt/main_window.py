"""
signals.app_qt.main_window
=========================

Главное окно, приведённое к логике оригинала (см. ORIGINAL_DESIGN.md):

* дерево «Предмет → измерение» со столбцами: Выбор · Код предмета · Файл/измерение ·
  Графики (КНОПКА в каждой строке) · динамические столбцы из процессора;
* имя предмета и метка измерения меняются прямо в ячейке (двойной клик);
* фильтр — свойство столбца: двойной клик по заголовку открывает фильтр столбца;
* настройка столбцов — диалог «Доступные ↔ Текущие» (значения из процессора);
* приборы — отдельные группы генератор/осциллограф/управление, цветные кнопки;
* загрузка старого формата .analysis; сохранить всё / выбранные; перенос
  анализов между предметами (drag-drop и контекстное меню); темы; сохранение при выходе.
"""
from __future__ import annotations

import logging
import math
import tempfile
from copy import copy
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QCursor
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QDockWidget,
    QFileDialog, QFormLayout, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QToolTip, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..domain import Analysis, MeasurementParams, Project, Subject
from ..io import ProjectStore, parse_file
from ..runtime_ext import register_user_column
from ..services import (
    DEFAULT_COLUMN_KEYS, analyze_full, column_by_key, column_value, format_value,
)
from . import theme
from .column_dialog import ColumnConfigDialog
from .filter_dialog import ColumnFilterDialog, SubjectFilterDialog
from .graph_window import GraphWindow
from .instrument_panel import InstrumentPanel
from .log_widget import LogWidget
from .summary_dialog import SummaryDialog
from .tree_widget import SignalsTree

logger = logging.getLogger("signals.app")
COL_CHECK, COL_CODE, COL_FILE, COL_GRAPH = 0, 1, 2, 3
DYN_START = 4
ROLE = Qt.ItemDataRole.UserRole


def parse_filename(stem: str):
    parts = stem.split("_")
    if len(parts) >= 4:
        try:
            start, end, rec = float(parts[-3]), float(parts[-2]), float(parts[-1])
            return "_".join(parts[:-3]), MeasurementParams(
                start_freq=start, end_freq=end, record_time=rec)
        except ValueError:
            pass
    return stem, None


class FormulaColumnDialog(QDialog):
    """Один диалог для добавления пользовательского столбца-формулы."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Новый столбец (формула)"); self.setModal(True)
        form = QFormLayout(self)
        self.key = QLineEdit(); self.label = QLineEdit(); self.expr = QLineEdit()
        self.expr.setPlaceholderText("например: max(amp)")
        form.addRow("Ключ (латиницей):", self.key)
        form.addRow("Название:", self.label)
        form.addRow("Формула (amp, freqs):", self.expr)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject)
        form.addRow(box)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("signals — анализатор АЧХ")
        self.resize(1340, 800)
        self.project = Project()
        self.store = ProjectStore()
        self.project_dir: Path | None = None
        self._cache: dict[str, tuple] = {}
        self._thumbs: dict[str, str] = {}
        self._windows: list[GraphWindow] = []
        self._loading = False
        saved_keys = theme.load_settings().get("columns") or DEFAULT_COLUMN_KEYS
        self.dynamic_columns = [c for c in (column_by_key(k) for k in saved_keys) if c] \
            or [c for c in (column_by_key(k) for k in DEFAULT_COLUMN_KEYS) if c]
        self._filters: dict[str, tuple] = {}     # col_key -> (op, v1, v2)
        self._subject_text = ""
        self._file_text = ""
        self._subj_counter = 0

        self.tree = SignalsTree()
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemDoubleClicked.connect(self._maybe_edit)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.header().sectionDoubleClicked.connect(self._on_header_double_clicked)
        self.tree.analysis_dropped.connect(self._on_drop)
        self.tree.setMouseTracking(True)
        self.tree.itemEntered.connect(self._on_item_entered)
        self.setCentralWidget(self.tree)

        self._build_menu()
        self._build_toolbar()
        self._build_docks()
        self.refresh()

        self.autosave = QTimer(self); self.autosave.setInterval(30_000)
        self.autosave.timeout.connect(self._autosave); self.autosave.start()

    def _icon(self, std):
        return self.style().standardIcon(std)

    # ---- меню «Вид» --------------------------------------------------------
    def _build_menu(self) -> None:
        view = self.menuBar().addMenu("Вид")
        style_menu = view.addMenu("Стиль интерфейса")
        nice = {"fusion": "Fusion (рекомендуется)", "windowsvista": "Windows 10",
                "windows11": "Windows 11", "windows": "Windows (классический)"}
        for s in theme.list_styles():
            title = nice.get(s.lower(), s)
            a = QAction(title, self)
            a.triggered.connect(lambda _=False, n=s: self._set_style(n)); style_menu.addAction(a)
        view.addSeparator()
        for name in theme.list_themes():
            a = QAction(f"Тема: {name}", self)
            a.triggered.connect(lambda _=False, n=name: self._set_theme(n)); view.addAction(a)
        view.addSeparator()
        a = QAction("Загрузить свой стиль (.qss)…", self)
        a.triggered.connect(self._load_custom_theme); view.addAction(a)

        tools = self.menuBar().addMenu("Приборы")
        a = QAction("Указать папку с DLL Hantek…", self)
        a.triggered.connect(self._set_hantek_dll_dir); tools.addAction(a)
        a = QAction("Обновить список приборов", self)
        a.triggered.connect(lambda: self.instruments.detect()); tools.addAction(a)

        upd = self.menuBar().addMenu("Обновление")
        a = QAction("Проверить обновления (GitHub)…", self)
        a.triggered.connect(self._open_update_dialog); upd.addAction(a)

    def _open_update_dialog(self) -> None:
        from .update_dialog import UpdateDialog
        UpdateDialog(self).exec()

    def _set_hantek_dll_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Папка с DLL Hantek (HT*.dll)")
        if d:
            theme.save_settings({"hantek_dll_dir": d})
            self._log(f"Папка DLL Hantek: {d} — выполняю повторный поиск приборов")
            self.instruments.detect()

    def _set_style(self, name: str) -> None:
        app = QApplication.instance()
        theme.apply_style(app, name)
        theme.apply_theme(app, theme.load_settings().get("theme", "Тёмная"))
        theme.save_settings({"style": name}); self._log(f"Стиль интерфейса: {name}")

    def _set_theme(self, name: str) -> None:
        theme.apply_theme(QApplication.instance(), name)
        theme.save_settings({"theme": name}); self._log(f"Тема: {name}")

    def _load_custom_theme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Стиль", "", "QSS (*.qss)")
        if path:
            theme.apply_theme(QApplication.instance(), path)
            theme.save_settings({"theme": path}); self._log(f"Стиль: {path}")

    # ---- тулбар ------------------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Главная"); tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        S = self.style().StandardPixmap

        def act(icon, text, tip, slot):
            a = tb.addAction(self._icon(icon), text); a.setToolTip(tip)
            a.triggered.connect(slot); return a

        act(S.SP_FileDialogNewFolder, "Добавить предмет", "Добавить новый предмет", self.add_subject)
        act(S.SP_DialogOpenButton, "Добавить измерения",
            "Открыть CSV/Excel в выбранный предмет (или по имени файла)", self.load_files)
        act(S.SP_DirOpenIcon, "Открыть проект/анализ",
            "Открыть .sigproj, старый .analysis или папку проекта", self.open_project)
        act(S.SP_DialogSaveButton, "Сохранить всё", "Сохранить весь проект", self.save_project)
        act(S.SP_DialogSaveButton, "Сохранить выбранные",
            "Сохранить только отмеченные измерения в файл", self.save_selected)
        tb.addSeparator()
        act(S.SP_FileDialogListView, "Настройки столбцов", "Выбрать отображаемые столбцы",
            self.configure_columns)
        act(S.SP_DialogResetButton, "Отключить фильтры", "Сбросить все фильтры", self.clear_filters)
        act(S.SP_FileDialogDetailedView, "Добавить столбец", "Пользовательский столбец-формула",
            self.add_column)
        tb.addSeparator()
        act(S.SP_FileDialogInfoView, "Сводка", "Сводный график по отмеченным", self.open_summary)
        act(S.SP_DriveHDIcon, "Экспорт .sigproj", "Упаковать проект в один файл", self.export_archive)

    def _build_docks(self) -> None:
        self.instruments = InstrumentPanel()
        self.instruments.captured.connect(self._on_captured)
        self.instruments.log.connect(self._log)
        dock_i = QDockWidget("Управление приборами", self); dock_i.setObjectName("dock_instruments")
        dock_i.setWidget(self.instruments)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock_i)

        self.logw = LogWidget()
        dock_l = QDockWidget("Журнал", self); dock_l.setObjectName("dock_log")
        dock_l.setWidget(self.logw)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock_l)
        # журнал ПОД приборами (вертикально), а не сбоку
        self.splitDockWidget(dock_i, dock_l, Qt.Orientation.Vertical)

    def _log(self, text: str) -> None:
        self.logw.append_line(text)

    # ---- дерево ------------------------------------------------------------
    def refresh(self) -> None:
        self._loading = True
        expanded = self._expanded_codes()
        self.tree.clear()
        headers = ["Выбор", "Код предмета", "Файл / измерение", "Графики"] + \
                  [c["title"] for c in self.dynamic_columns]
        self.tree.setColumnCount(len(headers))
        self.tree.setHeaderLabels(headers)

        for subject in self.project.subjects:
            if self._subject_text and self._subject_text.lower() not in \
                    f"{subject.code} {subject.name}".lower():
                continue
            s_item = QTreeWidgetItem(); s_item.setText(COL_CODE, subject.name)
            s_item.setFlags(s_item.flags() | Qt.ItemFlag.ItemIsEditable)
            s_item.setData(0, ROLE, ("subject", subject, None))
            self.tree.addTopLevelItem(s_item)
            for analysis in subject.analyses:
                title = analysis.label or (analysis.source_file.name
                                           if analysis.source_file else analysis.id)
                if self._file_text and self._file_text.lower() not in title.lower():
                    continue
                result = self.result_for(analysis)
                if self._filters and not self._passes_filters(analysis, result):
                    continue
                a_item = QTreeWidgetItem()
                a_item.setFlags(a_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                                | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
                a_item.setCheckState(COL_CHECK, Qt.CheckState.Unchecked)
                a_item.setText(COL_CODE, analysis.description)      # короткое описание
                a_item.setText(COL_FILE, title)
                if analysis.description:
                    a_item.setToolTip(COL_CODE, analysis.description)
                a_item.setData(0, ROLE, ("analysis", subject, analysis))
                for i, col in enumerate(self.dynamic_columns, start=DYN_START):
                    a_item.setText(i, format_value(column_value(analysis, result, col)))
                s_item.addChild(a_item)
                btn = QPushButton("Открыть графики")
                btn.clicked.connect(lambda _=False, a=analysis: self._open_graph(a))
                self.tree.setItemWidget(a_item, COL_GRAPH, btn)
            s_item.setFlags(s_item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
            if subject.code in expanded:
                s_item.setExpanded(True)
        self.tree.resizeColumnToContents(COL_GRAPH)
        self._loading = False

    def result_for(self, analysis: Analysis):
        p = analysis.params
        sig = (p.start_freq, p.end_freq, p.record_time, p.cut_second, p.gain,
               p.fixedlevel, p.normalize, p.edge_strategy,
               analysis.signal_start_channel, analysis.selected_channel,
               tuple(analysis.channels))
        cached = self._cache.get(analysis.id)
        if cached and cached[0] == sig:
            return cached[1]
        result = analyze_full(analysis)
        self._cache[analysis.id] = (sig, result)
        return result

    def _expanded_codes(self) -> set[str]:
        codes = set()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            data = it.data(0, ROLE)
            if it.isExpanded() and data:
                codes.add(data[1].code)
        return codes

    def _selected(self):
        item = self.tree.currentItem()
        return (item, item.data(0, ROLE)) if item else (None, None)

    def _selected_subject(self) -> Subject | None:
        _, data = self._selected()
        return data[1] if data else None

    def _checked_analyses(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            s_item = self.tree.topLevelItem(i)
            for j in range(s_item.childCount()):
                a_item = s_item.child(j)
                if a_item.checkState(COL_CHECK) == Qt.CheckState.Checked:
                    out.append(a_item.data(0, ROLE))
        return out

    # ---- фильтры (свойство столбца) ----------------------------------------
    def _on_header_double_clicked(self, index: int) -> None:
        if index == COL_CODE:
            dlg = SubjectFilterDialog(self._subject_text, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._subject_text = dlg.text(); self.refresh()
        elif index == COL_FILE:
            dlg = SubjectFilterDialog(self._file_text, self)
            dlg.setWindowTitle("Фильтр по имени измерения")
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._file_text = dlg.text(); self.refresh()
        elif index >= DYN_START:
            col = self.dynamic_columns[index - DYN_START]
            dlg = ColumnFilterDialog(col["title"], self._filters.get(col["key"]), self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                f = dlg.result_filter()
                if f is None:
                    self._filters.pop(col["key"], None)
                else:
                    self._filters[col["key"]] = f
                self.refresh()
                self._log(f"Фильтр: {col['title']} {f[0] if f else 'снят'}")

    def clear_filters(self) -> None:
        self._filters.clear(); self._subject_text = ""; self._file_text = ""
        self.refresh(); self._log("Фильтры сброшены")

    def _passes_filters(self, analysis: Analysis, result) -> bool:
        for key, (op, v1, v2) in self._filters.items():
            col = column_by_key(key)
            if not col:
                continue
            v = column_value(analysis, result, col)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return False
            if op == "Равно" and abs(v - v1) >= 1e-6:
                return False
            if op == "Больше" and not v > v1:
                return False
            if op == "Меньше" and not v < v1:
                return False
            if op == "Между" and v2 is not None and not (min(v1, v2) <= v <= max(v1, v2)):
                return False
        return True

    # ---- столбцы -----------------------------------------------------------
    def configure_columns(self) -> None:
        dlg = ColumnConfigDialog(self.dynamic_columns, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.dynamic_columns = dlg.get_columns()
            theme.save_settings({"columns": [c["key"] for c in self.dynamic_columns]})
            self.refresh()

    def add_column(self) -> None:
        dlg = FormulaColumnDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        key = dlg.key.text().strip(); label = dlg.label.text().strip(); expr = dlg.expr.text().strip()
        if not key or not expr:
            return
        try:
            register_user_column(key, label=label or key, expr=expr)
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.warning(self, "Ошибка формулы", str(exc)); return
        col = column_by_key(key)
        if col:
            self.dynamic_columns.append(col)
            theme.save_settings({"columns": [c["key"] for c in self.dynamic_columns]})
        self._cache.clear(); self.refresh()
        self._log(f"Добавлен столбец «{label or key}» = {expr}")

    # ---- объекты / файлы ---------------------------------------------------
    def add_subject(self) -> None:
        self._subj_counter += 1
        code = f"AN{self._subj_counter}"
        while self.project.subject(code) is not None:
            self._subj_counter += 1; code = f"AN{self._subj_counter}"
        self.project.subjects.append(Subject(code=code, name=code))
        self.refresh()
        # сразу даём переименовать
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, ROLE)[1].code == code:
                self.tree.setCurrentItem(it); self.tree.editItem(it, COL_CODE); break
        self._log(f"Добавлен предмет «{code}» — переименуйте при необходимости")

    def _subject_by_code(self, code: str) -> Subject:
        s = self.project.subject(code)
        if s is None:
            s = Subject(code=code, name=code); self.project.subjects.append(s)
        return s

    def load_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Добавить измерения", "",
                                                "Данные (*.csv *.xlsx *.xls)")
        target = self._selected_subject()
        for path in paths:
            try:
                channels = parse_file(path)
            except Exception as exc:                   # noqa: BLE001
                self._log(f"Не удалось открыть {Path(path).name}: {exc}"); continue
            code, params = parse_filename(Path(path).stem)
            subject = target or self._subject_by_code(code)
            subject.analyses.append(Analysis(params=params or MeasurementParams(),
                                             channels=channels, source_file=Path(path),
                                             label=Path(path).stem))
            self._log(f"Загружено: {Path(path).name} → «{subject.code}»")
        self.refresh()

    def _on_captured(self, channels: dict, cfg) -> None:
        if cfg is not None:
            params = MeasurementParams(start_freq=cfg.start_freq, end_freq=cfg.end_freq,
                                       record_time=cfg.sweep_time, amplitude=cfg.amplitude,
                                       offset=cfg.offset, sweep_time=cfg.sweep_time)
            label = f"Свип {cfg.start_freq:.0f}–{cfg.end_freq:.0f} Гц"
        else:
            params = MeasurementParams(); label = "Чтение осциллографа"
        subject = self._selected_subject() or self._subject_by_code("Измерения")
        subject.analyses.append(Analysis(params=params, channels=channels, label=label))
        self._log(f"Измерение: {label} ({len(channels)} каналов) → «{subject.code}»")
        self.refresh()

    # ---- быстрый предпросмотр (наведение) ----------------------------------
    def _thumbnail(self, analysis: Analysis) -> str | None:
        """Сгенерировать (с кэшем) мини-график исходных сигналов → путь к PNG."""
        if analysis.id in self._thumbs:
            return self._thumbs[analysis.id]
        try:
            import os
            import tempfile
            import numpy as np
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            from matplotlib.figure import Figure
            fig = Figure(figsize=(2.9, 1.7), dpi=100)
            ax = fig.add_subplot(111)
            for name, ch in analysis.channels.items():
                t, a = ch.time, ch.amplitude
                if len(a) > 600:
                    idx = np.linspace(0, len(a) - 1, 600).astype(int); t, a = t[idx], a[idx]
                ax.plot(t, a, linewidth=0.7, label=name)
            ax.set_title("Исходные сигналы", fontsize=7)
            ax.tick_params(labelsize=6)
            if analysis.channels:
                ax.legend(fontsize=5, loc="upper right")
            try:                                   # наложить строб (интервал анализа)
                result = self.result_for(analysis)
                t0 = float(result.start_time)
                t1 = t0 + float(analysis.params.record_time)
                ax.axvspan(t0, t1, color="red", alpha=0.15)
                ax.axvline(t0, color="red", linewidth=0.8)
            except Exception:                      # noqa: BLE001
                pass
            fig.tight_layout(pad=0.3)
            path = os.path.join(tempfile.gettempdir(), f"sig_thumb_{analysis.id}.png")
            FigureCanvasAgg(fig).print_png(path)
            self._thumbs[analysis.id] = path
            return path
        except Exception:                              # noqa: BLE001
            return None

    def _on_item_entered(self, item, col) -> None:
        data = item.data(0, ROLE)
        if not data or data[0] != "analysis":
            return
        path = self._thumbnail(data[2])
        if not path:
            return
        a = data[2]
        html = f"<b>{a.label or a.id}</b><br><img src='{path.replace(chr(92), '/')}'>"
        if a.description:
            html += f"<br>{a.description}"
        item.setToolTip(COL_FILE, html)
        QToolTip.showText(QCursor.pos(), html, self.tree)

    # ---- графики -----------------------------------------------------------
    def _open_graph(self, analysis: Analysis) -> None:
        win = GraphWindow(analysis)
        win.changed.connect(lambda a=analysis: (self._cache.pop(a.id, None),
                                                self._thumbs.pop(a.id, None), self.refresh()))
        win.closed.connect(self._on_window_closed)
        self._windows.append(win); win.show()

    def _on_window_closed(self, win) -> None:
        if win in self._windows:
            self._windows.remove(win)

    def open_summary(self) -> None:
        checked = self._checked_analyses()
        if not checked:
            QMessageBox.information(self, "Сводка", "Отметьте галочками измерения в дереве.")
            return
        selected = [(f"{d[1].name}/{d[2].label or d[2].id}", d[2]) for d in checked]
        SummaryDialog(selected, self).exec()

    # ---- переименование / перемещение / удаление --------------------------
    def _maybe_edit(self, item, col) -> None:
        data = item.data(0, ROLE)
        if not data:
            return
        if data[0] == "subject" and col == COL_CODE:
            self.tree.editItem(item, COL_CODE)              # переименование предмета
        elif data[0] == "analysis":
            if col == COL_CODE:
                self.tree.editItem(item, COL_CODE)          # короткое описание
            else:
                self._open_graph(data[2])                   # двойной клик — графики

    def _on_item_changed(self, item, col) -> None:
        if self._loading:
            return
        data = item.data(0, ROLE)
        if not data:
            return
        kind, subject, analysis = data
        if kind == "subject" and col == COL_CODE:
            text = item.text(COL_CODE).strip()
            if text and text != subject.name:
                subject.name = text
        elif kind == "analysis" and col == COL_CODE:
            text = item.text(COL_CODE).strip()
            if text != analysis.description:
                analysis.description = text; analysis.dirty = True
        elif kind == "analysis" and col == COL_FILE:
            text = item.text(COL_FILE).strip()
            current = analysis.label or (analysis.source_file.name
                                         if analysis.source_file else analysis.id)
            if text and text != current:
                analysis.label = text; analysis.dirty = True

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, ROLE)
        menu = QMenu(self)
        if data[0] == "analysis":
            menu.addAction("Открыть графики", lambda a=data[2]: self._open_graph(a))
            menu.addAction("Переименовать измерение", lambda it=item: self.tree.editItem(it, COL_FILE))
            menu.addAction("Изменить описание", lambda it=item: self.tree.editItem(it, COL_CODE))
            sub = menu.addMenu("Переместить в предмет")
            for s in self.project.subjects:
                if s is not data[1]:
                    sub.addAction(s.name, lambda _=False, s=s, d=data: self._move(d, s))
        else:
            menu.addAction("Переименовать предмет", lambda it=item: self.tree.editItem(it, COL_CODE))
        menu.addAction("Удалить", self.delete_selected)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_drop(self, data, target_subject) -> None:
        self._move(data, target_subject)

    def _move(self, data, target: Subject) -> None:
        _, subject, analysis = data
        if subject is target:
            return
        subject.analyses.remove(analysis); target.analyses.append(analysis)
        analysis.dirty = True; self.refresh()
        self._log(f"Анализ перемещён в «{target.code}»")

    def delete_selected(self) -> None:
        item, data = self._selected()
        if not data:
            return
        kind, subject, analysis = data
        if kind == "subject":
            self.project.subjects.remove(subject)
        else:
            subject.analyses.remove(analysis)
        self.refresh()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete and self.tree.hasFocus():
            self.delete_selected()
        else:
            super().keyPressEvent(event)

    # ---- сохранение / открытие --------------------------------------------
    def save_project(self) -> None:
        if self.project_dir is None:
            folder = QFileDialog.getExistingDirectory(self, "Папка проекта")
            if not folder:
                return
            self.project_dir = Path(folder)
            self.store.save(self.project, self.project_dir, full=True)
        else:
            self.store.save(self.project, self.project_dir)
        self._log(f"Проект сохранён: {self.project_dir}")

    def save_selected(self) -> None:
        checked = self._checked_analyses()
        if not checked:
            QMessageBox.information(self, "Сохранить выбранные",
                                    "Отметьте галочками нужные измерения."); return
        subset = Project(); by_code: dict[str, Subject] = {}
        for _, subject, analysis in checked:
            s = by_code.get(subject.code)
            if s is None:
                s = Subject(code=subject.code, name=subject.name)
                by_code[subject.code] = s; subset.subjects.append(s)
            clone = copy(analysis); clone.dirty = True; s.analyses.append(clone)
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить выбранные",
                                              "selected.sigproj", "Проект (*.sigproj)")
        if not path:
            return
        tmp = Path(tempfile.mkdtemp())
        self.store.save(subset, tmp, full=True); self.store.pack(tmp, path)
        self._log(f"Сохранены выбранные ({len(checked)}): {path}")

    def _autosave(self) -> None:
        if self.project_dir and self.project.dirty_analyses():
            self.store.save(self.project, self.project_dir)
            self._log("Автосохранение (только изменённые измерения)")

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть проект/анализ", "",
            "Проекты (*.sigproj *.analysis project.json);;Все файлы (*)")
        try:
            if path and path.endswith(".analysis"):
                self.project = self.store.load_legacy(path); self.project_dir = None
                self._log(f"Загружен старый формат: {path}")
            elif path and path.endswith(".sigproj"):
                folder = Path(path).with_suffix("")
                self.store.unpack(path, folder)
                self.project = self.store.load(folder); self.project_dir = folder
                self._log(f"Проект открыт: {folder}")
            elif path and Path(path).name == "project.json":
                folder = Path(path).parent                  # выбрали индекс внутри папки
                self.project = self.store.load(folder); self.project_dir = folder
                self._log(f"Проект открыт из папки: {folder}")
            else:
                folder = QFileDialog.getExistingDirectory(self, "Папка проекта")
                if not folder:
                    return
                self.project = self.store.load(Path(folder)); self.project_dir = Path(folder)
                self._log(f"Проект открыт: {folder}")
            self._cache.clear(); self.refresh()
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.warning(self, "Ошибка открытия", str(exc))

    def export_archive(self) -> None:
        if self.project_dir is None:
            self.save_project()
        if self.project_dir is None:
            return
        self.store.save(self.project, self.project_dir)
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт проекта", "project.sigproj",
                                              "Проект (*.sigproj)")
        if path:
            self.store.pack(self.project_dir, path); self._log(f"Экспортировано: {path}")

    # ---- выход -------------------------------------------------------------
    def closeEvent(self, event) -> None:
        reply = QMessageBox.question(
            self, "Выход", "Сохранить проект перед выходом?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Cancel:
            event.ignore(); return
        if reply == QMessageBox.StandardButton.Yes:
            self.save_project()
        for win in list(self._windows):
            win.close()
        event.accept()
