"""
signals.services.updater
=========================

Автообновление приложения с GitHub.

Пользователь выбирает ветку репозитория, а дальше всё просто: программа
сравнивает сохранённый у себя commit SHA с верхушкой этой ветки на GitHub,
и если они разошлись — скачивает архив ветки и подменяет только те файлы,
что реально изменились (старые версии перед этим уносятся в бэкап).

Сторонних зависимостей нет — обходимся стандартной библиотекой (urllib и
zipfile), чтобы не тащить лишнее ради разовой операции. Сетевые методы нужно
вызывать из рабочего потока, не из GUI — иначе интерфейс подвиснет на время
скачивания (где это делается — app_qt/update_dialog.py).
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_REPO = "EretikBoy/signals"
VERSION_FILE = ".signals_version.json"
API = "https://api.github.com"
# Поддеревья/файлы, которые обновление НЕ трогает (защита данных пользователя):
#  - DLL Hantek, которые пользователь положил сам;
#  - служебное (.git, __pycache__, бэкапы, файл версии).
_SKIP_DIRS = {".git", "__pycache__"}
_SKIP_REL_PREFIXES = ("signals/contrib/hantek_dll",)


class UpdateError(RuntimeError):
    """Понятная пользователю ошибка обновления."""


def _request(url: str, token: str | None, accept: str) -> urllib.request.Request:
    headers = {"User-Agent": "signals-updater", "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _get_json(url: str, token: str | None = None):
    try:
        with urllib.request.urlopen(
            _request(url, token, "application/vnd.github+json"), timeout=25) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and exc.headers.get("x-ratelimit-remaining") == "0":
            raise UpdateError("Превышен лимит запросов к GitHub (60/час без токена). "
                              "Попробуйте позже или укажите токен в настройках.") from exc
        if exc.code == 404:
            raise UpdateError("Не найдено на GitHub — проверьте репозиторий и ветку.") from exc
        raise UpdateError(f"GitHub вернул ошибку {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"Нет связи с GitHub: {exc.reason}") from exc
    except Exception as exc:                           # noqa: BLE001
        raise UpdateError(f"Ошибка запроса: {exc}") from exc


def _skip(rel: Path) -> bool:
    if any(part in _SKIP_DIRS for part in rel.parts):
        return True
    if rel.name == VERSION_FILE or rel.parts and rel.parts[0].startswith(".backup_"):
        return True
    rel_posix = rel.as_posix()
    return any(rel_posix.startswith(p) for p in _SKIP_REL_PREFIXES)


class GitHubUpdater:
    def __init__(self, app_root, repo: str = DEFAULT_REPO, token: str | None = None) -> None:
        self.app_root = Path(app_root)
        self.repo = repo or DEFAULT_REPO
        self.token = token or None

    # ---- информация о версиях ---------------------------------------------
    def list_branches(self) -> list[tuple[str, str]]:
        data = _get_json(f"{API}/repos/{self.repo}/branches", self.token)
        return [(b["name"], b["commit"]["sha"]) for b in data]

    def branch_head(self, branch: str) -> dict:
        ref = urllib.parse.quote(branch, safe="")        # кириллица/пробелы в URL
        b = _get_json(f"{API}/repos/{self.repo}/branches/{ref}", self.token)
        commit = b["commit"].get("commit", {})
        msg = (commit.get("message") or "").splitlines()
        return {"sha": b["commit"]["sha"],
                "date": commit.get("author", {}).get("date", ""),
                "message": msg[0] if msg else ""}

    def local_version(self) -> dict:
        try:
            return json.loads((self.app_root / VERSION_FILE).read_text("utf-8"))
        except Exception:                              # noqa: BLE001
            return {}

    def _save_version(self, branch: str, head: dict) -> None:
        (self.app_root / VERSION_FILE).write_text(
            json.dumps({"branch": branch, "commit": head["sha"],
                        "date": head.get("date", ""), "message": head.get("message", "")},
                       ensure_ascii=False, indent=2), "utf-8")

    def check(self, branch: str) -> dict:
        head = self.branch_head(branch)
        local = self.local_version()
        same = local.get("commit") == head["sha"] and local.get("branch") == branch
        return {"branch": branch, "remote": head, "local": local,
                "update_available": not same}

    # ---- применение обновления --------------------------------------------
    def _download_zip(self, branch: str, say) -> bytes:
        ref = urllib.parse.quote(branch, safe="")
        url = f"https://codeload.github.com/{self.repo}/zip/refs/heads/{ref}"
        say(f"Скачивание ветки «{branch}»…")
        try:
            with urllib.request.urlopen(
                _request(url, self.token, "application/zip"), timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            raise UpdateError(f"Не удалось скачать ветку ({exc.code}).") from exc
        except Exception as exc:                       # noqa: BLE001
            raise UpdateError(f"Ошибка скачивания: {exc}") from exc

    @staticmethod
    def _find_app_root(extracted: Path) -> Path:
        """Найти внутри архива каталог приложения (где есть main.py и signals/)."""
        if (extracted / "main.py").exists() and (extracted / "signals").is_dir():
            return extracted
        for p in sorted(extracted.rglob("*")):
            if p.is_dir() and (p / "main.py").exists() and (p / "signals").is_dir():
                return p
        subs = [p for p in extracted.iterdir() if p.is_dir()]
        return subs[0] if subs else extracted

    def download_and_apply(self, branch: str, progress=None, log=None) -> dict:
        prog = progress or (lambda p: None)
        say = log or (lambda m: None)
        head = self.branch_head(branch)
        data = self._download_zip(branch, say)
        prog(40)
        changed: list[str] = []
        backup = self.app_root / f".backup_{time.strftime('%Y%m%d_%H%M%S')}"
        backed_up = False
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(td)
            src = self._find_app_root(Path(td))
            say(f"Применение изменений (источник: {src.name})…")
            files = [p for p in src.rglob("*") if p.is_file()]
            total = len(files) or 1
            for i, p in enumerate(files):
                rel = p.relative_to(src)
                prog(40 + int(i / total * 55))
                if _skip(rel):
                    continue
                dst = self.app_root / rel
                new = p.read_bytes()
                if dst.exists():
                    if dst.read_bytes() == new:
                        continue                       # файл не изменился
                    (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, backup / rel)    # бэкап заменяемого
                    backed_up = True
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(new)
                changed.append(rel.as_posix())
        if backed_up:
            say(f"Бэкап заменённых файлов: {backup.name}")
        self._save_version(branch, head)
        prog(100)
        say(f"Обновлено файлов: {len(changed)}")
        return {"changed": changed, "remote": head,
                "backup": backup.name if backed_up else None}
