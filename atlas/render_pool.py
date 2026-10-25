"""Графики плана выгрузки строятся и рисуются процессами на всех ядрах (``PXG_WORKERS``; лимит по памяти — ``MB_PER_WORKER``).

Задания плана (``FigureJob``) и общие таблицы передаются каждому процессу один раз; дальше по процессу ходят только номера заданий
и небольшие результаты (PNG, байты SVG/PDF, подписи). Результат тот же, что при построении подряд: порядок сохраняется.
"""
from __future__ import annotations

import itertools
from typing import Any, Callable, Iterator, Optional, Sequence

import pandas as pd

from . import parallel
from .engine.core import performance

MIN_JOBS = 24              # меньше заданий быстрее посчитать здесь: запуск процессов и передача им таблиц занимают секунды
MB_PER_WORKER = 1500       # процессу нужна своя копия таблиц эксплуатации
_STATE: dict = {}
_TOKENS = itertools.count(1)


def job_frames(jobs: Sequence[Any]) -> list:
    """Таблицы, на которых строятся графики (аргументы построителей заданий), без повторов."""
    out = {}
    for job in jobs:
        while hasattr(job, '_job'):
            job = job._job
        for arg in getattr(getattr(job, 'factory', None), 'args', ()):
            if isinstance(arg, pd.DataFrame):
                out[id(arg)] = arg
    return list(out.values())


def _init(token, jobs, indexed, work, params) -> None:
    """Один раз в процессе: задания, функция работы и параметры. Индекс таблицы привязан к объекту (``id``) — после передачи
    процессу объект новый, поэтому привязываем заново (только таблицам, у которых индекс был свой): кривые считаются по индексу,
    а не по всей таблице. Чужой индекс (у копии он остаётся от исходной таблицы) не привязывается."""
    for frame in indexed:
        frame.attrs['_atlas_index'].owner = id(frame)
    _STATE[token] = (jobs, work, params)


def _call(task):
    token, i, payload = task
    try:
        jobs, work, params = _STATE[token]
        return work(jobs[i], params, payload), None
    except Exception as e:
        return None, str(e)


def iter_run(jobs: Sequence[Any], work: Callable, params: Any = None, payloads: Optional[Sequence[Any]] = None,
             indices: Optional[Sequence[int]] = None) -> Iterator[tuple]:
    """(``work(job, params, payload)``, None) или (None, текст ошибки) для каждого задания по порядку, по мере готовности.

    ``work`` — функция верхнего уровня модуля; ``payloads[i]`` — данные, зависящие от задания (например, высота подписи);
    ``indices`` — какие задания считать (по умолчанию все)."""
    jobs = list(jobs)
    token = next(_TOKENS)
    tasks = [(token, i, payloads[i] if payloads is not None else None) for i in (range(len(jobs)) if indices is None else indices)]
    indexed = [f for f in job_frames(jobs) if performance.index_for(f) is not None]
    try:
        # процессу нужно время на запуск и получение таблиц: не больше процессов, чем по ~8 графиков на каждый
        workers = min(parallel.default_workers(MB_PER_WORKER), max(2, len(tasks) // 8))
        yield from parallel.iter_jobs(_call, tasks, MB_PER_WORKER, workers, initializer=_init, initargs=(token, jobs, indexed, work, params), min_jobs=MIN_JOBS)
    finally:
        _STATE.pop(token, None)


def run(jobs: Sequence[Any], work: Callable, params: Any = None, payloads: Optional[Sequence[Any]] = None,
        indices: Optional[Sequence[int]] = None) -> list:
    return list(iter_run(jobs, work, params, payloads, indices))
