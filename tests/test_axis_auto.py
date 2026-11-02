from __future__ import annotations

import numpy as np

from atlas import axis_auto
from atlas.contract import Axis, Chart, Result, Series


def chart(y, kind='line', **axis):
    return Chart('c', 'T', Axis('Дата', scale='time'), Axis('Давление', 'кгс/см²', **axis),
                 series=[Series('s', np.arange(len(y)), np.array(y, float), kind)])


def test_tight_round_bounds_cover_all_points():
    c = axis_auto.auto_chart(chart([44.3, 60, 87.2]))
    assert (c.y.minimum, c.y.maximum) == (40.0, 90.0)


def test_manual_and_special_axes_untouched():
    for c in (chart([44, 87], minimum=0.0), chart([44, 87], maximum=100.0), chart([44, 87], step=10.0), chart([44, 87], scale='log')):
        assert axis_auto.auto_chart(c) is c
    boxed = chart([44, 87], kind='box')
    assert axis_auto.auto_chart(boxed) is boxed
    assert axis_auto.auto_chart(chart([])).y.minimum is None


def test_bars_start_at_zero_with_round_top():
    c = axis_auto.auto_chart(chart([3, 41, 87], kind='bar'))
    assert (c.y.minimum, c.y.maximum) == (0.0, 100.0)
    assert (axis_auto.auto_chart(chart([44, 87], from_zero=True)).y.minimum) == 0.0
    mixed = axis_auto.auto_chart(chart([-40, 20, 60], kind='bar'))
    assert (mixed.y.minimum, mixed.y.maximum) == (-40.0, 60.0)


def test_stack_uses_sums():
    c = Chart('c', 'T', Axis('x', scale='category', categories=['a', 'b']), Axis('v'),
              series=[Series('s1', ['a', 'b'], np.array([40., 10.]), 'bar', stack='k'),
                      Series('s2', ['a', 'b'], np.array([30., 10.]), 'bar', stack='k')])
    out = axis_auto.auto_chart(c)
    assert (out.y.minimum, out.y.maximum) == (0.0, 100.0)           # сумма 70 → верх 100, а не 40


def test_each_axis_is_fitted_independently_with_five_intervals():
    c = chart([44.3, 60, 87.2])
    c.y2 = Axis('Уровень', 'м', inverse=True)
    c.series.append(Series('lvl', np.arange(3), np.array([300., 500., 900.]), 'line', axis='y2'))
    out = axis_auto.auto_chart(c)
    assert (out.y.minimum, out.y.maximum) == (40.0, 90.0)
    assert out.y2.minimum >= 0 and out.y2.maximum >= 900 and (out.y2.maximum - out.y2.minimum) % 5 == 0
    c.y2 = Axis('Уровень', 'м', minimum=0.0, maximum=1000.0)          # вручную — не трогаем, основная подбирается
    kept = axis_auto.auto_chart(c)
    assert (kept.y2.minimum, kept.y2.maximum) == (0.0, 1000.0) and kept.y.minimum == 40.0


def test_non_negative_data_never_goes_below_zero():
    assert axis_auto.auto_chart(chart([0.2, 3.0])).y.minimum >= 0
    assert axis_auto.auto_chart(chart([-5, 3.0])).y.minimum < 0


def test_apply_keeps_result_without_charts():
    r = Result()
    assert axis_auto.apply(r) is r
