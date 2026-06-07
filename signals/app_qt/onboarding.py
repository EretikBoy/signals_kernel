"""
signals.app_qt.onboarding
=========================

Обучение при первом запуске — два тура на выбор:

* базовый ведёт по реальному рабочему сценарию (калибровка керамической антенны
  на вилке К-3): от подготовки оснастки до вывода о годности по амплитуде,
  подсвечивая нужные поля и кнопки по шагам;
* продвинутый — беглый обзор всего остального (свип-АЧХ, простое чтение
  осциллографа, периодическая запись, обработка и экспорт любых осциллограмм).

Если на шаге есть картинка или видео, в подсказке сразу видна её миниатюра —
кликнул и открылась крупно. Файлы тур берёт из ~/.signals/onboarding, а если их
там нет — из встроенной onboarding_media; и если файла всё равно нет, прямо
говорит, куда его положить.

Подсветка реализована как прозрачный для мыши слой поверх содержимого главного
окна (а не отдельное окно — так подсказка не теряет фокус и естественно
перекрывается диалогами вроде окна графиков, возвращаясь обратно при их закрытии).
В месте, которое нужно показать, в этом слое — «окно»-прожектор: затемнение там
не рисуется, и виджет под ним остаётся кликабельным как обычно.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap, QRegion
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from . import theme

MEDIA_DIRS = [Path.home() / ".signals" / "onboarding",
              Path(__file__).parent / "onboarding_media"]
VIDEO_EXT = {".mp4", ".avi", ".mov", ".webm", ".mkv"}


def resolve_media(name: str | None) -> Path | None:
    if not name:
        return None
    for d in MEDIA_DIRS:
        p = d / name
        if p.exists():
            return p
    return None


def should_show_onboarding() -> bool:
    return not theme.load_settings().get("onboarding_done", False)


def mark_done() -> None:
    theme.save_settings({"onboarding_done": True})


# ---- геометрия подсветки ---------------------------------------------------
def top_menu_rect(window, title: str):
    """Прямоугольник пункта верхнего меню по подписи (в координатах окна)."""
    mb = window.menuBar()
    for act in mb.actions():
        if act.text() == title:
            r = mb.actionGeometry(act)
            if not r.isNull():
                return QRect(mb.mapTo(window, r.topLeft()), r.size())
    return None


def help_menu_rect(window):
    return top_menu_rect(window, "Справка")


def union_rect(window, widgets):
    """Объединённый прямоугольник нескольких виджетов (в координатах окна)."""
    rects = []
    for w in widgets:
        if w is not None and w.isVisible():
            rects.append(QRect(w.mapTo(window, QPoint(0, 0)), w.size()))
    if not rects:
        return None
    out = rects[0]
    for r in rects[1:]:
        out = out.united(r)
    return out


# ---------------------------------------------------------------------------
class OnboardingStep:
    def __init__(self, title: str, text: str | Callable[[], str], *,
                 target: Callable[[], QWidget | None] | None = None,
                 target_rect: Callable[[], QRect | None] | None = None,
                 media: str | None = None,
                 advance_signal: Callable[[], Any] | None = None,
                 advance_when: Callable[[], bool] | None = None,
                 on_enter: Callable[[], Any] | None = None) -> None:
        self.title = title
        self.text = text                              # str ИЛИ callable → str (реакция на состояние)
        self.target = target
        self.target_rect = target_rect                # callable → QRect в координатах окна
        self.media = media
        self.advance_signal = advance_signal
        self.advance_when = advance_when              # callable → bool: переходить ли по сигналу
        self.on_enter = on_enter

    def widget(self) -> QWidget | None:
        try:
            w = self.target() if callable(self.target) else self.target
        except Exception:                              # noqa: BLE001
            return None
        return w if (w is not None and w.isVisible()) else None


class _ClickLabel(QLabel):
    def __init__(self, on_click) -> None:
        super().__init__()
        self._cb = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border:1px solid gray;border-radius:6px;padding:2px;")

    def mousePressEvent(self, ev) -> None:              # noqa: N802
        if self._cb:
            self._cb()


# ---------------------------------------------------------------------------
class MediaPopup(QFrame):
    """Крупный показ изображения/видео шага (дочерний виджет поверх главного окна)."""
    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self.setObjectName("ob_media")
        self._owner = owner
        self._player = None
        base = owner.palette().base().color().name()
        bd = owner.palette().highlight().color().name()
        self.setStyleSheet(f"QFrame#ob_media{{background:{base};border:2px solid {bd};"
                           "border-radius:10px;}")
        self._lay = QVBoxLayout(self)
        self._title = QLabel(""); self._title.setStyleSheet("font-weight:bold;")
        self._lay.addWidget(self._title)
        self._body = QLabel("")
        self._body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body.setWordWrap(True)
        self._lay.addWidget(self._body, 1)
        close = QPushButton("Закрыть"); close.clicked.connect(self.hide)
        self._lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.hide()

    def show_media(self, name: str | None, caption: str = "") -> None:
        self._stop()
        self._title.setText(caption or "Иллюстрация")
        # размер под окно (но не больше 720×520)
        ow, oh = self._owner.width(), self._owner.height()
        w = min(720, max(420, ow - 80)); h = min(520, max(300, oh - 120))
        self._body.setMinimumSize(w - 40, h - 90)
        path = resolve_media(name)
        if path is None:
            dirs = "\n".join(str(d / (name or "")) for d in MEDIA_DIRS)
            self._body.setPixmap(QPixmap())
            self._body.setText("Файл не найден. Положите изображение или видео сюда:\n\n" + dirs)
        elif path.suffix.lower() in VIDEO_EXT:
            self._play_video(path)
        else:
            pm = QPixmap(str(path))
            if pm.isNull():
                self._body.setText(f"Не удалось открыть {path.name}")
            else:
                self._body.setText("")
                self._body.setPixmap(pm.scaled(w - 40, h - 90, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        self.adjustSize()
        self.move(max(8, (ow - self.width()) // 2), max(8, (oh - self.height()) // 2))
        self.show(); self.raise_()

    def _play_video(self, path: Path) -> None:
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PyQt6.QtMultimediaWidgets import QVideoWidget
        except Exception:                              # noqa: BLE001
            self._body.setText("Видео недоступно (нет QtMultimedia). Файл:\n" + str(path))
            return
        vw = QVideoWidget(self); vw.setMinimumSize(self._body.minimumWidth(), self._body.minimumHeight())
        self._body.hide(); self._lay.insertWidget(1, vw, 1); self._video = vw
        self._player = QMediaPlayer(self); self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio); self._player.setVideoOutput(vw)
        self._player.setSource(QUrl.fromLocalFile(str(path))); self._player.play()

    def _stop(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:                          # noqa: BLE001
                pass
            self._player = None
        v = getattr(self, "_video", None)
        if v is not None:
            v.setParent(None); self._video = None; self._body.show()

    def hide(self) -> None:                            # noqa: A003
        self._stop(); super().hide()


# ---------------------------------------------------------------------------
class OnboardingOverlay(QWidget):
    """Подсветка обучения — дочерний слой главного окна.

    Слой «сквозной» для мыши (`WA_TransparentForMouseEvents`) — он ничего не
    перехватывает, так что любую кнопку приложения можно нажать в любой момент,
    как будто подсветки и нет вовсе. Подсказка и
    медиа — тоже дочерние виджеты, поэтому не сереют, не теряют фокус и естественно
    скрываются под окном графиков/диалогом, возвращаясь при их закрытии.
    """
    def __init__(self, window: QWidget, steps: list[OnboardingStep], title: str,
                 start_index: int = 0) -> None:
        super().__init__(window)
        self.window_ = window
        self.steps = steps
        self.i = 0
        self._spot = QRect()
        self._conn = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(window.rect())
        window.installEventFilter(self)
        self._build_bubble(title)
        self.media = MediaPopup(window)
        self.show(); self.bubble.show(); self._raise_ui()
        self.show_step(start_index)

    def _raise_ui(self) -> None:
        self.raise_(); self.bubble.raise_()            # подсказка всегда выше затемнения

    def _build_bubble(self, title: str) -> None:
        self.bubble = QFrame(self.window_); self.bubble.setObjectName("ob_bubble")
        base = self.window_.palette().base().color().name()
        bd = self.window_.palette().highlight().color().name()
        self.bubble.setStyleSheet(
            f"QFrame#ob_bubble{{background:{base};border:2px solid {bd};border-radius:12px;}}")
        self.bubble.setMaximumWidth(460)
        lay = QVBoxLayout(self.bubble)
        self.counter = QLabel(""); self.counter.setStyleSheet("color:gray;font-size:11px;")
        lay.addWidget(self.counter)
        self.tour_title = QLabel(title)
        self.step_title = QLabel(""); self.step_title.setWordWrap(True)
        self.step_title.setStyleSheet("font-size:15px;font-weight:bold;")
        lay.addWidget(self.step_title)
        self.step_text = QLabel(""); self.step_text.setWordWrap(True)
        self.step_text.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.step_text)
        self.thumb = _ClickLabel(self._open_media_full)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter); self.thumb.setMaximumWidth(440)
        lay.addWidget(self.thumb)
        row = QHBoxLayout(); lay.addLayout(row)
        self.skip_btn = QPushButton("Пропустить обучение"); self.skip_btn.clicked.connect(self.finish)
        row.addWidget(self.skip_btn); row.addStretch(1)
        self.back_btn = QPushButton("Назад"); self.back_btn.clicked.connect(self.prev)
        row.addWidget(self.back_btn)
        self.next_btn = QPushButton("Далее ▶"); self.next_btn.clicked.connect(self.next)
        row.addWidget(self.next_btn)

    # ---- навигация ---------------------------------------------------------
    def show_step(self, index: int) -> None:
        self._disconnect()
        self.media.hide()
        self.i = max(0, min(index, len(self.steps) - 1))
        step = self.steps[self.i]
        if step.on_enter:
            try:
                step.on_enter()
            except Exception:                          # noqa: BLE001
                pass
        self.counter.setText(f"{self.tour_title.text()} · шаг {self.i + 1} из {len(self.steps)}")
        self.step_title.setText(step.title)
        try:
            self.step_text.setText(step.text() if callable(step.text) else step.text)
        except Exception:                              # noqa: BLE001
            self.step_text.setText("")
        self._set_thumb(step)
        self.back_btn.setEnabled(self.i > 0)
        self.next_btn.setText("Готово ✓" if self.i == len(self.steps) - 1 else "Далее ▶")

        rect = None
        if step.target_rect:
            try:
                rect = step.target_rect()
            except Exception:                          # noqa: BLE001
                rect = None
        if rect is None:
            w = step.widget()
            if w is not None:
                rect = QRect(w.mapTo(self.window_, QPoint(0, 0)), w.size())
        self._spot = rect.adjusted(-6, -6, 6, 6) if (rect is not None and rect.isValid()) \
            else QRect()

        if step.advance_signal:
            try:
                sig = step.advance_signal()
                if sig is not None:
                    sig.connect(self._auto_next); self._conn = sig
            except Exception:                          # noqa: BLE001
                self._conn = None

        self._place_bubble(); self._update_mask(); self._raise_ui(); self.update()

    def _set_thumb(self, step: OnboardingStep) -> None:
        if not step.media:
            self.thumb.hide(); return
        path = resolve_media(step.media)
        if path is None:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("🖼 нет файла — нажмите, чтобы узнать куда положить")
        elif path.suffix.lower() in VIDEO_EXT:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("▶  Видео — нажмите, чтобы открыть")
        else:
            pm = QPixmap(str(path))
            if pm.isNull():
                self.thumb.setText(f"нажмите, чтобы открыть {path.name}")
            else:
                self.thumb.setText("")
                self.thumb.setPixmap(pm.scaled(220, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        self.thumb.setToolTip("Нажмите, чтобы увеличить"); self.thumb.show()

    def _open_media_full(self) -> None:
        step = self.steps[self.i]
        if step.media:
            self.media.show_media(step.media, step.title)

    def _auto_next(self, *args) -> None:
        step = self.steps[self.i]
        if step.advance_when is not None:
            try:
                ready = bool(step.advance_when())
            except Exception:                          # noqa: BLE001
                ready = True
            if not ready:                              # состояние ещё не достигнуто —
                QTimer.singleShot(50, lambda: self.show_step(self.i))   # обновим текст/подсветку
                return
        QTimer.singleShot(400, self.next)

    def next(self) -> None:                            # noqa: A003
        if self.i >= len(self.steps) - 1:
            self.finish(); return
        self.show_step(self.i + 1)

    def prev(self) -> None:
        if self.i > 0:
            self.show_step(self.i - 1)

    def finish(self) -> None:
        self._disconnect()
        mark_done()
        self.window_.removeEventFilter(self)
        self.media.hide(); self.bubble.hide(); self.hide()
        self.bubble.deleteLater(); self.media.deleteLater(); self.deleteLater()

    def _disconnect(self) -> None:
        if self._conn is not None:
            try:
                self._conn.disconnect(self._auto_next)
            except Exception:                          # noqa: BLE001
                pass
            self._conn = None

    # ---- геометрия / отрисовка --------------------------------------------
    def _place_bubble(self) -> None:
        self.bubble.adjustSize()
        bw, bh = self.bubble.width(), self.bubble.height()
        W, H = self.width(), self.height()
        if self._spot.isNull():
            x, y = (W - bw) // 2, (H - bh) // 2
        else:
            x = self._spot.center().x() - bw // 2
            y = self._spot.bottom() + 14
            if y + bh > H - 8:
                y = self._spot.top() - bh - 14
            if y < 8:
                y = min(self._spot.bottom() + 14, H - bh - 8)
        self.bubble.move(max(8, min(x, W - bw - 8)), max(8, min(y, H - bh - 8)))
        self.bubble.raise_()

    def _update_mask(self) -> None:
        # вырез под подсветкой: затемнение не рисуется там → виджет под ним яркий.
        region = QRegion(self.rect())
        if not self._spot.isNull():
            region = region.subtracted(QRegion(self._spot))
        self.setMask(region)

    def paintEvent(self, a0) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))            # затемнение поверх приложения
        if not self._spot.isNull():
            p.setPen(QPen(self.window_.palette().highlight().color(), 3))
            p.drawRoundedRect(self._spot.adjusted(-2, -2, 2, 2), 7, 7)
        p.end()

    def eventFilter(self, a0, a1) -> bool:
        if a0 is self.window_ and a1 is not None:
            t = a1.type()
            if t in (QEvent.Type.Resize, QEvent.Type.Move):
                self.setGeometry(self.window_.rect())
                self._place_bubble(); self._update_mask(); self._raise_ui(); self.update()
        return False


# ---------------------------------------------------------------------------
class WelcomeDialog(QDialog):
    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Добро пожаловать в signals")
        self.setModal(True)
        lay = QVBoxLayout(self)
        head = QLabel("Анализатор АЧХ резонансных систем")
        head.setStyleSheet("font-size:16px;font-weight:bold;"); lay.addWidget(head)
        intro = QLabel("С чего начать? Можно пройти короткое интерактивное обучение прямо "
                       "в программе — подсветим нужные кнопки и поля по шагам.")
        intro.setWordWrap(True); lay.addWidget(intro)
        b1 = QPushButton("🛠  Базовое: калибровка антенн (рекомендуется)")
        b1.clicked.connect(lambda: self._choose("basic")); lay.addWidget(b1)
        b2 = QPushButton("📚  Продвинутое: все возможности приложения")
        b2.clicked.connect(lambda: self._choose("advanced")); lay.addWidget(b2)
        b3 = QPushButton("Пропустить"); b3.clicked.connect(lambda: self._choose(None))
        lay.addWidget(b3)
        self.again = QCheckBox("Показать обучение при следующем запуске"); lay.addWidget(self.again)
        self.choice: str | None = None

    def _choose(self, what: str | None) -> None:
        self.choice = what
        if not self.again.isChecked():
            mark_done()
        self.accept()

    def run(self) -> None:
        self.exec()
        if self.choice == "basic":
            start_basic(self.window_)
        elif self.choice == "advanced":
            start_advanced(self.window_)


# ---- цели/действия ---------------------------------------------------------
def _first_subject_rect(window):
    tree = window.tree
    if tree.topLevelItemCount() == 0:
        return None
    item = tree.topLevelItem(0)
    r = tree.visualItemRect(item)
    if r.isNull() or r.width() == 0:
        return None
    return QRect(tree.viewport().mapTo(window, r.topLeft()), r.size())


def _collapse_first(window) -> None:
    tree = window.tree
    if tree.topLevelItemCount():
        tree.topLevelItem(0).setExpanded(False)


def _expand_all(window) -> None:
    tree = window.tree
    for i in range(tree.topLevelItemCount()):
        tree.topLevelItem(i).setExpanded(True)


def _first_graph_button(window) -> QWidget | None:
    from .main_window import COL_GRAPH
    _expand_all(window)                                # раскрыть, иначе кнопка скрыта
    tree = window.tree
    for i in range(tree.topLevelItemCount()):
        s = tree.topLevelItem(i)
        for j in range(s.childCount()):
            w = tree.itemWidget(s.child(j), COL_GRAPH)
            if w is not None:
                return w
    return None


def _add_verdict_column(window) -> None:
    from ..services import column_by_key
    col = column_by_key("antenna_verdict")
    if col and col["key"] not in [c["key"] for c in window.dynamic_columns]:
        window.dynamic_columns.append(col)
        theme.save_settings({"columns": [c["key"] for c in window.dynamic_columns]})
        window.refresh()


def _set_gen(window, **vals) -> None:
    p = getattr(window, "instruments", None)
    if p is None:
        return
    for attr, v in vals.items():
        w = getattr(p, attr, None)
        if w is not None:
            w.setValue(v)


def _osc_found(window) -> bool:
    try:
        return window.instruments.oscilloscope_combo.count() > 0
    except Exception:                                  # noqa: BLE001
        return False


def _device_text(window) -> str:
    if _osc_found(window):
        return ("Прибор найден и выбран в списках — можно продолжать. Если приборов "
                "несколько, выберите нужный осциллограф и генератор.")
    return ("Прибор не найден. Проверьте, воткнут ли он в USB и установлены ли драйверы "
            "(DLL Hantek в папке <b>hantek_dll</b>), затем нажмите подсвеченную кнопку "
            "«Обновить список приборов». В <b>Журнале</b> внизу видно, найден ли прибор "
            "и доступны ли DLL.")


def _device_target(window):
    p = getattr(window, "instruments", None)
    if p is None:
        return None
    if _osc_found(window):
        return union_rect(window, [getattr(p, "oscilloscope_combo", None),
                                   getattr(p, "generator_combo", None)])
    return union_rect(window, [getattr(p, "refresh_btn", None), getattr(p, "status", None)])


def build_basic_tour(window) -> list[OnboardingStep]:
    P = lambda name: (lambda: getattr(window.instruments, name, None))  # noqa: E731
    return [
        OnboardingStep(
            "Базовое обучение: калибровка антенн",
            "Проведём полный цикл проверки керамической антенны на калибровочной "
            "вилке. Дальше — по шагам; где есть иллюстрация, её миниатюра видна сразу "
            "(клик — открыть крупно).",
            media="intro.png"),
        OnboardingStep(
            "Прибор",
            "Нужен поддерживаемый прибор — как правило <b>Hantek</b> со встроенным "
            "генератором. Он будет и генератором, и осциллографом одновременно.",
            media="hantek.png"),
        OnboardingStep(
            "Калибровочная вилка К-3",
            "Понадобится калибровочная вилка (кодовое название <b>К-3</b>). В неё "
            "вкручивается испытуемая антенна.",
            media="fork_k3.png"),
        OnboardingStep(
            "Установка антенны",
            "Вкрутите керамическую антенну в вилку с моментом затяжки <b>3.5</b>. "
            "Не перетягивайте — момент важен для повторяемости измерений.",
            media="antenna_mount.png"),
        OnboardingStep(
            "Подключение переходной платы",
            "Подключите переходную плату к штекеру <b>строго по ключам</b> (по меткам "
            "ориентации), чтобы не перепутать контакты.",
            media="adapter.png"),
        OnboardingStep(
            "Прибор найден?",
            lambda: _device_text(window),
            target_rect=lambda: _device_target(window),
            advance_signal=lambda: getattr(window.instruments, "devices_changed", None),
            advance_when=lambda: _osc_found(window),
            media="devices_found.png"),
        OnboardingStep(
            "Диапазон частот генератора",
            "Задайте диапазон частот калибровочной вилки — обычно <b>2155–2185 Гц</b>. "
            "Эти значения уже стоят в подсвеченных полях, можно просто сверить и идти дальше.",
            target_rect=lambda: union_rect(
                window, [getattr(window.instruments, "start_freq", None),
                         getattr(window.instruments, "end_freq", None)]),
            on_enter=lambda: _set_gen(window, start_freq=2155.0, end_freq=2185.0)),
        OnboardingStep(
            "Амплитуда генератора",
            "Амплитуду сигнала генератора выставьте <b>1 В</b> (подставлено в "
            "подсвеченное поле).",
            target=P("amplitude"), on_enter=lambda: _set_gen(window, amplitude=1.0)),
        OnboardingStep(
            "Развёртка",
            "Время развёртки (длительность свипа) — <b>30 секунд</b>. За это время "
            "генератор плавно пройдёт весь диапазон частот.",
            target=P("sweep_time"), on_enter=lambda: _set_gen(window, sweep_time=30.0)),
        OnboardingStep(
            "Добавьте предмет",
            "Добавьте предмет в таблицу — это «папка» для измерения антенны. Имя можно "
            "задать своё или оставить присвоенное автоматически. Нажмите подсвеченную "
            "кнопку.",
            target=lambda: window.toolbar.widgetForAction(window.act_add_subject),
            advance_signal=lambda: window.act_add_subject.triggered, media="add_subject.png"),
        OnboardingStep(
            "Подготовка к замеру",
            "Убедитесь, что антенна подписана, а вилка с антенной <b>свободно висит в "
            "воздухе</b> (ничего не касается) — иначе исказится резонанс.",
            media="fork_hang.png"),
        OnboardingStep(
            "Запуск измерения",
            lambda: ("Нажмите подсвеченную кнопку «НАЧАТЬ ЗАПИСЬ» и <b>дождитесь "
                     "окончания</b> свипа (~30 с). По завершении обучение продолжится "
                     "само." if _osc_found(window) else
                     "⚠ Прибор сейчас не найден — без него запись не получится. "
                     "Вернитесь на шаг «Прибор найден?» и подключите прибор; когда он "
                     "появится в списках, нажмите «НАЧАТЬ ЗАПИСЬ»."),
            target=P("measure_btn"),
            advance_signal=lambda: window.instruments.captured, media="reference_signal.png"),
        OnboardingStep(
            "Разверните предмет",
            lambda: ("Измерение лежит <b>внутри</b> предмета. Нажмите на треугольник ▸ слева "
                     "от предмета (подсвечен), чтобы раскрыть его и увидеть измерения."
                     if window.tree.topLevelItemCount() else
                     "Сначала сделайте запись (предыдущий шаг) или добавьте предмет — "
                     "тогда его можно будет раскрыть."),
            target_rect=lambda: _first_subject_rect(window),
            on_enter=lambda: _collapse_first(window),
            advance_signal=lambda: window.tree.itemExpanded),
        OnboardingStep(
            "Просмотр записи",
            lambda: ("Теперь видно измерение. Нажмите «Открыть графики» (или дважды "
                     "кликните по строке), чтобы посмотреть запись."
                     if _first_graph_button(window) is not None else
                     "Здесь у каждого измерения есть кнопка «Открыть графики». Сделайте "
                     "запись на шаге «Запуск измерения» — и она появится."),
            target=lambda: _first_graph_button(window),
            on_enter=lambda: _expand_all(window), media="reference_signal.png"),
        OnboardingStep(
            "Форма сигнала",
            "Сверьте форму с образцом (миниатюра ниже): чёткий резонансный пик без "
            "обрывов и без зашкаливания по краям. Посмотрели — закройте окно графиков "
            "и нажмите «Далее».",
            media="reference_signal.png"),
        OnboardingStep(
            "Вывод о годности",
            "Если форма нормальная — годность смотрим по максимальной амплитуде. "
            "В таблицу только что добавился столбец «Годность антенны»: всё, что ниже "
            "порога — брак (порог можно поменять в настройках).",
            target=lambda: window.tree,
            on_enter=lambda: (_add_verdict_column(window), _expand_all(window)),
            media="verdict.png"),
        OnboardingStep(
            "Следующая антенна",
            "Для <b>каждой</b> антенны добавляйте <b>новый предмет</b> (кнопка "
            "«Добавить предмет»), затем снова «НАЧАТЬ ЗАПИСЬ». Так проверяйте столько "
            "антенн, сколько нужно.<br><br>Здесь — меню <b>«Справка»</b> — вы всегда "
            "сможете снова открыть это обучение целиком или перейти к нужному шагу.",
            target_rect=lambda: help_menu_rect(window), media="intro.png"),
    ]


def build_advanced_tour(window) -> list[OnboardingStep]:
    P = lambda name: (lambda: getattr(window.instruments, name, None))  # noqa: E731
    return [
        OnboardingStep(
            "Продвинутое обучение",
            "Коротко обо всех возможностях. Это не только калибровка антенн: "
            "приложение получает и обрабатывает <b>любые осциллограммы</b> с "
            "поддерживаемых приборов. Подсветим, где что находится.",
            media="intro.png"),
        OnboardingStep(
            "Панель приборов",
            "Здесь выбираются генератор и осциллограф. Список заполняется реальным "
            "сканированием (VISA *IDN? и USB-поиск Hantek). «Обновить список» пишет в "
            "журнал всё найденное и ответы приборов.",
            target=lambda: window.instruments, media="devices_found.png"),
        OnboardingStep(
            "Свип-измерение АЧХ",
            "Эта кнопка запускает основной режим: генератор плавно меняет частоту, "
            "осциллограф снимает отклик, программа строит АЧХ и считает резонанс, "
            "полосу −3 дБ и добротность.",
            target=P("measure_btn")),
        OnboardingStep(
            "Просто чтение осциллографа",
            "Не нужен свип? Эта кнопка <b>просто читает данные с осциллографа</b> и "
            "сохраняет сигнал в дерево. Подходит для любой осциллограммы, а не только "
            "для измерения АЧХ.",
            target=P("read_btn")),
        OnboardingStep(
            "Периодическая запись",
            "Осциллограф можно опрашивать периодически (по интервалу) — удобно "
            "наблюдать за процессом во времени. Каждый опрос сохраняется отдельным "
            "измерением с временной меткой.",
            target=P("record_btn")),
        OnboardingStep(
            "Дерево предметов и измерений",
            "Слева — «Предмет → измерение». Двойной клик — переименование; "
            "перетаскивание — перенос измерения между предметами; двойной клик по "
            "заголовку столбца — фильтр; одиночный клик по заголовку — сортировка.",
            target=lambda: window.tree),
        OnboardingStep(
            "Графики и обработка",
            "По каждому измерению — окно обработки: исходные сигналы, сглаживание, "
            "выбор стратегии поиска фронта, строб (интервал анализа) и АЧХ. Параметры "
            "пересчитываются на лету; результат влияет на столбцы.",
            target=lambda: _first_graph_button(window)),
        OnboardingStep(
            "Столбцы и формулы",
            "Этой кнопкой настраивается набор столбцов (метрики каналов). Рядом — "
            "добавление пользовательского <b>столбца-формулы</b> (например "
            "max(amp)/mean(amp)).",
            target=lambda: window.toolbar.widgetForAction(window.act_columns)),
        OnboardingStep(
            "Сводка и набор кривых",
            "«Сводка» (подсвечена) накладывает АЧХ нескольких отмеченных измерений на "
            "один график. А меню «Кривые» — набор кривых с обменом с Excel и формулами "
            "с аннотациями (пик, полоса −3 дБ, касательная).",
            target=lambda: window.toolbar.widgetForAction(window.act_summary)),
        OnboardingStep(
            "Шаблоны обработки",
            "В этом меню «Шаблоны» параметры обработки + набор столбцов + формулы "
            "сохраняются как шаблон и применяются к выделенным или всем измерениям — "
            "не настраивать каждое заново.",
            target_rect=lambda: top_menu_rect(window, "Шаблоны")),
        OnboardingStep(
            "Экспорт и сохранение",
            "Этой кнопкой проект упаковывается в один файл .sigproj. Также есть "
            "сохранение всего или только отмеченных и выгрузка в Excel из сводки и "
            "окна графиков.",
            target=lambda: window.toolbar.widgetForAction(window.act_export)),
        OnboardingStep(
            "Обновления и расширения",
            "Меню «Обновление» — автообновление с GitHub (выбор ветки, замена только "
            "изменённых файлов). Новые приборы, столбцы, форматы и алгоритмы "
            "добавляются плагинами без перекомпиляции (docs/plugins.md, scenarios.md).",
            target_rect=lambda: top_menu_rect(window, "Обновление")),
        OnboardingStep(
            "Готово",
            "Это всё основное.<br><br>Здесь — меню <b>«Справка»</b> — вы всегда сможете "
            "снова запустить любой тур или перейти к отдельному шагу.",
            target_rect=lambda: help_menu_rect(window), media="intro.png"),
    ]


def _close_existing(window) -> None:
    ov = getattr(window, "_onboarding", None)
    if ov is not None:
        try:
            ov.finish()
        except Exception:                              # noqa: BLE001
            pass
    window._onboarding = None


def start_basic(window, start_index: int = 0):
    _close_existing(window)
    window._onboarding = OnboardingOverlay(window, build_basic_tour(window),
                                           "Базовое обучение", start_index)
    return window._onboarding


def start_advanced(window, start_index: int = 0):
    _close_existing(window)
    window._onboarding = OnboardingOverlay(window, build_advanced_tour(window),
                                           "Продвинутое обучение", start_index)
    return window._onboarding
