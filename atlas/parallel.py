"""Независимые задания (например, файлы при загрузке) раздаются процессам: ядра до 20, PXG_WORKERS задаёт число вручную.

Мало заданий (PXG_PARALLEL_MIN, по умолчанию 4) — считаем в этом же процессе: запуск процессов дороже. Сбой пула
(процесс убит из-за нехватки памяти, не запустился) — те же задания подряд, а не ошибка пользователю.
"""
from __future__ import annotations

import logging
import os
import pickle
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from typing import Any, Callable, Iterator, List, Optional, Sequence

from . import progress

MAX_WORKERS = 20
RESERVE_MB = 1024            # столько свободной памяти оставляем системе и основной программе
log = logging.getLogger(__name__)


def _free_mb() -> Optional[float]:
    try:
        with open('/proc/meminfo', encoding='ascii') as f:
            for line in f:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    try:
        from pxg_core.workers import available_mb       # Windows: GlobalMemoryStatusEx
        return available_mb()
    except Exception:
        return None


def default_workers(mb_per_worker: float = 0.0) -> int:
    env = os.environ.get('PXG_WORKERS')
    if env and env.strip().isdigit():
        return max(1, int(env))
    n = min(os.cpu_count() or 1, MAX_WORKERS)
    free = _free_mb()
    if mb_per_worker and free is not None:
        n = min(n, max(1, int((free - RESERVE_MB) // mb_per_worker)))
    return max(1, n)


def iter_jobs(fn: Callable[[Any], Any], jobs: Sequence[Any], mb_per_worker: float = 0.0, workers: Optional[int] = None,
              initializer: Optional[Callable] = None, initargs: tuple = (), min_jobs: int = 4) -> Iterator[Any]:
    """Результаты ``fn(job)`` по порядку по мере готовности: потребитель обрабатывает их, пока процессы считают дальше
    (в памяти не копится всё сразу). fn и initializer — функции верхнего уровня модуля (picklable).

    ``initializer(*initargs)`` выполняется один раз в каждом процессе (и в этом же процессе, если считаем в нём): так общие
    большие данные передаются процессу один раз, а не с каждым заданием. Меньше ``min_jobs`` заданий считаем здесь же."""
    jobs = list(jobs)
    n = min(default_workers(mb_per_worker) if workers is None else max(1, workers), len(jobs))
    done = 0
    if n >= 2 and len(jobs) >= int(os.environ.get('PXG_PARALLEL_MIN') or min_jobs):
        try:
            progress.report(0, len(jobs))
            with ProcessPoolExecutor(max_workers=n, mp_context=get_context('spawn'), initializer=initializer, initargs=initargs) as ex:
                for res in ex.map(fn, jobs, chunksize=1):
                    done += 1
                    progress.advance()
                    yield res
            return
        except (BrokenProcessPool, MemoryError, PermissionError, pickle.PicklingError, AttributeError, TypeError):
            # процесс убит или не запустился, либо задания нельзя передать процессу (не picklable)
            log.exception('%d процессов не справились, считаем в одном', n)
    progress.report(done, len(jobs))
    if initializer:
        initializer(*initargs)
    for j in jobs[done:]:
        res = fn(j)
        progress.advance()
        yield res


def map_jobs(fn: Callable[[Any], Any], jobs: Sequence[Any], mb_per_worker: float = 0.0, workers: Optional[int] = None,
             initializer: Optional[Callable] = None, initargs: tuple = ()) -> List[Any]:
    """[fn(job) для job из jobs] по порядку (см. ``iter_jobs``)."""
    return list(iter_jobs(fn, jobs, mb_per_worker, workers, initializer, initargs))


def _star(task):
    fn, args = task
    return fn(*args)


def map_figures(fn: Callable[..., Any], arguments: Sequence[tuple], min_jobs: int = 12, mb_per_worker: float = 600) -> List[Any]:
    """[fn(*args) для args из arguments] по порядку; fn — функция верхнего уровня модуля. Мало рисунков (меньше ``min_jobs``) — здесь же:
    запуск процесса занимает секунды. Процессов не больше, чем по ~6 рисунков на каждый."""
    arguments = list(arguments)
    workers = min(default_workers(mb_per_worker), max(2, len(arguments) // 6))
    return list(iter_jobs(_star, [(fn, a) for a in arguments], mb_per_worker, workers, min_jobs=min_jobs))