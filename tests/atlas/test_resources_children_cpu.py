"""Плашка ресурсов: занятость потоков учитывает рабочие процессы расчётов, а не только главный."""
import multiprocessing
import time

import pytest

from atlas import resources


def _burn(seconds):
    end = time.process_time() + seconds
    while time.process_time() < end:
        pass


@pytest.mark.skipif(not hasattr(__import__('os'), 'getppid') or __import__('sys').platform.startswith('win'), reason='нужен /proc')
def test_busy_counts_worker_processes():
    resources.cpu_busy()
    ctx = multiprocessing.get_context('spawn')
    procs = [ctx.Process(target=_burn, args=(1.5,)) for _ in range(2)]
    for p in procs:
        p.start()
    time.sleep(1.0)
    busy = resources.cpu_busy()
    for p in procs:
        p.join()
    assert busy >= 1.2, busy        # два процесса считают, главный спит
