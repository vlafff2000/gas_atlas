"""Плашка ресурсов в левой панели: ОЗУ программы, размер проектов, занятые потоки процессора.

Только стандартная библиотека (psutil на РЕД ОС 7.3 не ставим). Размер папок считается в фоне и кэшируется на
``TTL`` секунд, поэтому запрос плашки никогда не ждёт обхода диска. Файл один и тот же в Газовом атласе
(``atlas/resources.py``) и в остальных программах (``pxg_core/resources.py``).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, Optional

TTL = 120.0                  # размер папок пересчитываем не чаще раза в 2 минуты
WALK_BUDGET = 20.0           # обход одной папки дольше этого срока прерываем: показываем «не меньше N»
_lock = threading.Lock()
_sizes: Dict[str, Dict[str, Any]] = {}
_cpu: Dict[str, float] = {"wall": 0.0, "cpu": 0.0, "busy": 0.0}


def folder_size(path: str, budget: float = WALK_BUDGET) -> tuple[int, bool]:
    """Размер папки, байт, и признак «посчитано полностью». Ссылки не разворачиваются, ошибки доступа пропускаются."""
    total, stop = 0, time.monotonic() + budget
    stack = [path]
    while stack:
        if time.monotonic() > stop:
            return total, False
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, True


def cached_size(path: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Последнее известное значение; если оно устарело, в фоне запускается пересчёт. Первый раз вернёт None."""
    if not path:
        return None
    now = time.monotonic() if now is None else now
    with _lock:
        item = _sizes.get(path)
        if item and (item["busy"] or now - item["at"] < TTL):
            return item["value"]
        if item is None:
            item = _sizes[path] = {"value": None, "at": 0.0, "busy": False}
        item["busy"] = True
        old = item["value"]

    def work() -> None:
        size, full = folder_size(path)
        with _lock:
            _sizes[path] = {"value": {"bytes": size, "full": full}, "at": time.monotonic(), "busy": False}

    threading.Thread(target=work, daemon=True, name="resource-size").start()
    return old


def _rss_of(pid: str) -> int:
    try:
        with open("/proc/%s/statm" % pid, encoding="ascii") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return 0


def memory_bytes() -> Optional[int]:
    """Память программы: резидентная память этого процесса и его дочерних (рабочие процессы расчётов)."""
    if os.path.isdir("/proc/self"):
        me = str(os.getpid())
        total = _rss_of("self")
        try:
            for pid in os.listdir("/proc"):
                if not pid.isdigit() or pid == me:
                    continue
                try:
                    with open("/proc/%s/stat" % pid, encoding="ascii", errors="replace") as f:
                        fields = f.read().rsplit(")", 1)[1].split()
                    if int(fields[1]) == int(me):          # поле 4 исходной строки — родитель
                        total += _rss_of(pid)
                except (OSError, ValueError, IndexError):
                    continue
        except OSError:
            pass
        return total or None
    try:                                                     # Windows
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD), ("peak", ctypes.c_size_t),
                        ("working", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                        ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("pagefile", ctypes.c_size_t),
                        ("peakpagefile", ctypes.c_size_t)]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        handle = ctypes.windll.kernel32.GetCurrentProcess()          # type: ignore[attr-defined]
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb):  # type: ignore[attr-defined]
            return int(c.working)
    except Exception:
        pass
    return None


def total_memory_bytes() -> Optional[int]:
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        import ctypes

        class Mem(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong),
                        ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
        m = Mem()
        m.length = ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):    # type: ignore[attr-defined]
            return int(m.total)
    except Exception:
        pass
    return None


def cpu_busy() -> float:
    """Сколько потоков процессора занято программой: рост процессорного времени / прошедшее время между запросами."""
    wall, cpu = time.monotonic(), time.process_time()
    with _lock:
        if _cpu["wall"] and wall - _cpu["wall"] >= 0.5:
            _cpu["busy"] = max(0.0, (cpu - _cpu["cpu"]) / (wall - _cpu["wall"]))
            _cpu["wall"], _cpu["cpu"] = wall, cpu
        elif not _cpu["wall"]:
            _cpu["wall"], _cpu["cpu"] = wall, cpu
        return _cpu["busy"]


def snapshot(current: str = "", everything: str = "", workers: Optional[Callable[[], int]] = None) -> Dict[str, Any]:
    """Данные плашки. ``current`` — папка открытого проекта, ``everything`` — папка со всеми проектами (можно пустую)."""
    threads = os.cpu_count() or 1
    return {
        "ram": {"used": memory_bytes(), "total": total_memory_bytes()},
        "project": cached_size(current),
        "all": cached_size(everything) if everything else None,
        "cpu": {"busy": round(cpu_busy(), 2), "threads": threads, "workers": workers() if workers else None},
    }
