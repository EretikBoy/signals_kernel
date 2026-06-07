"""
signals.app_qt.update_dialog
============================

Окно автообновления с GitHub. Пользователь выбирает ветку, приложение сверяет
текущую версию с верхушкой ветки и заменяет изменённые файлы. Сеть — в потоке.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

from ..services.updater import DEFAULT_REPO, GitHubUpdater, UpdateError
from . import theme

_APP_ROOT = Path(__file__).resolve().parents[2]      # каталог с main.py и signals/


class _Worker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int)
    log = pyqtSignal(str)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn(self.progress.emit, self.log.emit))
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                       # noqa: BLE001
            self.failed.emit(f"Непредвиденная ошибка: {exc}")


class UpdateDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Обновление с GitHub")
        self.resize(640, 540)
        self._worker = None
        self._can_restart = False
        s = theme.load_settings()
        self.repo = s.get("update_repo", DEFAULT_REPO)
        self.token = s.get("github_token", "")
        self._updater = GitHubUpdater(_APP_ROOT, self.repo, self.token)
        self._build_ui()
        self._show_local()
        self._load_branches()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout(); root.addLayout(form)
        self.repo_edit = QLineEdit(self.repo)
        form.addRow("Репозиторий:", self.repo_edit)
        self.token_edit = QLineEdit(self.token)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("необязательно — поднимает лимит запросов")
        form.addRow("Токен GitHub:", self.token_edit)
        row = QHBoxLayout()
        self.branch_combo = QComboBox(); self.branch_combo.setMinimumWidth(240)
        row.addWidget(self.branch_combo, 1)
        self.refresh_btn = QPushButton("Обновить список веток")
        self.refresh_btn.clicked.connect(self._load_branches); row.addWidget(self.refresh_btn)
        form.addRow("Ветка:", row)

        self.current_lbl = QLabel("Текущая версия: …"); self.current_lbl.setWordWrap(True)
        root.addWidget(self.current_lbl)
        self.status_lbl = QLabel(""); self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        btns = QHBoxLayout()
        self.check_btn = QPushButton("Проверить обновления")
        self.check_btn.clicked.connect(self._check); btns.addWidget(self.check_btn)
        self.update_btn = QPushButton("Обновить")
        self.update_btn.setEnabled(False); self.update_btn.clicked.connect(self._apply)
        btns.addWidget(self.update_btn)
        self.restart_btn = QPushButton("Перезапустить")
        self.restart_btn.setEnabled(False); self.restart_btn.clicked.connect(self._restart)
        btns.addWidget(self.restart_btn)
        root.addLayout(btns)

        self.progress = QProgressBar(); root.addWidget(self.progress)
        self.logw = QPlainTextEdit(); self.logw.setReadOnly(True); root.addWidget(self.logw, 1)

    # ---- вспомогательное ---------------------------------------------------
    def _log(self, msg: str) -> None:
        self.logw.appendPlainText(msg)

    def _show_local(self) -> None:
        v = self._updater.local_version()
        if v.get("commit"):
            self.current_lbl.setText(
                f"Текущая версия: ветка {v.get('branch', '?')}, коммит "
                f"{v['commit'][:8]} ({v.get('date', '')[:10]})")
        else:
            self.current_lbl.setText("Текущая версия: не зафиксирована (первый запуск)")

    def _rebuild_updater(self) -> None:
        self.repo = self.repo_edit.text().strip() or DEFAULT_REPO
        self.token = self.token_edit.text().strip()
        theme.save_settings({"update_repo": self.repo, "github_token": self.token})
        self._updater = GitHubUpdater(_APP_ROOT, self.repo, self.token)

    def _busy(self, on: bool) -> None:
        for w in (self.check_btn, self.refresh_btn, self.update_btn, self.branch_combo):
            w.setEnabled(not on)
        if on:
            self.restart_btn.setEnabled(False)

    # ---- ветки -------------------------------------------------------------
    def _load_branches(self) -> None:
        self._rebuild_updater()
        self._busy(True); self._log("Загрузка списка веток…")
        self._worker = _Worker(lambda prog, log: self._updater.list_branches())
        self._worker.done.connect(self._branches_loaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _branches_loaded(self, branches) -> None:
        self._busy(False)
        prev = self.branch_combo.currentText()
        self.branch_combo.clear()
        for name, sha in branches:
            self.branch_combo.addItem(f"{name}  ({sha[:7]})", name)
        target = prev or self._updater.local_version().get("branch")
        if target:
            idx = self.branch_combo.findData(target)
            if idx >= 0:
                self.branch_combo.setCurrentIndex(idx)
        self._log(f"Веток найдено: {len(branches)}")

    def _branch(self) -> str:
        return self.branch_combo.currentData() or self.branch_combo.currentText().split()[0]

    # ---- проверка ----------------------------------------------------------
    def _check(self) -> None:
        self._rebuild_updater()
        branch = self._branch()
        if not branch:
            return
        self._busy(True); self._log(f"Сверка с веткой «{branch}»…")
        self._worker = _Worker(lambda prog, log: self._updater.check(branch))
        self._worker.done.connect(self._checked)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _checked(self, res) -> None:
        self._busy(False)
        head = res["remote"]
        info = (f"На GitHub: коммит {head['sha'][:8]} ({head.get('date', '')[:10]})\n"
                f"{head.get('message', '')}")
        if res["update_available"]:
            self.status_lbl.setText("⬆ Доступно обновление.\n" + info)
            self.update_btn.setEnabled(True)
        else:
            self.status_lbl.setText("✓ Установлена последняя версия.\n" + info)
            self.update_btn.setEnabled(False)
        self._log("Готово.")

    # ---- применение --------------------------------------------------------
    def _apply(self) -> None:
        branch = self._branch()
        if QMessageBox.question(
                self, "Обновление",
                f"Скачать ветку «{branch}» и заменить изменённые файлы приложения?\n"
                "Заменяемые файлы будут сохранены в резервную папку.") \
                != QMessageBox.StandardButton.Yes:
            return
        self._busy(True); self.update_btn.setEnabled(False)
        self._worker = _Worker(lambda prog, log: self._updater.download_and_apply(branch, prog, log))
        self._worker.progress.connect(self.progress.setValue)
        self._worker.log.connect(self._log)
        self._worker.done.connect(self._applied)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _applied(self, res) -> None:
        self._busy(False)
        changed = res.get("changed", [])
        self._show_local()
        if not changed:
            self.status_lbl.setText("Файлы уже актуальны — изменений не потребовалось.")
            self._log("Изменений нет.")
            return
        self.status_lbl.setText(f"✓ Обновлено файлов: {len(changed)}. "
                                "Перезапустите приложение, чтобы применить.")
        self._log("Изменённые файлы:")
        for f in changed[:200]:
            self._log(f"  {f}")
        if res.get("backup"):
            self._log(f"Резервная копия: {res['backup']}")
        self._can_restart = True
        self.restart_btn.setEnabled(True)

    def _restart(self) -> None:
        try:
            if getattr(sys, "frozen", False):          # собранный .exe
                args = [sys.executable, *sys.argv[1:]]
            else:                                       # python main.py
                args = [sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]]
            # Popen со списком сам экранирует пробелы/кириллицу в пути — в отличие от execv
            subprocess.Popen(args, cwd=str(_APP_ROOT))
            QApplication.quit()
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.information(self, "Перезапуск",
                                    f"Не удалось перезапустить автоматически ({exc}).\n"
                                    "Закройте и откройте приложение вручную.")

    def _on_failed(self, msg: str) -> None:
        self._busy(False)
        self.status_lbl.setText(f"Ошибка: {msg}")
        self._log(f"Ошибка: {msg}")
