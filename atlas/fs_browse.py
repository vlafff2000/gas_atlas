"""Серверная часть веб-проводника: список папки, быстрые места, «последняя папка» и недавние файлы.

Только стандартная библиотека (Python 3.12+, РЕД ОС 7.3, Windows). Сервер слушает 127.0.0.1, поэтому
показ файловой системы безопасен для одного пользователя. Одна «последняя папка» на пользователя
общая для всех строк импорта, экранов и приложений: хранится в ~/.pxg/ui.json
(каталог можно сменить переменной PXG_HOME, например для переносной сборки).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import stat as stat_mod
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

MAX_RECENT = 12
DEFAULT_LIMIT = 500
TIME_BUDGET = 5.0  # секунд на чтение одной папки (медленные сетевые каталоги)
LIST_TIMEOUT = 8.0  # секунд до ответа «диск не отвечает»: зависший сетевой путь не вешает окно
PROBE_TIMEOUT = 1.5  # секунд на проверку «папка существует» там, где диск может не отвечать
CACHE_MAX_AGE = 600.0  # секунд, сколько хранится прежний листинг сетевой папки
CACHE_MAX = 64
DEAD_BACKOFF = 10.0  # секунд, в течение которых недоступный путь не опрашивается повторно
NET_FSTYPES = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "afs", "ceph", "glusterfs", "fuse.glusterfs",
               "fuse.sshfs", "davfs", "fuse.davfs", "fuse.rclone", "fuse.gvfsd-fuse", "9p", "lustre"}

_lock = threading.Lock()


class PathTimeout(Exception):
    """Путь не ответил за отведённое время."""


def _with_timeout(fn, timeout: float, *args, **kw):
    """Выполнить fn в фоновом потоке; если диск завис — PathTimeout, а окно остаётся живым."""
    box: Dict[str, Any] = {}

    def work() -> None:
        try:
            box["v"] = fn(*args, **kw)
        except BaseException as e:  # noqa: BLE001 - передаём в вызывающий поток
            box["e"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise PathTimeout()
    if "e" in box:
        raise box["e"]
    return box.get("v")


def _probe(path: str, timeout: float = PROBE_TIMEOUT, kind: str = "dir") -> bool:
    """os.path.isdir/isfile с ограничением по времени (недоступный диск = False, не зависание)."""
    f = os.path.isdir if kind == "dir" else os.path.isfile
    try:
        return bool(_with_timeout(f, timeout, path))
    except (PathTimeout, OSError):
        return False


# ---------- сетевые пути ----------

_mounts_cache: Dict[str, Any] = {"t": 0.0, "v": []}
_drive_type_cache: Dict[str, int] = {}


def _unesc(s: str) -> str:
    return s.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def net_mounts() -> List[Dict[str, str]]:
    """Сетевые монтирования Linux из /proc/mounts: [{dev, path, fstype}] (читается раз в 30 с)."""
    now = time.monotonic()
    if now - _mounts_cache["t"] < 30 and _mounts_cache["v"] is not None and _mounts_cache["t"]:
        return _mounts_cache["v"]
    out: List[Dict[str, str]] = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[2] in NET_FSTYPES:
                    out.append({"dev": _unesc(parts[0]), "path": _unesc(parts[1]), "fstype": parts[2]})
    except OSError:
        pass
    _mounts_cache.update(t=now, v=out)
    return out


LOCAL_FSTYPES = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "vfat", "exfat", "ntfs", "ntfs3",
                 "fuseblk", "tmpfs", "ramfs", "overlay", "squashfs", "iso9660", "udf", "devtmpfs", "proc", "sysfs"}
_all_mounts_cache: Dict[str, Any] = {"t": 0.0, "v": None}


def _all_mounts() -> List[Any]:
    """Все монтирования Linux [(путь, тип ФС)], длинные пути первыми (читается раз в 30 с)."""
    now = time.monotonic()
    if _all_mounts_cache["v"] is not None and now - _all_mounts_cache["t"] < 30:
        return _all_mounts_cache["v"]
    out: List[Any] = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    out.append((_unesc(parts[1]), parts[2]))
    except OSError:
        pass
    out.sort(key=lambda m: -len(m[0]))
    _all_mounts_cache.update(t=now, v=out)
    return out


def is_known_local(path: str) -> bool:
    """Точно локальный диск? На Windows — всё, что не сетевое. На Linux — только ФС из списка локальных:
    всё незнакомое (autofs, fuse, gvfs, неопознанные монтирования) читаем «легко», как сетевое."""
    if os.name == "nt":
        return not is_network(path)
    norm = path.rstrip("/") or "/"
    for mp, fstype in _all_mounts():
        m = mp.rstrip("/") or "/"
        if norm == m or m == "/" or norm.startswith(m + "/"):
            return fstype in LOCAL_FSTYPES
    return True  # нет /proc/mounts (не Linux): считаем локальным


def _gvfs_dirs() -> List[str]:
    out = []
    uid = os.getuid() if hasattr(os, "getuid") else None
    for base in ((("/run/user/%d/gvfs" % uid) if uid is not None else ""), os.path.join(os.path.expanduser("~"), ".gvfs")):
        if base:
            out.append(base)
    return out


def _win_drive_type(letter: str) -> int:
    """0 — неизвестно, 2 съёмный, 3 локальный, 4 сетевой, 5 привод. Без обращения к диску."""
    if letter in _drive_type_cache:
        return _drive_type_cache[letter]
    try:
        import ctypes
        t = int(ctypes.windll.kernel32.GetDriveTypeW(letter + ":\\"))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        t = 0
    _drive_type_cache[letter] = t
    return t


def is_network(path: str) -> bool:
    """Сетевой ли путь: UNC и сопоставленный сетевой диск (Windows); cifs/nfs/sshfs/gvfs (Linux). Без обращения к диску."""
    if not path:
        return False
    if path.startswith("\\\\") or path.startswith("//"):
        return True
    if os.name == "nt":
        return len(path) >= 2 and path[1] == ":" and _win_drive_type(path[0].upper()) == 4
    norm = path.rstrip("/") or "/"
    for base in _gvfs_dirs():
        if norm == base or norm.startswith(base + "/"):
            return True
    for m in net_mounts():
        mp = m["path"].rstrip("/") or "/"
        if norm == mp or norm.startswith(mp + "/"):
            return True
    return False


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
    if last and is_known_local(last) and not is_network(last) and not os.path.isdir(last):
        last = ""
    recent = [p for p in (data.get("recent") or [])
              if isinstance(p, str) and (is_network(p) or not is_known_local(p) or os.path.isfile(p))]  # сетевые не опрашиваем при старте
    return {"dir": last, "recent": recent[:MAX_RECENT]}


def set_last(directory: str = "", file: str = "") -> Dict[str, Any]:
    """Запомнить папку; при выборе файла — и сам файл (папка берётся из файла)."""
    file = os.path.normpath(file) if file else ""
    directory = os.path.normpath(directory) if directory else ""
    if file and not directory:
        directory = os.path.dirname(file)
    with _lock:
        data = _read_settings()
        if directory and (is_network(directory) or not is_known_local(directory) or os.path.isdir(directory)):
            data["last_dir"] = directory
        if file:
            rec = [p for p in (data.get("recent") or []) if p != file]
            data["recent"] = ([file] + rec)[:MAX_RECENT]
        _write_settings(data)
    return get_last()


def get_win() -> Dict[str, int]:
    """Запомненный размер окна проводника (общий для всех приложений)."""
    with _lock:
        w = _read_settings().get("win")
    if isinstance(w, dict) and all(isinstance(w.get(k), int) for k in ("w", "h")):
        return {"w": w["w"], "h": w["h"]}
    return {}


def set_win(w: Any, h: Any) -> Dict[str, int]:
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError):
        return get_win()
    if not (300 <= w <= 10000 and 200 <= h <= 10000):
        return get_win()
    with _lock:
        data = _read_settings()
        data["win"] = {"w": w, "h": h}
        _write_settings(data)
    return {"w": w, "h": h}


# ---------- избранное и часто посещаемые папки ----------
# Избранное — список, который инженер правит вручную (в том числе сетевые пути; существование не проверяем,
# чтобы не опрашивать диски). «Часто посещаемые» — только подсказка по счётчику заходов, любую запись можно убрать.

MAX_VISITS = 200
MAX_FREQUENT = 8
MIN_FREQUENT = 2  # столько заходов нужно, чтобы папка попала в подсказку


def _norm_dir(path: str) -> str:
    path = (path or "").strip().strip('"')
    if not path:
        return ""
    if len(path) > 1:
        path = os.path.normpath(path)
    return path


def _fav_name(path: str) -> str:
    return os.path.basename(path.rstrip("\\/")) or path


def get_favorites() -> Dict[str, Any]:
    with _lock:
        data = _read_settings()
    favs = []
    for f in data.get("favorites") or []:
        if isinstance(f, dict) and isinstance(f.get("path"), str) and f["path"]:
            favs.append({"path": f["path"], "name": str(f.get("name") or _fav_name(f["path"])),
                         "network": is_network(f["path"])})
    have = {f["path"] for f in favs}
    visits = data.get("visits") if isinstance(data.get("visits"), dict) else {}
    top = sorted(((p, v) for p, v in visits.items() if isinstance(v, dict) and isinstance(v.get("n"), int)
                  and v["n"] >= MIN_FREQUENT and p not in have),
                 key=lambda x: (-x[1]["n"], -(x[1].get("t") or 0)))[:MAX_FREQUENT]
    return {"favorites": favs,
            "frequent": [{"path": p, "name": _fav_name(p), "n": v["n"], "network": is_network(p)} for p, v in top]}


def add_visit(path: str) -> None:
    path = _norm_dir(path)
    if not path:
        return
    with _lock:
        data = _read_settings()
        visits = data.get("visits") if isinstance(data.get("visits"), dict) else {}
        v = visits.get(path) if isinstance(visits.get(path), dict) else {"n": 0}
        visits[path] = {"n": int(v.get("n") or 0) + 1, "t": int(time.time())}
        while len(visits) > MAX_VISITS:  # забываем самые редкие и старые
            visits.pop(min(visits, key=lambda k: (visits[k].get("n", 0), visits[k].get("t", 0))))
        data["visits"] = visits
        _write_settings(data)


def edit_favorites(action: str, path: str = "", name: str = "", to: int = -1) -> Dict[str, Any]:
    """add / remove / rename / move (на позицию to) для избранного; hide — убрать папку из «часто посещаемых»."""
    path = _norm_dir(path)
    with _lock:
        data = _read_settings()
        favs = [f for f in (data.get("favorites") or []) if isinstance(f, dict) and f.get("path")]
        idx = next((i for i, f in enumerate(favs) if f["path"] == path), -1)
        if action == "add" and path and idx < 0:
            favs.append({"path": path, "name": name.strip() or _fav_name(path)})
        elif action == "remove" and idx >= 0:
            favs.pop(idx)
        elif action == "rename" and idx >= 0:
            favs[idx]["name"] = name.strip() or _fav_name(path)
        elif action == "move" and idx >= 0 and 0 <= to < len(favs):
            favs.insert(to, favs.pop(idx))
        elif action == "hide" and isinstance(data.get("visits"), dict):
            data["visits"].pop(path, None)
        elif action == "clear_visits":
            data["visits"] = {}
        data["favorites"] = favs
        _write_settings(data)
    return get_favorites()


# ---------- быстрые места ----------

def _win_drives() -> List[Dict[str, str]]:
    """Диски Windows: буква, тип, UNC для сопоставленных сетевых. Маску дисков берём без обращения к ним."""
    import ctypes
    k = ctypes.windll.kernel32  # type: ignore[attr-defined]
    mask = int(k.GetLogicalDrives())
    out = []
    for i in range(26):
        if not mask >> i & 1:
            continue
        letter = chr(65 + i)
        t = _win_drive_type(letter)
        unc = ""
        if t == 4:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                n = ctypes.c_uint32(1024)
                if ctypes.windll.mpr.WNetGetConnectionW(letter + ":", buf, ctypes.byref(n)) == 0:  # type: ignore[attr-defined]
                    unc = buf.value
            except Exception:  # noqa: BLE001
                pass
        out.append({"letter": letter, "type": str(t), "unc": unc})
    return out


def places() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()

    def add(name: str, path: str, kind: str = "folder", check: bool = True) -> None:
        if not path or path in seen:
            return
        if check and not _probe(path):
            return
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
        try:
            drives = _win_drives()
        except Exception:  # noqa: BLE001 - нет ctypes.windll: перебор букв
            drives = [{"letter": c, "type": "0", "unc": ""} for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        for d in drives:
            drive = d["letter"] + ":\\"
            if d["type"] == "4":  # сетевой: не опрашиваем (может не отвечать), ошибку покажет сам переход
                add("%s: %s" % (d["letter"], d["unc"]) if d["unc"] else d["letter"] + ":", drive, "network", check=False)
            elif d["type"] in ("2", "5") and d["letter"] in "AB":
                continue
            else:
                try:
                    ok = bool(_with_timeout(os.path.exists, PROBE_TIMEOUT, drive))
                except (PathTimeout, OSError):
                    ok = False
                if ok:
                    add(d["letter"] + ":", drive, "drive", check=False)
    else:
        add("Корень /", "/", "drive")
        add("/mnt", "/mnt", "drive")
        add("/media", "/media", "drive")
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        run_media = os.path.join("/run/media", user) if user else "/run/media"
        add(run_media, run_media, "drive")
        for m in net_mounts():  # смонтированные cifs/nfs/sshfs: без опроса, чтобы не зависнуть
            base = os.path.basename(m["path"].rstrip("/")) or m["path"]
            add("%s (%s)" % (base, m["dev"]), m["path"], "network", check=False)
        for g in _gvfs_dirs():
            if _probe(g):
                try:
                    names = sorted(_with_timeout(os.listdir, PROBE_TIMEOUT, g))
                except (PathTimeout, OSError):
                    names = []
                for n in names:
                    add(n, os.path.join(g, n), "network", check=False)
    return out


# ---------- список папки ----------

def _parse_filter(filt: str) -> List[str]:
    return [("." + e.strip().lstrip(".*").lower()) for e in filt.replace(",", " ").split() if e.strip().lstrip(".*")]


_cache: Dict[str, Any] = {}  # путь -> (время, записи); только для сетевых папок
_dead: Dict[str, float] = {}  # путь -> когда снова можно опрашивать


def _fmt_mtime(ts: Optional[float]) -> str:
    try:
        return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
    except (OSError, ValueError, OverflowError):
        return ""


_POOL_WORKERS = 16


def _scan(path: str, light: bool, started: float, budget: float):
    """Прочитать папку: сначала быстрый проход scandir (только имена), затем, где нужно, параллельно тип и stat.

    light=True (сеть и незнакомые ФС): размер и дату не читаем вовсе (подгрузятся позже для видимых строк),
    права на папки не проверяем. Если сервер не отдаёт тип записи (DT_UNKNOWN), is_dir() — это stat на каждую
    запись, поэтому такие запросы идут пачкой по 16 потоков, а не по одному.
    """
    from concurrent.futures import ThreadPoolExecutor
    entries: List["os.DirEntry[str]"] = []
    truncated = False
    with os.scandir(path) as it:
        while True:
            if time.monotonic() - started > budget:
                truncated = True
                break
            try:
                entries.append(next(it))
            except StopIteration:
                break
            except OSError:
                break

    def kind(e: "os.DirEntry[str]") -> Any:
        try:
            is_dir = e.is_dir()
        except OSError:
            is_dir = False
        size = mt = None
        locked = False
        if not light:
            try:
                st = e.stat()
                size, mt = st.st_size, st.st_mtime
            except OSError:
                locked = True
            if is_dir and not locked:
                locked = not os.access(e.path, os.R_OK | os.X_OK)
        return {"name": e.name, "dir": is_dir, "size": size, "mt": mt, "locked": locked}

    if light and len(entries) > 32:
        with ThreadPoolExecutor(_POOL_WORKERS) as pool:
            raw = list(pool.map(kind, entries))
    else:
        raw = [kind(e) for e in entries]
    return raw, truncated


def _stat_one(path: str, name: str) -> Any:
    try:
        st = os.stat(os.path.join(path, name))
        return st.st_size, st.st_mtime, stat_mod.S_ISDIR(st.st_mode), False
    except OSError:
        return 0, None, False, True


def _stat_many(path: str, names: List[str]) -> List[Any]:
    from concurrent.futures import ThreadPoolExecutor
    if len(names) < 8:
        return [_stat_one(path, n) for n in names]
    with ThreadPoolExecutor(_POOL_WORKERS) as pool:
        return list(pool.map(lambda n: _stat_one(path, n), names))


def _fill_stats(path: str, raw: List[Dict[str, Any]], started: float, budget: float) -> bool:
    """Дочитать размер и дату у записей без них (сеть), параллельно. True — не уложились во время."""
    todo = [r for r in raw if r["mt"] is None and not r["locked"]]
    for i in range(0, len(todo), 200):
        if time.monotonic() - started > budget:
            return True
        chunk = todo[i:i + 200]
        for r, (size, mt, _isdir, bad) in zip(chunk, _stat_many(path, [r["name"] for r in chunk])):
            if bad:
                r["locked"] = True
            else:
                r["size"], r["mt"] = size, mt
    return False


def stat_items(path: str, names: List[str]) -> Dict[str, Dict[str, Any]]:
    """Размер и дата для выбранных имён (окно просит для видимых строк, когда папка прочитана без stat)."""
    path = os.path.normpath(path)
    names = [n for n in names[:300] if os.sep not in n and not (os.altsep and os.altsep in n)]
    out: Dict[str, Dict[str, Any]] = {}
    for n, (size, mt, is_dir, bad) in zip(names, _stat_many(path, names)):
        out[n] = {"size": 0, "mtime": "", "locked": True} if bad else {"size": 0 if is_dir else size, "mtime": _fmt_mtime(mt)}
    return out


def list_dir(path: str, filt: str = "", hidden: bool = False, query: str = "", sort: str = "name",
             desc: bool = False, offset: int = 0, limit: int = DEFAULT_LIMIT,
             budget: float = TIME_BUDGET, only_dirs: bool = False, fresh: bool = False) -> Dict[str, Any]:
    """Содержимое папки: сначала папки, затем файлы. Ошибка доступа — поле «error», а не исключение.

    Сетевая папка читается «легко» (без stat на каждый элемент; размер и дата подгружаются позже) и
    кладётся в кэш: повторное открытие мгновенное (cached=True), окно затем просит свежий листинг (fresh=True).
    """
    path = os.path.normpath(path) if path else ""
    res = {"path": path, "parent": "", "items": [], "total": 0, "offset": offset, "truncated": False,
           "error": "", "network": False, "cached": False, "lazy": False, "ms": 0}
    if not path:
        res["error"] = "Папка не найдена: —"
        return res
    parent = os.path.dirname(path)
    res["parent"] = parent if parent and parent != path else ""
    net = is_network(path)
    light = net or not is_known_local(path)  # сеть и незнакомые ФС читаем без stat на каждую запись
    res["network"] = net
    started = time.monotonic()
    raw = None
    truncated = False
    if light and not fresh:
        hit = _cache.get(path)
        if hit and time.monotonic() - hit[0] < CACHE_MAX_AGE:
            raw, truncated = hit[1], hit[2]
            res["cached"] = True
    if raw is None:
        try:
            raw, truncated = _scan(path, light, started, budget)
            res["ms"] = int((time.monotonic() - started) * 1000)
        except PermissionError:
            res["error"] = "Нет доступа к папке"
            return res
        except (FileNotFoundError, NotADirectoryError):
            res["error"] = "Папка не найдена: %s" % path
            return res
        except OSError as e:
            res["error"] = "Папка недоступна: %s" % (e.strerror or e)
            return res
        if light:
            with _lock:
                _cache[path] = (time.monotonic(), raw, truncated)
                while len(_cache) > CACHE_MAX:
                    _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
    exts = _parse_filter(filt)
    q = query.strip().lower()
    rows = []
    for r in raw:
        name = r["name"]
        if not hidden and (name.startswith(".") or name.startswith("~$")):
            continue
        if q and q not in name.lower():
            continue
        if not r["dir"]:
            if only_dirs:
                continue
            if exts and os.path.splitext(name)[1].lower() not in exts:
                continue
        rows.append(r)
    if light and sort in ("size", "mtime"):  # сортировка по полям, которых ещё нет: дочитываем (в пределах времени)
        if _fill_stats(path, rows, started, budget):
            truncated = True
    key = {"size": lambda x: x["size"] or 0, "mtime": lambda x: x["mt"] or 0}.get(sort, lambda x: x["name"].lower())
    folders = sorted([x for x in rows if x["dir"]], key=key, reverse=desc)
    files = sorted([x for x in rows if not x["dir"]], key=key, reverse=desc)
    rows = folders + files
    res["total"] = len(rows)
    res["truncated"] = truncated
    items = []
    for r in rows[offset:offset + limit]:
        name = r["name"]
        has = r["mt"] is not None or r["size"] is not None
        if not has and not r["locked"]:
            res["lazy"] = True
        items.append({
            "name": name, "dir": r["dir"],
            "size": 0 if r["dir"] or r["size"] is None else r["size"],
            "mtime": _fmt_mtime(r["mt"]),
            "ext": "" if r["dir"] else os.path.splitext(name)[1].lower().lstrip("."),
            "locked": r["locked"],
        })
    res["items"] = items
    return res


def browse(path: str, *args: Any, timeout: float = LIST_TIMEOUT, **kw: Any) -> Dict[str, Any]:
    """list_dir с ограничением по времени: недоступный диск возвращает ошибку, а не вешает окно."""
    path = os.path.normpath(path) if path else ""
    now = time.monotonic()
    if _dead.get(path, 0) > now:
        return {"path": path, "parent": os.path.dirname(path) if os.path.dirname(path) != path else "", "items": [],
                "total": 0, "offset": 0, "truncated": False, "network": True, "cached": False, "lazy": False,
                "error": "Диск не отвечает. Проверьте подключение и повторите через несколько секунд."}
    try:
        return _with_timeout(list_dir, timeout, path, *args, **kw)
    except PathTimeout:
        _dead[path] = time.monotonic() + DEAD_BACKOFF
        return {"path": path, "parent": os.path.dirname(path) if os.path.dirname(path) != path else "", "items": [],
                "total": 0, "offset": 0, "truncated": False, "network": True, "cached": False, "lazy": False,
                "error": "Диск не отвечает за %d с. Проверьте подключение и повторите." % int(timeout)}


# ---------- маршруты ----------

def _int(v: Optional[str], default: int) -> int:
    try:
        return max(0, int(v)) if v is not None else default
    except ValueError:
        return default


def _resolve_start(path: str) -> str:
    """Пустой путь — последняя папка или домашняя; путь к файлу — его папка (сетевые пути не опрашиваем)."""
    if not path:
        return get_last()["dir"] or os.path.expanduser("~")
    if is_known_local(path) and os.path.isfile(path):  # на сетевых и незнакомых ФС лишний запрос не делаем
        return os.path.dirname(path)
    return path


async def _list(request: Request) -> JSONResponse:
    from starlette.concurrency import run_in_threadpool
    q = request.query_params
    path = await run_in_threadpool(_resolve_start, q.get("path") or "")
    res = await run_in_threadpool(
        browse, path, q.get("filter") or "", q.get("hidden") in ("1", "true"), q.get("q") or "",
        q.get("sort") or "name", q.get("desc") in ("1", "true"), _int(q.get("offset"), 0),
        min(_int(q.get("limit"), DEFAULT_LIMIT), 5000), TIME_BUDGET, q.get("kind") == "folder",
        q.get("fresh") in ("1", "true"))
    return JSONResponse(res)


async def _stat(request: Request) -> JSONResponse:
    from starlette.concurrency import run_in_threadpool
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    names = [str(n) for n in (body.get("names") or []) if isinstance(n, str)]
    path = str(body.get("path") or "")
    try:
        out = await run_in_threadpool(_with_timeout, stat_items, LIST_TIMEOUT, path, names)
    except PathTimeout:
        out = {}
    return JSONResponse({"stats": out})


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
    path = request.query_params.get("path") or ""
    if not path or not os.path.isfile(path):
        return JSONResponse({"error": "Файл не найден: %s" % (path or "—")}, status_code=404)
    if not os.access(path, os.R_OK):
        return JSONResponse({"error": "Нет доступа к файлу"}, status_code=403)
    return FileResponse(path, media_type="application/octet-stream")


async def _win(request: Request) -> JSONResponse:
    if request.method == "POST":
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return JSONResponse(set_win(body.get("w"), body.get("h")))
    return JSONResponse(get_win())


async def _favorites(request: Request) -> JSONResponse:
    if request.method == "POST":
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        to = body.get("to")
        return JSONResponse(edit_favorites(str(body.get("action") or ""), str(body.get("path") or ""),
                                           str(body.get("name") or ""), to if isinstance(to, int) else -1))
    return JSONResponse(get_favorites())


async def _visit(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        add_visit(str(body.get("path") or ""))
    return JSONResponse(get_favorites())


def routes() -> List[Route]:
    return [
        Route("/api/fs/file", _file),
        Route("/api/fs/list", _list),
        Route("/api/fs/places", _places),
        Route("/api/fs/stat", _stat, methods=["POST"]),
        Route("/api/fs/last", _last, methods=["GET", "POST"]),
        Route("/api/fs/win", _win, methods=["GET", "POST"]),
        Route("/api/fs/favorites", _favorites, methods=["GET", "POST"]),
        Route("/api/fs/visit", _visit, methods=["POST"]),
    ]
