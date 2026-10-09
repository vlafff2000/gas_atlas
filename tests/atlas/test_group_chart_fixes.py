"""Групповые графики: стопка по общим датам, шкала по сумме, столбцы от нуля, отметки пропусков, выгрузка стопкой."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas import thinning
from atlas.api import create_app
from atlas.contract import Axis, Chart, Series
from atlas.engine.modules import production as legacy
from atlas.modules import _group_charts
from atlas.projects import Projects
from atlas.render import axis_extent, to_plotly


# ---------- прореживание стопки ----------

def stack_chart(wells=40, days=1200):
    x = pd.date_range('2020-01-01', periods=days).to_numpy()
    rng = np.random.default_rng(3)
    series = [Series(f'№ {w}', x, rng.random(days) * 10 + (w % 5), 'line', stack='share') for w in range(wells)]
    return Chart('c', 'c', Axis('Дата', scale='time'), Axis('Доля', '%'), series=series)


def test_stacked_lines_are_thinned_with_the_same_indices():
    """Серии стопки отдаются по одним и тем же индексам: сумма на оставленных датах равна сумме по всем точкам."""
    chart = stack_chart()
    assert sum(len(s.x) for s in chart.series) > thinning.CHART_POINTS     # прореживание включается
    kept = thinning.screen_indices(chart)
    assert set(kept) == set(range(40))
    first = kept[0]
    assert all(np.array_equal(first, k) for k in kept.values())
    assert 5 < len(first) <= thinning.SERIES_CAP
    total_all = sum(np.asarray(s.y) for s in chart.series)
    total_kept = sum(np.asarray(s.y)[first] for s in chart.series)
    assert np.allclose(total_all[first], total_kept)


def test_stack_with_different_x_is_not_thinned():
    chart = stack_chart()
    chart.series[1].x = chart.series[1].x[1:]
    chart.series[1].y = chart.series[1].y[1:]
    assert thinning.screen_indices(chart) == {}


def test_window_keeps_stack_aligned():
    chart = stack_chart()
    x = thinning.axis_numbers(chart.series[0].x)
    picked = thinning.window_indices(chart, x[0], x[-1])
    idx = [p[0] for p in picked.values()]
    assert all(np.array_equal(idx[0], i) for i in idx)


# ---------- «столбцы + кривая» ----------

def day_frame():
    rows = []
    for d in pd.date_range('2024-11-01', '2024-11-30'):
        rows += [(d, '101', '2024', 1.0e6), (d, '103', '2024', np.nan)]      # скв. 103: все записи ноября исключены
    for d in pd.date_range('2024-12-01', '2024-12-31'):
        rows += [(d, '101', '2024', 1.0e6), (d, '102', '2024', 2.0e6), (d, '103', '2024', 3.0e6)]
    return pd.DataFrame(rows, columns=['date', 'well', 'period', 'v'])


def test_hybrid_bars_share_month_axis_and_gaps_are_not_zero():
    d = day_frame()
    chart = _group_charts.hybrid_chart(None, d, pd.DataFrame(), '1')
    bars = [s for s in chart.series if s.kind == 'bar']
    assert len(bars) == 3
    months = [pd.Timestamp(v) for v in bars[0].x]
    assert months == [pd.Timestamp('2024-11-01'), pd.Timestamp('2024-12-01')]
    for s in bars:
        assert [pd.Timestamp(v) for v in s.x] == months          # у всех одни и те же месяцы: стопка по номеру = по дате
    by = {s.name: list(s.y) for s in bars}
    assert by['№ 101'] == pytest.approx([30.0, 31.0])
    assert np.isnan(by['№ 102'][0]) and by['№ 102'][1] == pytest.approx(62.0)      # не 0 и не чужой ноябрь
    assert np.isnan(by['№ 103'][0])                                             # все записи исключены: пропуск, не 0
    assert by['№ 103'][1] == pytest.approx(93.0)
    labels = {s.name: s.labels for s in bars}
    assert labels['№ 102'][0] == 'записей: 0 из 30 сут' and labels['№ 101'][1] == 'записей: 31 из 31 сут'


def test_axis_extent_of_stacked_bars_is_the_sum():
    d = day_frame()
    chart = _group_charts.hybrid_chart(None, d, pd.DataFrame(), '1')
    lo, hi = axis_extent(chart, 'y')
    assert hi == pytest.approx(31 + 62 + 93)      # декабрь: сумма трёх скважин, а не максимум одной (93)


def test_export_stacks_bars_and_starts_from_zero():
    d = day_frame()
    chart = _group_charts.hybrid_chart(None, d, pd.DataFrame(), '1')
    fig = to_plotly(chart)
    assert fig.layout.barmode == 'stack'
    assert fig.layout.yaxis.range[0] == 0 and fig.layout.yaxis.range[1] >= 186      # две оси: границы заданы явно, по сумме стопки


def test_bars_without_from_zero_still_start_from_zero_in_export():
    chart = Chart('c', 'c', Axis('Сезон', scale='category', categories=['a', 'b', 'c']), Axis('Объем', 'млн м³', from_zero=False),
                  series=[Series('v', ['a', 'b', 'c'], [95, 98, 100], 'bar')])
    assert to_plotly(chart).layout.yaxis.rangemode == 'tozero'


def test_stacked_lines_use_stackgroup_in_export():
    x = pd.date_range('2024-01-01', periods=3).to_numpy()
    chart = Chart('c', 'c', Axis('Дата', scale='time'), Axis('Доля', '%'),
                  series=[Series('a', x, [10, 20, 30], 'line', stack='s'), Series('b', x, [90, 80, 70], 'line', stack='s')])
    fig = to_plotly(chart)
    assert [t.stackgroup for t in fig.data] == ['s', 's']


# ---------- пропуски расхода на линии скважины ----------

@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    return client, pid, projects


def test_missing_days_are_marked_when_shown_as_zero(env):
    from atlas.domain import DatasetKind
    client, pid, projects = env
    df = projects.data(pid)[DatasetKind.PRODUCTION]
    kind = 'withdrawal'
    periods = sorted(set(df[df.kind == kind].period))[-1:]
    wells = sorted(set(df[(df.kind == kind) & df.period.isin(periods)].well))[:3]
    missing = int(legacy.curve_data(df, kind, periods, wells).missing.sum())
    body = client.post('/api/modules/production/run', json={'project': pid, 'params': dict(
        kind=kind, view='time', periods=periods, wells=wells, groups=[])}).json()
    names = [s['name'] for c in body['charts'] for s in c['series']]
    marks = [n for n in names if n.startswith('Нет записи (показан 0)')]
    assert len(marks) == (1 if missing else 0)
    if missing:
        assert f'{missing} сут' in marks[0]


def test_curve_marks_days_without_record_but_keeps_zero():
    """Сутки без записи на линии остаются нулём, но отмечены отдельными маркерами и подписаны."""
    from atlas.modules import _production as production
    dates = pd.date_range('2025-01-01', periods=10)
    q = np.array([200, 210, np.nan, np.nan, 190, 195, np.nan, 180, 185, 175], dtype=float) * 1000
    df = pd.DataFrame({'date': dates, 'well': '7', 'kind': 'withdrawal', 'period': '2024-2025', 'q': q,
                       'file': 'f.csv', 'sheet': 's', '_row': np.arange(10), '_point_id': [f'p{i}' for i in range(10)],
                       '_excluded': False})
    sel = production.Selection.__new__(production.Selection)
    sel.df, sel.kind, sel.periods, sel.gdi = df, 'withdrawal', ['2024-2025'], None
    chart = production.curve_chart(sel, ['7'], 'date')
    marks = [s for s in chart.series if s.name.startswith('Нет записи (показан 0)')]
    assert len(marks) == 1 and marks[0].name.endswith('3 сут')
    assert list(marks[0].y) == [0, 0, 0] and marks[0].kind == 'points' and marks[0].hollow
    line = chart.series[0]
    assert line.kind == 'line' and sorted(set(np.asarray(line.y)[[2, 3, 6]])) == [0.0]       # на линии по-прежнему 0
