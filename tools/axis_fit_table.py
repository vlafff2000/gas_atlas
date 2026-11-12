"""Случайная сверочная таблица автоподбора шкал для зеркала на экране (``web/src/axisFit.ts``).

``tests/fixtures/axis_fit_random.json`` — 300 случайных наборов шкал с ответом ``atlas/axis_fit.py``; её читают и pytest
(ответ Python не изменился), и тест интерфейса (TS даёт те же числа). После намеренной правки правил подбора:
``python tools/axis_fit_table.py`` — и посмотреть разницу в git."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TABLE = ROOT / 'tests' / 'fixtures' / 'axis_fit_random.json'
COUNT, SEED = 300, 20261112


def _value(rng: random.Random, scale: float) -> float:
    return float(f'{rng.choice([0.0, rng.uniform(-1, 1), rng.uniform(0, 1), -rng.uniform(0, 1)]) * scale:.6g}')


def _need(rng: random.Random) -> dict | None:
    if rng.random() < 0.04:
        return None
    scale = 10 ** rng.randint(-4, 7)
    lo = _value(rng, scale)
    hi = float(f'{lo + rng.choice([0.0, rng.uniform(0, 1), rng.uniform(0, 1e-3)]) * scale:.6g}')
    need: dict = {'lo': lo, 'hi': hi}
    if rng.random() < 0.05:
        need = {'lo': None, 'hi': None}
    if rng.random() < 0.3:
        need['anchor'] = True
    if rng.random() < 0.3:
        need['mode'] = rng.choice(['zero', 'data'])
    if rng.random() < 0.2:
        need['inverse'] = True
    if rng.random() < 0.12:
        need['minimum'] = _value(rng, scale)
    if rng.random() < 0.12:
        need['maximum'] = _value(rng, scale)
    if rng.random() < 0.08:
        need['step'] = float(f'{rng.choice([1, 2, 2.5, 5, 3]) * scale / 10:.6g}')
    return need


def build() -> list[dict]:
    from atlas.axis_fit import Need, fit_axes
    rng = random.Random(SEED)
    out = []
    for _ in range(COUNT):
        needs = [_need(rng) for _ in range(rng.choice([1, 1, 2, 2, 3, 5]))]
        fits = fit_axes([None if n is None else Need(**n) for n in needs])
        out.append({'needs': needs, 'expect': [None if f is None else [f.minimum, f.maximum, f.step, f.n, f.why] for f in fits]})
    return out


def main() -> int:
    TABLE.write_text('[\n' + ',\n'.join(json.dumps(c, ensure_ascii=False) for c in build()) + '\n]\n', encoding='utf-8')
    print(f'{TABLE.relative_to(ROOT)}: {COUNT} наборов')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
