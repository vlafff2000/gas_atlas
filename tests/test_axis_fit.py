"""Единый автоподбор шкал (atlas/axis_fit.py): таблица «вход → ожидаемые границы и шаг» и общие свойства.

Таблица ``tests/fixtures/axis_fit_cases.json`` — общая с экраном (зеркало ``web/src/axisFit.ts`` проверяется ею же)."""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from atlas.axis_fit import MULTS, N_MAX, N_MIN, WHY, Need, clean, fit_axes, fit_axis, is_nice, nice_step

CASES = json.loads((Path(__file__).parent / 'fixtures' / 'axis_fit_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_table(case):
    fits = fit_axes([None if n is None else Need(**n) for n in case['needs']])
    got = [None if f is None else {'min': f.minimum, 'max': f.maximum, 'step': f.step, 'n': f.n, 'why': f.why} for f in fits]
    assert got == case['expect']


def test_every_reason_has_text():
    assert {e['why'] for c in CASES for e in c['expect'] if e} <= set(WHY)


def test_nice_step_and_clean():
    assert [nice_step(v) for v in (0.11, 1, 1.2, 2.4, 2.6, 7, 523)] == [0.2, 1, 2, 2.5, 5, 10, 1000]
    assert is_nice(0.25) and is_nice(5000) and not is_nice(14) and not is_nice(0)
    assert clean(98.60000000000001) == 98.6 and clean(0.1 + 0.2) == 0.3


def _random_need(rng: random.Random) -> Need:
    scale = 10 ** rng.uniform(-4, 7)
    lo = rng.choice([0.0, rng.uniform(-1, 1) * scale, rng.uniform(0, 1) * scale, -rng.uniform(0, 1) * scale])
    hi = lo + rng.choice([0.0, rng.uniform(0, 1) * scale, rng.uniform(0, 1e-3) * scale])
    return Need(lo, hi, anchor=rng.random() < 0.3, mode=rng.choice(['auto', 'auto', 'zero', 'data']), inverse=rng.random() < 0.2)


def test_properties_on_random_data():
    """Любые данные: всё внутри шкалы, шаг круглый, границы кратны шагу и без дробных хвостов, число делений одно на все шкалы,
    данные одного знака за нуль не выходят, столбцы и режим «от нуля» включают нуль."""
    rng = random.Random(20261112)
    for _ in range(3000):
        needs = [_random_need(rng) for _ in range(rng.choice([1, 1, 2, 3, 5]))]
        fits = fit_axes(needs)
        assert all(f is not None for f in fits)
        assert len({f.n for f in fits}) == 1 and N_MIN <= fits[0].n <= N_MAX
        for need, f in zip(needs, fits):
            tol = (f.maximum - f.minimum) * 1e-9
            assert f.minimum - tol <= need.lo and need.hi <= f.maximum + tol, (need, f)
            assert is_nice(f.step), (need, f)
            assert abs((f.maximum - f.minimum) / f.step - f.n) < 1e-6, (need, f)
            assert abs(f.minimum / f.step - round(f.minimum / f.step)) < 1e-6, (need, f)
            assert f.minimum == clean(f.minimum) and f.maximum == clean(f.maximum)
            if len(needs) == 1 and need.lo >= 0:                 # у нескольких шкал возможна общая нулевая линия (отдельный тест)
                assert f.minimum >= 0, (need, f)
            if len(needs) == 1 and need.hi <= 0 and need.lo < 0:
                assert f.maximum <= 0, (need, f)
            if need.mode == 'zero' or (need.anchor and need.mode == 'auto'):
                assert f.minimum <= 0 <= f.maximum, (need, f)


def test_single_axis_fills_the_field():
    """Сбой прежнего подбора: при пяти делениях и шагах 1–2–5 данные занимали 40–50 % поля (10–100 → 0…250, 0–523 → 0…1000)."""
    rng = random.Random(7)
    for _ in range(2000):
        lo = rng.uniform(0, 500)
        need = Need(lo, lo + rng.uniform(1, 2000))
        f = fit_axis(need)
        assert (need.hi - need.lo) / (f.maximum - f.minimum) >= 0.55 or f.minimum == 0, (need, f)
        assert (need.hi - min(need.lo, f.minimum if f.minimum == 0 else need.lo)) / (f.maximum - f.minimum) >= 0.55, (need, f)


def test_zero_lines_coincide():
    """Шкалы разных знаков: нуль на одном делении (обратная шкала считает деления сверху)."""
    for needs in ([Need(0, 100, anchor=True), Need(-5, 60)], [Need(-40, 60, anchor=True), Need(-1, 3)],
                  [Need(-30, 100), Need(-9, 2, inverse=True)]):
        fits = fit_axes(needs)
        places = []
        for need, f in zip(needs, fits):
            below = round(-f.minimum / f.step)
            places.append(f.n - below if need.inverse else below)
        assert len(set(places)) == 1, (needs, fits)
    costly = fit_axes([Need(0, 100, anchor=True), Need(-5, 60, inverse=True)])      # общий нуль сжал бы столбцы до 40 % поля: не делается
    assert (costly[0].minimum, costly[0].maximum) == (0.0, 100.0)
    own = fit_axes([Need(0, 100, anchor=True, mode='data'), Need(-5, 60)])          # «по данным»: шкала в общий нуль не втягивается
    assert own[0].minimum == 0.0


def test_mults_are_the_documented_ones():
    assert MULTS == (1.0, 2.0, 2.5, 5.0)
