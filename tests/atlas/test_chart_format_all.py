"""Общий стиль всех графиков экспорта (``fmt_all``): линии, маркеры, столбцы; правила наборов данных и «Отдельные графики» сильнее."""
import plotly.graph_objects as go
import pytest

from atlas import chart_format
from atlas.contract import ParamError
from atlas.engine.core.export import figure_bytes


def figure():
    return go.Figure([go.Scatter(x=[0, 1, 2], y=[1, 2, 3], mode='lines+markers', name='ГДИ 1'),
                      go.Scatter(x=[0, 1, 2], y=[3, 2, 1], mode='lines+markers', name='ГДИ 2'),
                      go.Bar(x=['a', 'b'], y=[1, 2], name='столбцы')])


ALL = '{"width": 3, "dash": "dash", "marker": 5, "shape": "square", "hollow": true, "bar_opacity": 0.5, "bar_width": 0.5, "bar_border": "#ff0000", "bar_border_width": 2}'


def styled(extra=None, form=None):
    cfg = chart_format.for_module(chart_format.configs({'fmt_all': ALL, **(form or {})}), 'gdi')
    cfg = {**cfg, **(extra or {})}
    return chart_format.apply(figure(), cfg)


def test_global_style_reaches_every_trace():
    fig = styled()
    for t in fig.data[:2]:
        assert t.line.width == 3 and t.line.dash == 'dash' and t.marker.size == 10 and t.marker.symbol == 'square-open'
        assert 'width' in t.meta['own'] and 'size' in t.meta['own']
    bar = fig.data[2]
    assert bar.opacity == 0.5 and bar.marker.line.color == '#ff0000' and bar.meta['bar_width'] == 0.5


def test_series_rule_beats_global_style():
    rule = chart_format.parse_series('[{"match": "гди 2", "width": 1, "marker": 2, "look": {"dash": "dot"}}]')
    fig = styled({'series': rule})
    assert fig.data[0].line.width == 3 and fig.data[0].line.dash == 'dash'
    assert fig.data[1].line.width == 1 and fig.data[1].marker.size == 4 and fig.data[1].line.dash == 'dot'


def test_empty_is_reset():
    assert chart_format.configs({'fmt_all': ''}) == {}
    fig = chart_format.apply(figure(), chart_format.for_module(chart_format.configs({'fmt_all': ''}), 'gdi'))
    assert fig.data[0].line.width is None and fig.data[2].opacity is None


def test_drawing_differs():
    plain = figure_bytes(chart_format.apply(figure(), {}), 'png', 150, 150)
    assert figure_bytes(styled(), 'png', 150, 150) != plain


@pytest.mark.parametrize('bad', ['{"width": 99}', '{"shape": "blob"}', '{"bar_border": "red"}', '{"bar_width": 0}'])
def test_values_validated(bad):
    with pytest.raises(ParamError):
        chart_format.configs({'fmt_all': bad})
