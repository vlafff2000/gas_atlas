from __future__ import annotations

from atlas.contract import Axis, Chart, Series
from atlas.render import TICK_INTERVALS, aligned_range, chart_file, to_plotly


def _chart(**kw):
    c = Chart('t-1', 'Тест', Axis('Дата', scale='time'), Axis('Дебит', from_zero=True), y2=Axis('Давление', **kw))
    c.series.append(Series('a', ['2024-01-01', '2024-02-01', '2024-03-01'], [3.0, 47.0, 120.0], 'line'))
    c.series.append(Series('b', ['2024-01-01', '2024-02-01', '2024-03-01'], [0.31, 0.5, 0.97], 'line', axis='y2'))
    return c


def test_two_axes_share_tick_count_and_grid():
    fig = to_plotly(_chart(from_zero=True))
    for axis in (fig.layout.yaxis, fig.layout.yaxis2):
        lo, hi = axis.range
        assert round((hi - lo) / axis.dtick) == TICK_INTERVALS
        assert axis.tick0 == lo
    assert fig.layout.yaxis.range[0] <= 0 and fig.layout.yaxis.range[1] >= 120


def test_fixed_maximum_is_kept():
    fig = to_plotly(_chart(from_zero=True, maximum=100))
    assert fig.layout.yaxis2.range[1] == 100
    assert round((fig.layout.yaxis2.range[1] - fig.layout.yaxis2.range[0]) / fig.layout.yaxis2.dtick) == TICK_INTERVALS


def test_range_always_covers_data():
    for lo, hi in ((0.31, 0.97), (-5, 3), (1000, 1001), (0, 7)):
        start, step = aligned_range(lo, hi)
        assert start <= lo + 1e-9 and start + TICK_INTERVALS * step >= hi - 1e-9


def test_png_export_runs():
    data, name, _ = chart_file(_chart(), 'png', 150)
    assert data[:4] == b'\x89PNG'
