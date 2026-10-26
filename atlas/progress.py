"""Что Атлас считает сейчас: список выполняемых запросов для шкалы выполнения в окне (web/src/BusyBar.tsx).

Тот же подход, что ``pxg_core/progress.py`` в all_scripts. Задачу на каждый запрос ``/api/*`` открывает ``runlog.RequestLog``
(название — по адресу, ``label_for``); долгие этапы могут отмечать шаги: ``progress.report(done, total, text)`` /
``progress.advance()`` (``parallel.map_jobs`` делает это сам). Окно раз в секунду читает ``GET /api/progress``.
"""
from __future__ import annotations

import contextlib
import contextvars
import itertools
import re
import threading
import time
from typing import Iterator, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

_lock = threading.Lock()
_tasks: dict[int, dict] = {}
_ids = itertools.count(1)
_current: contextvars.ContextVar = contextvars.ContextVar('atlas_progress_task', default=None)

_LABELS = [
    (r'/modules/[^/]+/(run|table|window)', 'Расчёт раздела'),
    (r'/modules/[^/]+/export', 'Выгрузка раздела'),
    (r'/import/ggh', 'Разбор ГГХ'),
    (r'/import/pressure', 'Разбор замеров давления'),
    (r'/import/(apply|check|fix|table)', 'Загрузка данных в проект'),
    (r'/import/', 'Чтение файла импорта'),
    (r'/folder/(load|scan)', 'Чтение папки проекта'),
    (r'/passport', 'Паспорт скважины'),
    (r'/exports', 'Подготовка выгрузки'),
    (r'/backup|/restore', 'Резервная копия проекта'),
    (r'/corrected-db', 'Исправленная БД'),
    (r'/exclusions', 'Исключённые точки'),
    (r'/state/', 'Расчёт раздела'),
]


def label_for(path: str) -> str:
    for rx, label in _LABELS:
        if re.search(rx, path):
            return label
    return 'Выполняется запрос'


class Task:
    def __init__(self, label: str, total: Optional[int] = None):
        self.id = next(_ids)
        self.data = {'id': self.id, 'label': label, 'started': time.time(), 'done': 0, 'total': total, 'text': ''}

    def report(self, done: Optional[int] = None, total: Optional[int] = None, text: Optional[str] = None) -> None:
        with _lock:
            if done is not None:
                self.data['done'] = done
            if total is not None:
                self.data['total'] = total
            if text is not None:
                self.data['text'] = text

    def advance(self, n: int = 1, text: Optional[str] = None) -> None:
        with _lock:
            self.data['done'] += n
            if text is not None:
                self.data['text'] = text


@contextlib.contextmanager
def task(label: str, total: Optional[int] = None) -> Iterator[Task]:
    t = Task(label, total)
    with _lock:
        _tasks[t.id] = t.data
    token = _current.set(t)
    try:
        yield t
    finally:
        _current.reset(token)
        with _lock:
            _tasks.pop(t.id, None)


def report(done: Optional[int] = None, total: Optional[int] = None, text: Optional[str] = None) -> None:
    t = _current.get()
    if t is not None:
        t.report(done, total, text)


def advance(n: int = 1, text: Optional[str] = None) -> None:
    t = _current.get()
    if t is not None:
        t.advance(n, text)


def active() -> list[dict]:
    now = time.time()
    with _lock:
        return [dict(d, elapsed=round(now - d['started'], 1)) for d in _tasks.values()]


async def progress(request: Request) -> JSONResponse:
    return JSONResponse({'tasks': active()})


def routes() -> list[Route]:
    return [Route('/api/progress', progress)]
