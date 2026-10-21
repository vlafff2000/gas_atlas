"""Выгрузка и копирование графика совпадают с экраном: личный вид браузера накладывается на расчёт (atlas/chart_view.py)."""
from atlas.chart_view import apply_view
from atlas.contract import Axis, Chart, Series


def sample() -> Chart:
    return Chart('t-1', 'График', Axis('Дата', scale='time'), Axis('Q', 'м³'),
                 [Series('A', [1, 2, 3], [1, 4, 9], kind='line', group='ГСП-1'),
                  Series('B', [1, 2, 3], [2, 3, 4], kind='points', facets={'Период': '2024'})],
                 y2=Axis('P', 'МПа'))


def test_empty_view_changes_nothing():
    chart = sample()
    assert apply_view(chart, None) is chart
    assert apply_view(chart, {}) is chart


def test_looks_ranges_and_window_applied():
    out = apply_view(sample(), {'looks': {'ГСП-1|line': {'color': '#ff0000', 'width': 4, 'opacity': 0.5, 'bogus': 1}},
                               'ranges': {'y': [0, 20], 'y2': [1, 2]}, 'x': [1, 2]})
    assert out.series[0].look == {'color': '#ff0000', 'width': 4.0, 'opacity': 0.5} and out.series[0].opacity == 0.5
    assert (out.y.minimum, out.y.maximum) == (0, 20) and (out.y2.minimum, out.y2.maximum) == (1, 2)
    assert (out.x.minimum, out.x.maximum) == (1, 2)


def test_hidden_series_and_bad_values_ignored():
    out = apply_view(sample(), {'hidden': ['ГСП-1'], 'looks': {'B|points': {'color': 'red'}}, 'ranges': {'y': [5, 5], 'y3': [0, 1]}})
    assert [s.name for s in out.series] == ['B'] and out.series[0].look is None
    assert out.y.minimum is None and out.y2.minimum is None
    assert [s.name for s in apply_view(sample(), {'facets': ['Период\u0001 2024']}).series] == ['A', 'B']
    assert [s.name for s in apply_view(sample(), {'facets': ['Период\u00012024']}).series] == ['A']


def test_export_png_uses_view():
    from atlas import render
    plain = render.chart_file(sample(), 'svg', 150)[0]
    shown = render.chart_file(apply_view(sample(), {'looks': {'ГСП-1|line': {'color': '#12ab34'}}, 'ranges': {'y': [0, 50]}}), 'svg', 150)[0]
    assert b'12ab34' not in plain and b'12ab34' in shown
