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


def test_legend_columns_from_export_tabs_reach_drawing():
    """Колонки легенды из вкладок экспорта доходят до рисунка: легенда не бьётся на строки сама."""
    def multi():
        f = go.Figure([go.Scatter(x=[0, 1], y=[0, i], name='Длинное название ряда %d' % i) for i in range(6)])
        return f
    cfg = chart_format.configs({'fmt_legend_columns': 1})
    assert cfg['*']['style']['chart']['legend_columns'] == 1
    one = figure_bytes(chart_format.apply(multi(), chart_format.for_module(cfg, 'gdi')), 'png', 150, 150)
    auto = figure_bytes(chart_format.apply(multi(), {}), 'png', 150, 150)
    assert one != auto
    with pytest.raises(ParamError):
        chart_format.configs({'fmt_legend_columns': 40})


def test_full_style_panel_reaches_every_module():
    """Поле fmt_style несёт всё оформление «Любого графика»: подзаголовок, рамку легенды, размер подписей осей."""
    import json
    doc = {'chart': {'subtitle': 'Подзаголовок', 'legend_border': True, 'legend_size': 9, 'plot_background': '#eeeeee'},
           'axes': {'tick_size': 11, 'line_color': '#ff0000'}}
    cfg = chart_format.configs({'fmt_style': json.dumps(doc), 'fmt_grid': 'both'})
    style = cfg['*']['style']
    assert style['chart']['subtitle'] == 'Подзаголовок' and style['chart']['grid'] == 'both'
    assert style['text']['tick_size'] == 11
    assert chart_format.configs({'fmt_style': json.dumps({'chart': {'legend': 'left'}})})['*']['legend'] == 'left'
    styled = chart_format.apply(figure(), chart_format.for_module(cfg, 'gdi'))
    assert styled.layout.meta['style']['axes']['y']['line_color'] == '#ff0000'
    with pytest.raises(ParamError):
        chart_format.configs({'fmt_style': json.dumps({'chart': {'legend_size': 99}})})
