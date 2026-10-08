"""Создать большой демонстрационный проект в общем хранилище 5.8 / 6 (для проверки скорости).

Проект появляется в списке проектов обеих версий. По умолчанию: отбор и закачка 1 000 000 строк, ГДИ 300 000,
реагирование 200 000, кроссплот давлений 500 000 пар. Данные синтетические и строятся заново при каждом запуске,
в git они не хранятся.

    python tools/make_large_demo.py
    python tools/make_large_demo.py --production 200000 --gdi 50000 --response 0 --pressure 100000
    GAS_ATLAS_STORAGE=/путь/к/storage python tools/make_large_demo.py

0 у набора (кроме отбора и закачки) — набор не создаётся. Работает на Python 3.8+.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atlas.engine.core.config import STORAGE  # noqa: E402
from atlas.engine.core.demo_large import DEFAULTS, create_large_demo  # noqa: E402
from atlas.engine.core.storage import Store  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--production', type=int, default=DEFAULTS['production'], help='строк отбора и закачки')
    parser.add_argument('--gdi', type=int, default=DEFAULTS['gdi'], help='точек ГДИ')
    parser.add_argument('--response', type=int, default=DEFAULTS['response'], help='замеров реагирования')
    parser.add_argument('--pressure', type=int, default=DEFAULTS['pressure_match'], help='пар кроссплота давлений')
    parser.add_argument('--seed', type=int, default=2026, help='зерно генератора (одинаковое — одинаковые данные)')
    parser.add_argument('--name', default=None, help='название проекта')
    parser.add_argument('--storage', default=str(STORAGE), help='папка хранилища (по умолчанию общая с 5.8)')
    args = parser.parse_args(argv)
    started = time.time()
    store = Store(Path(args.storage))
    pid = create_large_demo(store, name=args.name, production=args.production, gdi=args.gdi,
                            response=args.response, pressure_match=args.pressure, seed=args.seed)
    tables = store.manifest(pid)['tables']
    print('Создан проект «%s» (%s) за %.1f с' % (store.manifest(pid)['name'], pid, time.time() - started))
    for name, rows in tables.items():
        print('  %-15s %12s' % (name, format(rows, ',').replace(',', ' ')))
    return pid


if __name__ == '__main__':
    main()
