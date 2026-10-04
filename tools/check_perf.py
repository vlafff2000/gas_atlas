"""Проверка скорости Atlas 6 на большом демо-объекте: время каждого расчёта против бюджета в ``tools/perf_budget.json``.

    python tools/check_perf.py            # создать большое демо, замерить, сравнить с бюджетом; код 1 — бюджет превышен
    python tools/check_perf.py --update   # записать бюджет: 3 × замеренное время (не меньше 2 с)

Замер — тот же, что в ``tools/benchmark_large_demo.py`` (первый запрос раздела, серверная часть, без браузера).
Бюджет с запасом: CI-машина медленнее обычной, ловится не дрожание, а настоящая регрессия (минуты вместо секунд).
Итог пишется и в сводку задачи GitHub Actions (``GITHUB_STEP_SUMMARY``).
"""
import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
BUDGET = ROOT / 'tools' / 'perf_budget.json'
FACTOR, FLOOR = 3.0, 2.0


def measure():
    from benchmark_large_demo import bench_atlas
    from app.core.demo_large import create_large_demo
    from app.core.storage import Store
    with tempfile.TemporaryDirectory(prefix='gas_atlas_perf_') as tmp:
        os.environ['GAS_ATLAS_STORAGE'] = tmp
        started = time.perf_counter()
        pid = create_large_demo(Store(tmp))
        print('Большое демо создано за %.1f с' % (time.perf_counter() - started))
        return bench_atlas(tmp, pid)


def compare(rows, budget):
    """Строки отчёта ``(название, время, бюджет, статус)``; статус: ok / медленно / ошибка / без бюджета."""
    report = []
    for name, took, _size, note in rows:
        if '(повтор)' in name:
            continue
        limit = budget.get(name)
        if note and note.startswith('HTTP '):
            status = 'ошибка'
        elif limit is None:
            status = 'без бюджета'
        else:
            status = 'ok' if took <= limit else 'медленно'
        report.append((name, took, limit, status))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--update', action='store_true', help='записать бюджет по текущему замеру')
    args = parser.parse_args(argv)
    rows = measure()
    if args.update:
        budget = {n: max(FLOOR, float(math.ceil(t * FACTOR))) for n, t, _, _ in rows if '(повтор)' not in n}
        BUDGET.write_text(json.dumps(budget, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf8')
        print('Бюджет записан: %s (%d разделов)' % (BUDGET.relative_to(ROOT), len(budget)))
        return 0
    budget = json.loads(BUDGET.read_text(encoding='utf8'))
    report = compare(rows, budget)
    lines = ['| Раздел | Время, с | Бюджет, с | Итог |', '|---|---:|---:|---|']
    for name, took, limit, status in report:
        lines.append('| %s | %.2f | %s | %s |' % (name, took, '' if limit is None else '%g' % limit, status))
    text = '\n'.join(lines)
    print(text)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf8') as f:
            f.write('### Скорость на большом демо-объекте\n\n' + text + '\n')
    missing = sorted(set(budget) - {n for n, *_ in report})
    if missing:
        print('\nНет замера для: ' + '; '.join(missing))
    bad = [r for r in report if r[3] in ('медленно', 'ошибка')]
    for name, took, limit, status in bad:
        print('ПРЕВЫШЕНИЕ: %s — %.2f с при бюджете %s с (%s)' % (name, took, limit, status))
    return 1 if bad or missing else 0


if __name__ == '__main__':
    sys.exit(main())
