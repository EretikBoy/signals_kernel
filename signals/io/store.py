"""
signals.io.store
================

Хранилище проекта вместо pickle. Проект — это ПАПКА:

    project/
      project.json          индекс: предметы, анализы, параметры, метки
      data/<analysis_id>.csv данные каналов анализа (CHx_time, CHx_amplitude)

Это решает проблему «перезатёртых данных» и тормозов автосейва:
* Запись атомарна (через temp-файл + os.replace).
* Сохранение ИНКРЕМЕНТАЛЬНОЕ — переписываются только изменённые анализы
  (`Analysis.dirty`), а не все 1000. Поэтому автосейв не кладёт UI.
* CSV каналов читаются тем же парсером, что и обычные файлы (формат совместим).

Для передачи/архива есть pack()/unpack() в один .sigproj (zip) — это и сжатие.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import numpy as np

from ..domain import Analysis, Channel, ChannelMetadata, MeasurementParams, Project, Subject
from .parsers import parse_csv


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)            # атомарная замена
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class ProjectStore:
    SUFFIX = ".sigproj"

    # ---- сохранение --------------------------------------------------------
    def save(self, project: Project, folder: str | Path, *, full: bool = False) -> None:
        folder = Path(folder)
        data_dir = folder / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        index = {"version": 1, "subjects": []}
        for subject in project.subjects:
            s_rec = {"code": subject.code, "name": subject.name, "analyses": []}
            for a in subject.analyses:
                s_rec["analyses"].append({
                    "id": a.id,
                    "label": a.label,
                    "description": a.description,
                    "source_file": str(a.source_file) if a.source_file else None,
                    "signal_start_channel": a.signal_start_channel,
                    "selected_channel": a.selected_channel,
                    "params": asdict(a.params),
                    "channels": list(a.channels.keys()),
                })
                if full or a.dirty:
                    self._write_analysis_csv(data_dir / f"{a.id}.csv", a)
                    a.dirty = False
            index["subjects"].append(s_rec)

        _atomic_write_text(folder / "project.json", json.dumps(index, ensure_ascii=False, indent=2))

    def _write_analysis_csv(self, path: Path, analysis: Analysis) -> None:
        frame = {}
        for name, ch in analysis.channels.items():
            frame[f"{name}_time"] = pd.Series(ch.time)
            frame[f"{name}_amplitude"] = pd.Series(ch.amplitude)
        df = pd.DataFrame(frame)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        os.close(fd)
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)

    # ---- загрузка ----------------------------------------------------------
    def load(self, folder: str | Path) -> Project:
        folder = Path(folder)
        index = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        subjects: list[Subject] = []
        for s_rec in index["subjects"]:
            analyses: list[Analysis] = []
            for a_rec in s_rec["analyses"]:
                csv_path = folder / "data" / f"{a_rec['id']}.csv"
                channels = parse_csv(str(csv_path)) if csv_path.exists() else {}
                analyses.append(Analysis(
                    params=MeasurementParams(**a_rec["params"]),
                    channels=channels,
                    signal_start_channel=a_rec.get("signal_start_channel", ""),
                    selected_channel=a_rec.get("selected_channel", ""),
                    source_file=Path(a_rec["source_file"]) if a_rec.get("source_file") else None,
                    label=a_rec.get("label", ""),
                    description=a_rec.get("description", ""),
                    id=a_rec["id"],
                    dirty=False,
                ))
            subjects.append(Subject(code=s_rec["code"], name=s_rec.get("name", ""), analyses=analyses))
        return Project(subjects=subjects)

    # ---- упаковка в один файл (.sigproj = zip) -----------------------------
    def pack(self, folder: str | Path, archive: str | Path) -> None:
        folder = Path(folder)
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in folder.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(folder))

    def unpack(self, archive: str | Path, folder: str | Path) -> Path:
        folder = Path(folder)
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(folder)
        return folder

    # ---- миграция: старый формат .analysis (pickle) ------------------------
    def load_legacy(self, analysis_file: str | Path) -> Project:
        """Загрузить проект из старого формата приложения (.analysis = pickle).

        Данные каналов лежат прямо в пикле (channels_data → DataFrame с колонками
        «Время»/«Амплитуда»), поэтому соседняя папка с CSV не требуется.
        """
        import pickle
        with open(analysis_file, "rb") as f:
            data = pickle.load(f)

        subjects: list[Subject] = []
        for code, s_info in data.get("subjects", {}).items():
            analyses: list[Analysis] = []
            for _idx, a_info in s_info.get("analyses", {}).items():
                channels: dict[str, Channel] = {}
                for cname, cdata in a_info.get("channels_data", {}).items():
                    df = pd.DataFrame(cdata.get("data", {}))
                    if "Время" in df and "Амплитуда" in df:
                        t = df["Время"].to_numpy(dtype=float)
                        a = df["Амплитуда"].to_numpy(dtype=float)
                    elif df.shape[1] >= 2:
                        t = df.iloc[:, 0].to_numpy(dtype=float)
                        a = df.iloc[:, 1].to_numpy(dtype=float)
                    else:
                        continue
                    name = cdata.get("name", cname)
                    channels[name] = Channel(name=name, time=t, amplitude=a,
                                             metadata=ChannelMetadata(record_length=t.size,
                                                                      source_label=cname))
                p = a_info.get("params", {})
                params = MeasurementParams(
                    start_freq=float(p.get("start_freq", 100)),
                    end_freq=float(p.get("end_freq", 1000)),
                    sweep_time=float(p.get("sweep_time", 30)),
                    record_time=float(p.get("record_time", 1)),
                    cut_second=float(p.get("cut_second", 0)),
                    fixedlevel=float(p.get("fixedlevel", 0.6)),
                    gain=float(p.get("gain", 7)),
                    amplitude=float(p.get("amplitude", 1)),
                    offset=float(p.get("offset", 0)),
                )
                analyses.append(Analysis(
                    params=params, channels=channels,
                    label=a_info.get("original_file_name") or a_info.get("file_name", ""),
                    dirty=True,
                ))
            subjects.append(Subject(code=code, name=s_info.get("subject_name", code),
                                    analyses=analyses))
        return Project(subjects=subjects)
