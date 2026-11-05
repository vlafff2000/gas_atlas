from __future__ import annotations

import dataclasses

import matplotlib
import pytest

matplotlib.use('Agg')

from atlas import chart_special
from atlas.contract import Axis, Chart, Series


def _chart(**y) -> Chart:
    cats = ['a', 'b', 'c']
    chart = Chart('t', 'Работающие скважины', Axis('Месяц', scale='category', categories=cats), Axis('Скважин', 'скв.', **y))
    chart.series.append(Series('в работе', cats, [40.0, 45.0, 50.0], 'bar', stack='m', segments=['40', '45', '50']))
    return chart


def _ax(chart: Chart):
    from atlas.render import group_colors, series_color
    plt = chart_special._setup()
    fig = chart_special._stack_figure(plt, chart, group_colors(chart), series_color, {})
    chart_special._dress(fig, chart, {})
    return fig.axes[0]


def test_stack_axis_starts_from_zero_by_default():
    assert _ax(_chart())._get_lines is not None
    assert _ax(_chart()).get_ylim()[0] == 0


def test_stack_axis_manual_min_max_step():
    ax = _ax(_chart(minimum=10, maximum=80, step=10))
    assert ax.get_ylim() == (10, 80)
    assert [round(t) for t in ax.get_yticks() if 10 <= t <= 80] == [10, 20, 30, 40, 50, 60, 70, 80]


def test_stack_axis_only_max_or_only_min():
    assert _ax(_chart(maximum=100)).get_ylim() == (0, 100)
    lo, hi = _ax(_chart(minimum=20)).get_ylim()
    assert lo == 20 and hi > 50


def test_export_applies_axis_from_format_doc():
    from atlas import export_any
    prepared, _ = export_any.prepared(_chart(), export_any.settings_of({'doc': {'axes': {'y': {'min': '10', 'max': '80', 'step': '10'}}}}))
    assert (prepared.y.minimum, prepared.y.maximum, prepared.y.step) == (10, 80, 10)
    content, *_ = export_any.export(_chart(), {'format': 'png', 'doc': {'axes': {'y': {'min': '10', 'max': '80', 'step': '10'}}}})
    assert content[:4] == b'\x89PNG'
