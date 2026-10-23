"""Независимые задания (например, файлы при загрузке) раздаются процессам: ядра до 16, PXG_WORKERS задаёт число вручную.

Мало заданий (PXG_PARALLEL_MIN, по умолчанию 4) — считаем в этом же процессе: запуск процессов дороже. Сбой пула
(процесс убит из-за нехватки памяти, не запустился) — те же задания подряд, а не ошибка пользователю.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from typing import Any, Callable, List, Optional, Sequence

MAX_WORKERS = 16
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


def map_jobs(fn: Callable[[Any], Any], jobs: Sequence[Any], mb_per_worker: float = 0.0, workers: Optional[int] = None) -> List[Any]:
    """[fn(job) для job из jobs] по порядку; fn — функция верхнего уровня модуля (picklable)."""
    jobs = list(jobs)
    n = min(default_workers(mb_per_worker) if workers is None else max(1, workers), len(jobs))
    if n < 2 or len(jobs) < int(os.environ.get('PXG_PARALLEL_MIN') or 4):
        return [fn(j) for j in jobs]
    try:
        with ProcessPoolExecutor(max_workers=n, mp_context=get_context('spawn')) as ex:
            return list(ex.map(fn, jobs, chunksize=1))
    except (BrokenProcessPool, MemoryError, PermissionError):
        log.exception('%d процессов не справились, считаем в одном', n)
        return [fn(j) for j in jobs]
