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
    for c in (chart([44, 87], minimum=0.0), chart([44, 87], maximum=100.0), chart([44, 87], from_zero=True), chart([44, 87], step=10.0),
              chart([44, 87], kind='bar'), chart([44, 87], scale='log')):
        assert axis_auto.auto_chart(c) is c
    two = chart([44, 87])
    two.y2 = Axis('Уровень')
    assert axis_auto.auto_chart(two) is two
    assert axis_auto.auto_chart(chart([])).y.minimum is None


def test_non_negative_data_never_goes_below_zero():
    assert axis_auto.auto_chart(chart([0.2, 3.0])).y.minimum >= 0
    assert axis_auto.auto_chart(chart([-5, 3.0])).y.minimum < 0


def test_apply_keeps_result_without_charts():
    r = Result()
    assert axis_auto.apply(r) is r
