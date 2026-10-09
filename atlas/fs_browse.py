"""Серверная часть веб-проводника: список папки, быстрые места, «последняя папка» и недавние файлы.

Только стандартная библиотека (Python 3.8, РЕД ОС 7.3, Windows). Сервер слушает 127.0.0.1, поэтому
показ файловой системы безопасен для одного пользователя. Одна «последняя папка» на пользователя
общая для всех строк импорта, экранов и приложений: хранится в ~/.pxg/ui.json
(каталог можно сменить переменной PXG_HOME, например для переносной сборки).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

MAX_RECENT = 12
DEFAULT_LIMIT = 500
TIME_BUDGET = 5.0  # секунд на чтение одной папки (медленные сетевые каталоги)

_lock = threading.Lock()


# ---------- настройки пользователя ----------

def settings_path() -> str:
    home = os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg")
    return os.path.join(home, "ui.json")


def _read_settings() -> Dict[str, Any]:
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_settings(data: Dict[str, Any]) -> None:
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass  # нет прав на запись — просто не запоминаем


def get_last() -> Dict[str, Any]:
    """Последняя папка (если она ещё существует) и недавние файлы (существующие)."""
    with _lock:
        data = _read_settings()
    last = data.get("last_dir") or ""
    if not (last and os.path.isdir(last)):
        last = ""
    recent = [p for p in (data.get("recent") or []) if isinstance(p, str) and os.path.isfile(p)]
    return {"dir": last, "recent": recent[:MAX_RECENT]}


def set_last(directory: str = "", file: str = "") -> Dict[str, Any]:
    """Запомнить папку; при выборе файла — и сам файл (папка берётся из файла)."""
    file = os.path.normpath(file) if file else ""
    directory = os.path.normpath(directory) if directory else ""
    if file and not directory:
        directory = os.path.dirname(file)
    with _lock:
        data = _read_settings()
        if directory and os.path.isdir(directory):
            data["last_dir"] = directory
        if file:
            rec = [p for p in (data.get("recent") or []) if p != file]
            data["recent"] = ([file] + rec)[:MAX_RECENT]
        _write_settings(data)
    return get_last()


# ---------- быстрые места ----------

def places() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()

    def add(name: str, path: str, kind: str = "folder") -> None:
        if path and path not in seen and os.path.isdir(path):
            seen.add(path)
            out.append({"name": name, "path": path, "kind": kind})

    home = os.path.expanduser("~")
    add("Домашняя", home, "home")
    for name, variants in (("Рабочий стол", ("Desktop", "Рабочий стол")),
                           ("Документы", ("Documents", "Документы")),
                           ("Загрузки", ("Downloads", "Загрузки"))):
        for v in variants:
            add(name, os.path.join(home, v))
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = letter + ":\\"
            try:
                if os.path.exists(drive):
                    add(letter + ":", drive, "drive")
            except OSError:
                pass
    else:
        add("Корень /", "/", "drive")
        add("/mnt", "/mnt", "drive")
        add("/media", "/media", "drive")
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        run_media = os.path.join("/run/media", user) if user else "/run/media"
        add(run_media, run_media, "drive")
    return out


# ---------- список папки ----------

def _parse_filter(filt: str) -> List[str]:
    return [("." + e.strip().lstrip(".*").lower()) for e in filt.replace(",", " ").split() if e.strip().lstrip(".*")]


def _stat(entry: "os.DirEntry[str]") -> Optional[os.stat_result]:
    try:
        return entry.stat()
    except OSError:
        return None


def list_dir(path: str, filt: str = "", hidden: bool = False, query: str = "", sort: str = "name",
             desc: bool = False, offset: int = 0, limit: int = DEFAULT_LIMIT,
             budget: float = TIME_BUDGET, only_dirs: bool = False) -> Dict[str, Any]:
    """Содержимое папки: сначала папки, затем файлы. Ошибка доступа — поле «error», а не исключение."""
    path = os.path.normpath(path) if path else ""
    res = {"path": path, "parent": "", "items": [], "total": 0, "offset": offset, "truncated": False, "error": ""}
    if not path or not os.path.isdir(path):
        res["error"] = "Папка не найдена: %s" % (path or "—")
        return res
    parent = os.path.dirname(path)
    res["parent"] = parent if parent and parent != path else ""
    exts = _parse_filter(filt)
    q = query.strip().lower()
    started = time.monotonic()
    items: List[Dict[str, Any]] = []
    try:
        it = os.scandir(path)
    except PermissionError:
        res["error"] = "Нет доступа к папке"
        return res
    except OSError as e:
        res["error"] = "Папка недоступна: %s" % (e.strerror or e)
        return res
    with it:
        while True:
            if time.monotonic() - started > budget:
                res["truncated"] = True
                break
            try:
                entry = next(it)
            except StopIteration:
                break
            except OSError:
                break
            name = entry.name
            if not hidden and (name.startswith(".") or name.startswith("~$")):
                continue
            if q and q not in name.lower():
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            if not is_dir:
                if only_dirs:
                    continue
                if exts and os.path.splitext(name)[1].lower() not in exts:
                    continue
            st = _stat(entry)
            accessible = True
            if is_dir:
                accessible = os.access(entry.path, os.R_OK | os.X_OK)
            items.append({
                "name": name, "dir": is_dir,
                "size": 0 if is_dir or st is None else st.st_size,
                "mtime": dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M") if st else "",
                "ext": "" if is_dir else os.path.splitext(name)[1].lower().lstrip("."),
                "locked": not accessible or st is None,
            })
    key = {"size": lambda x: x["size"], "mtime": lambda x: x["mtime"]}.get(sort, lambda x: x["name"].lower())
    folders = sorted([x for x in items if x["dir"]], key=key, reverse=desc)
    files = sorted([x for x in items if not x["dir"]], key=key, reverse=desc)
    items = folders + files
    res["total"] = len(items)
    res["items"] = items[offset:offset + limit]
    return res


# ---------- маршруты ----------

def _int(v: Optional[str], default: int) -> int:
    try:
        return max(0, int(v)) if v is not None else default
    except ValueError:
        return default


async def _list(request: Request) -> JSONResponse:
    from starlette.concurrency import run_in_threadpool
    q = request.query_params
    path = q.get("path") or ""
    if not path:
        path = get_last()["dir"] or os.path.expanduser("~")
    elif os.path.isfile(path):
        path = os.path.dirname(path)
    res = await run_in_threadpool(
        list_dir, path, q.get("filter") or "", q.get("hidden") in ("1", "true"), q.get("q") or "",
        q.get("sort") or "name", q.get("desc") in ("1", "true"), _int(q.get("offset"), 0),
        min(_int(q.get("limit"), DEFAULT_LIMIT), 5000), TIME_BUDGET, q.get("kind") == "folder")
    return JSONResponse(res)


async def _places(request: Request) -> JSONResponse:
    from starlette.concurrency import run_in_threadpool
    return JSONResponse({"places": await run_in_threadpool(places)})


async def _last(request: Request) -> JSONResponse:
    if request.method == "POST":
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return JSONResponse(set_last(str(body.get("dir") or ""), str(body.get("file") or "")))
    return JSONResponse(get_last())


async def _file(request: Request):
    """Содержимое файла по пути из проводника (сервер локальный, 127.0.0.1): интерфейс получает его как обычный выбранный файл."""
    from starlette.responses import FileResponse
    path = request.query_params.get("path") or ""
    if not path or not os.path.isfile(path):
        return JSONResponse({"error": "Файл не найден: %s" % (path or "—")}, status_code=404)
    if not os.access(path, os.R_OK):
        return JSONResponse({"error": "Нет доступа к файлу"}, status_code=403)
    return FileResponse(path, media_type="application/octet-stream")


def routes() -> List[Route]:
    return [
        Route("/api/fs/file", _file),
        Route("/api/fs/list", _list),
        Route("/api/fs/places", _places),
        Route("/api/fs/last", _last, methods=["GET", "POST"]),
    ]
