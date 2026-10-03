"""Замер скорости Atlas 6 и 5.8 на большом демо-объекте (``tools/make_large_demo.py``).

    python tools/benchmark_large_demo.py              # создать большое демо во временной папке и замерить обе версии
    python tools/benchmark_large_demo.py --only 6     # только Atlas 6 (Python 3.10+)
    python tools/benchmark_large_demo.py --only 5.8   # только 5.8 (страницы через streamlit.testing)

Каждая версия меряется в отдельном процессе: время — серверная часть (расчёт и JSON / отрисовка Streamlit), без браузера;
память — пик RSS процесса. Данные создаются заново, в git не попадают.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ATLAS_MODULES = ('overview', 'production', 'histograms', 'gdi', 'response', 'pressure', 'fund', 'groups', 'wells',
                 'exclusions', 'filter_history')
PAGES_58 = ('Обзор', 'Производительность скважин', 'Гистограммы по эксплуатации скважин', 'ГДИ', 'Графики реагирования',
            'Кроссплот давлений', 'Поскважинный анализ', 'Аналитика фонда', 'Группы', 'Исключенные точки')


def peak_mb():
    try:
        import resource
    except ImportError:                     # Windows
        return float('nan')
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def bench_atlas(storage, pid):
    from starlette.testclient import TestClient
    from atlas.api import create_app
    from atlas.projects import Projects
    client = TestClient(create_app(Projects(storage)))
    out = []

    def timed(label, method, url, body=None):
        started = time.perf_counter()
        r = client.request(method, url, json=body)
        took = time.perf_counter() - started
        note = None if r.status_code < 400 else 'HTTP %d: %s' % (r.status_code, r.text[:120])
        if label:
            notes = [n['text'] for n in r.json().get('notes', [])] if r.status_code == 200 and method == 'POST' else []
            shown = [n for n in notes if 'ДЕМОНСТРАЦ' not in n and 'Рабочие правила' not in n and 'Проект «' not in n]
            out.append((label, took, len(r.content), note or ('; '.join(shown)[:90] or None)))
        return r.json()

    def options(module, param, params):
        return timed(None, 'POST', '/api/modules/%s/options' % module, {'project': pid, 'param': param, 'params': params})

    def run(label, module, params, repeat=True):
        timed('%s · %s' % (module, label), 'POST', '/api/modules/%s/run' % module, {'project': pid, 'params': params})
        if repeat:      # тот же запрос ещё раз: кэш результатов
            timed('%s · %s (повтор)' % (module, label), 'POST', '/api/modules/%s/run' % module,
                  {'project': pid, 'params': params})

    timed('Список проектов', 'GET', '/api/projects')
    run('открытие проекта (первое чтение данных)', 'overview', {}, repeat=False)
    groups = options('production', 'groups', {})
    wells = options('production', 'wells', {'groups': groups})
    periods = options('production', 'periods', {})
    run('10 скважин, 4 последних сезона', 'production', {'groups': groups, 'wells': wells[:10], 'periods': periods[-4:]})
    run('все %d скважин, все сезоны' % len(wells), 'production', {'groups': groups, 'wells': wells, 'periods': periods})
    run('все скважины, последний сезон', 'histograms', {'groups': groups, 'wells': wells, 'periods': periods[-1:]})
    run('все скважины, все сезоны', 'histograms', {'groups': groups, 'wells': wells, 'periods': periods})
    run('по умолчанию', 'gdi', {})
    run('все скважины, последнее исследование', 'gdi', {'wells': wells, 'last_n': 1})
    obs = options('response', 'wells', {})
    run('все %d наблюдательных скважин' % len(obs), 'response', {'wells': obs})
    run('все пары', 'pressure', {})
    run('все сезоны', 'fund', {'periods': periods})
    run('последний сезон', 'groups', {'periods': periods[-1:]})
    run('одна скважина, все сезоны', 'wells', {'wells': wells[:1], 'periods': periods})
    run('по умолчанию', 'exclusions', {}, repeat=False)
    run('по умолчанию', 'filter_history', {}, repeat=False)
    return out


def bench_58(storage, pid):
    from streamlit.testing.v1 import AppTest
    from app.core import config
    from app.core.storage import Store
    from app.ui import navigation
    store = Store(storage)
    m = store.manifest(pid)
    store.commit(pid, settings={**m['settings'], 'visible_pages': navigation.PAGES})
    config.STORAGE = Path(storage)
    out = []
    started = time.perf_counter()
    at = AppTest.from_file(str(ROOT / 'app' / 'main.py'), default_timeout=900).run()
    out.append(('Запуск и первая страница', time.perf_counter() - started, None, at.exception[0].message if at.exception else None))
    for page in PAGES_58:
        for attempt in ('первый', 'повтор'):
            started = time.perf_counter()
            try:
                at.sidebar.radio[0].set_value(page).run()
                note = at.exception[0].message[:120] if at.exception else None
            except Exception as e:      # таймаут AppTest и т. п.
                note = repr(e)[:120]
            out.append(('%s (%s)' % (page, attempt), time.perf_counter() - started, None, note))
    return out


def child(version, storage, pid):
    os.environ['GAS_ATLAS_STORAGE'] = storage
    rows = bench_atlas(storage, pid) if version == '6' else bench_58(storage, pid)
    print(json.dumps({'rows': rows, 'peak_mb': peak_mb()}, ensure_ascii=False))


def report(version, result):
    print('\n%s — пик памяти %.0f МБ' % ('Atlas 6' if version == '6' else '5.8', result['peak_mb']))
    for name, took, size, note in result['rows']:
        size_text = '' if size is None else '%8.1f МБ' % (size / 2 ** 20)
        print('  %-44s %7.2f с %s %s' % (name, took, size_text, note or ''))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--only', choices=('6', '5.8'))
    parser.add_argument('--storage', help='готовое хранилище (по умолчанию временная папка)')
    parser.add_argument('--project', help='id готового проекта в хранилище')
    parser.add_argument('--verbose', action='store_true', help='показывать журнал и предупреждения версий')
    parser.add_argument('--child', nargs=3, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return child(*args.child)
    with tempfile.TemporaryDirectory(prefix='gas_atlas_large_demo_') as tmp:
        storage, pid = args.storage or tmp, args.project
        if not pid:
            from app.core.demo_large import create_large_demo
            from app.core.storage import Store
            started = time.perf_counter()
            pid = create_large_demo(Store(storage))
            print('Большое демо создано за %.1f с' % (time.perf_counter() - started))
        for version in ([args.only] if args.only else ['6', '5.8']):
            done = subprocess.run([sys.executable, __file__, '--child', version, storage, pid],
                                  stdout=subprocess.PIPE, stderr=None if args.verbose else subprocess.DEVNULL,
                                  universal_newlines=True, cwd=str(ROOT))
            lines = [x for x in done.stdout.splitlines() if x.startswith('{')]
            if done.returncode or not lines:
                print('\n%s: замер не удался (код %d), подробности — с ключом --verbose' % (version, done.returncode))
                continue
            report(version, json.loads(lines[-1]))


if __name__ == '__main__':
    main()
