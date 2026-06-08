"""
Окно установщика на tkinter (stdlib — install.exe должен оставаться лёгким).

Один install.exe для online и offline архивов: _detect_mode смотрит, что
лежит рядом, и выбирает конвейер — steps.PIPELINE или offline_steps.PIPELINE.
Установка идёт в фоновом потоке; с tkinter общаемся только через очередь
и `after`-опрос из основного потока (tkinter не потокобезопасен).
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from .. import detect
from . import offline_steps, steps

_POLL_MS = 80

ContextFactory = Callable[[detect.TargetProfile, Path], Any]


def _detect_mode(payload_dir: Path) -> str:
    """pyruntime-{amd64,win32}/ рядом -> offline-бандл, иначе лёгкий online-архив."""
    if (payload_dir / "pyruntime-amd64").exists() or (payload_dir / "pyruntime-win32").exists():
        return "offline"
    return "online"


class InstallerWindow(tk.Tk):
    def __init__(self, *, payload_dir: Path) -> None:
        super().__init__()
        self.title("Установка Signals")
        self.geometry("580x380")
        self.resizable(False, False)

        self._payload_dir = payload_dir
        self._profile = detect.detect_target()
        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

        self._mode = _detect_mode(payload_dir)
        if self._mode == "offline":
            self._pipeline = offline_steps.PIPELINE
            self._make_context: ContextFactory = (
                lambda profile, payload: offline_steps.OfflineContext(profile=profile, payload_dir=payload))
            self._done_hint = "Запускайте приложение файлом «Запустить Signals.bat»."
        else:
            self._pipeline = steps.PIPELINE
            self._make_context = (
                lambda profile, payload: steps.InstallContext(
                    profile=profile, install_dir=Path.home() / "Signals", payload_dir=payload))
            self._done_hint = "Запустите приложение из папки app (main.py)."

        self._build_widgets()
        self._log(f"Режим установки: {'оффлайн (готовый бандл)' if self._mode == 'offline' else 'онлайн (загрузка по сети)'}")
        self._log(f"Обнаружено: {self._profile.os_label} "
                  f"→ Python {self._profile.python_version} ({self._profile.python_arch}), "
                  f"{self._profile.qt_binding}")
        self.after(_POLL_MS, self._poll_queue)

    # ---- построение виджетов -------------------------------------------------
    def _build_widgets(self) -> None:
        ttk.Label(self, text="Установка Signals", font=("Segoe UI", 14, "bold")) \
            .pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(self, text=f"Обнаружена система: {self._profile.os_label}") \
            .pack(anchor="w", padx=12, pady=(2, 8))

        self._status_var = tk.StringVar(value="Готово к установке")
        ttk.Label(self, textvariable=self._status_var).pack(anchor="w", padx=12)

        self._progress = ttk.Progressbar(self, mode="determinate", maximum=1000)
        self._progress.pack(fill="x", padx=12, pady=(4, 10))

        self._log_box = tk.Text(self, height=12, state="disabled", wrap="word",
                                font=("Consolas", 9))
        self._log_box.pack(fill="both", expand=True, padx=12)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=10)
        self._start_btn = ttk.Button(btns, text="Установить", command=self._start)
        self._start_btn.pack(side="left")
        self._close_btn = ttk.Button(btns, text="Закрыть", command=self.destroy)
        self._close_btn.pack(side="right")

    def _log(self, text: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.insert("end", text + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    # ---- запуск конвейера в фоновом потоке -----------------------------------
    def _start(self) -> None:
        self._start_btn.configure(state="disabled")
        ctx = self._make_context(self._profile, self._payload_dir)
        threading.Thread(target=self._run_pipeline, args=(ctx,), daemon=True).start()

    def _run_pipeline(self, ctx: Any) -> None:
        pipeline = self._pipeline
        total = len(pipeline)
        try:
            for i, (label, step) in enumerate(pipeline):
                def report(fraction: float, text: str, _i: int = i, _label: str = label) -> None:
                    overall = (_i + max(0.0, min(1.0, fraction))) / total
                    self._queue.put(("progress", (overall, f"[{_i + 1}/{total}] {_label}: {text}")))
                report(0.0, "начало")
                step(ctx, report)
            self._queue.put(("done", None))
        except Exception as exc:                           # noqa: BLE001 — показываем причину пользователю как есть
            self._queue.put(("error", str(exc)))

    # ---- доставка прогресса из фонового потока в Tk --------------------------
    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    fraction, text = payload                # type: ignore[misc]
                    self._progress["value"] = fraction * 1000
                    self._status_var.set(text)
                    self._log(text)
                elif kind == "done":
                    self._progress["value"] = 1000
                    self._status_var.set("Готово — " + self._done_hint)
                    self._log("Установка завершена.")
                    messagebox.showinfo("Готово", f"Установка завершена.\n\n{self._done_hint}")
                elif kind == "error":
                    self._status_var.set("Ошибка установки")
                    self._log(f"ОШИБКА: {payload}")
                    messagebox.showerror("Ошибка установки", str(payload))
                    self._start_btn.configure(state="normal")
        except queue.Empty:
            pass
        self.after(_POLL_MS, self._poll_queue)
