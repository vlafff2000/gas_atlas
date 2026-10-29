"""Вкладки экспорта модулей: общие сетка и жирный/курсив подписей осей (``chart_format``) рисуются так же, как в «Любом графике»."""
import plotly.graph_objects as go
import pytest

from atlas import chart_format
from atlas.contract import ParamError
from atlas.engine.core.export import figure_bytes


def figure():
    f = go.Figure(go.Scatter(x=[0, 1, 2, 3], y=[0, 2, 1, 3], mode='lines'))
    f.update_layout(xaxis_title='X', yaxis_title='Y', yaxis=dict(range=[0, 4]))
    return f


FORM = {'fmt_grid': 'both', 'fmt_grid_width': 1.5, 'fmt_minor_grid': 'show', 'fmt_minor_grid_color': '#ff0000',
        'fmt_axis_title_bold': True, 'fmt_tick_italic': True}


def test_common_style_reaches_every_module():
    cfg = chart_format.configs(FORM)
    assert cfg['*']['style'] == {'chart': {'grid': 'both', 'grid_width': 1.5, 'minor_grid': 'show', 'minor_grid_color': '#ff0000'},
                                 'text': {'title_bold': True, 'tick_italic': True}}
    assert chart_format.for_module(cfg, 'gdi')['style'] == cfg['*']['style']


def test_style_is_applied_to_figure_meta_and_drawing():
    cfg = chart_format.for_module(chart_format.configs(FORM), 'gdi')
    styled = chart_format.apply(figure(), cfg)
    assert styled.layout.meta['style']['axes']['y']['title_bold'] is True
    assert figure_bytes(styled, 'png', 150, 150) != figure_bytes(chart_format.apply(figure(), {}), 'png', 150, 150)


def test_empty_fields_change_nothing():
    assert chart_format.configs({'fmt_grid': '', 'fmt_tick_bold': ''}) == {}
    plain = chart_format.apply(figure(), {})
    assert 'style' not in (plain.layout.meta or {})


@pytest.mark.parametrize('bad', [{'fmt_grid_width': 9}, {'fmt_minor_grid': 'maybe'}, {'fmt_minor_grid_color': 'red'}])
def test_style_values_validated(bad):
    with pytest.raises(ParamError):
        chart_format.configs(bad)
