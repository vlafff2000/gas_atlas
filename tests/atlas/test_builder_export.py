"""Ручное оформление конструктора в выгрузке: ряд, ось, график доходят до фигуры и файла."""
import re

import pytest

from atlas import contract, render
from atlas.contract import Data
from atlas.modules import builder
from tests.atlas.test_builder import frames


def chart(**layout):
    row = {'dataset': 'production', 'y': 'q', 'wells': ['1']}
    return builder.build(Data(frames()), {'series': [row, {'dataset': 'operations', 'y': 'p_wellhead', 'axis': 'y2', 'view': 'points'}], **layout}).charts[0]


def test_old_layout_figure_has_empty_style():
    fig = render.to_plotly(chart())
    assert 'style' in fig.layout.meta          # конструктор всегда передаёт границы и шаг осей
    assert fig.layout.meta['style']['chart'] == {} and 'format' not in fig.layout.meta


def test_series_look_in_figure():
    c = builder.build(Data(frames()), {'series': [{'dataset': 'production', 'y': 'q', 'wells': ['1'], 'look': {
        'color': '#ff0000', 'width': 4, 'dash': 'dot', 'marker': True, 'shape': 'star', 'size': 12, 'opacity': .5}},
        {'dataset': 'operations', 'y': 'p_wellhead', 'view': 'points', 'look': {'shape': 'x', 'markerColor': '#00ff00', 'size': 10}},
        {'dataset': 'gas_db', 'y': 'gas', 'look': {'line': False, 'marker': False}}]}).charts[0]
    line, points, hidden = render.to_plotly(c).data[0], render.to_plotly(c).data[2], render.to_plotly(c).data[-1]
    assert line.line.color == '#ff0000' and line.line.dash == 'dot' and line.line.width == pytest.approx(2.4)
    assert line.mode == 'lines+markers' and line.marker.symbol == 'star' and line.marker.size == 12 and line.opacity == .5
    assert set(line.meta['own']) == {'width', 'size', 'alpha'}
    assert points.marker.symbol == 'x' and points.marker.color == '#00ff00' and points.marker.size == 10
    assert hidden.visible is False


def test_chart_style_in_figure_and_files():
    c = chart(chart_style={'title_font': 'times', 'title_size': 22, 'title_bold': True, 'legend': 'top', 'legend_size': 12, 'grid': 'h',
                           'grid_color': '#999999', 'background': '#fffbe6', 'title_align': 'center'},
              axis_style={'y': {'min': '0', 'max': '300', 'step': '50', 'decimals': 1, 'color': '#aa0000', 'tick_size': 15},
                          'x': {'date_format': 'MM.yyyy', 'min': '2025-01-02'}, 'y2': {'decimals': 0}})
    fig = render.to_plotly(c)
    assert fig.layout.meta['format'] == {'legend': 'top'} and fig.layout.meta['style']['axes']['y']['step'] == 50
    for fmt in ('png', 'svg', 'pdf', 'xlsx'):
        content, name, _ = render.chart_file(c, fmt, 150)
        assert content and name.endswith(fmt)
    svg = render.chart_file(c, 'svg', 150)[0].decode()
    assert '#fffbe6' in svg and 'Times' in svg or 'Liberation Serif' in svg        # фон и шрифт заголовка попали в файл
    assert re.search(r'300,0', svg) is not None or '300' in svg                  # подписи оси Y с запятой
    assert '#aa0000' in svg                                                       # цвет оси Y


def test_no_style_figures_of_other_modules_unchanged():
    """Модули без ручного оформления получают прежнюю фигуру: ни meta.style, ни meta.format."""
    c = chart()
    c.id = 'other-chart'
    meta = render.to_plotly(c).layout.meta
    assert 'style' not in meta and 'format' not in meta


def test_step_skips_alignment_only_in_builder():
    """Шаг делений у чужих модулей (ГГХ, давление) не отключает общую сетку двух осей; в конструкторе шаг важнее."""
    c = chart()
    c.y2 = c.y2 or contract.Axis('Y2', '')
    c.y.step = c.y2.step = 10
    c.id = 'other-chart'
    assert render.to_plotly(c).layout.yaxis.autorange is False      # выровнены
    c.id = 'builder'
    assert render.to_plotly(c).layout.yaxis.autorange is not False  # шаг задан вручную, выравнивания нет


def combo(*views, **extra):
    rows = []
    for i, view in enumerate(views):
        rows.append({'dataset': 'production', 'y': 'q', 'wells': ['1'] if i % 2 == 0 else ['2'], 'view': view, 'axis': ['y', 'y2', 'y3'][i % 3],
                     **extra.get(view, {})})
    return builder.build(Data(frames()), {'series': rows}).charts[0]


def test_combo_figure_traces():
    c = combo('bar', 'area', 'step', 'line_points')
    t = render.to_plotly(c).data
    assert t[0].type == 'bar' and t[0].yaxis == 'y' and t[0].meta['combo']
    assert t[1].fill == 'tozeroy' and t[1].meta['fill'] and t[1].fillcolor.startswith('rgba(') and t[1].fillcolor.endswith(',0.6)')
    assert t[2].line.shape == 'hv' and t[2].meta['step'] and t[2].fill is None
    assert t[3].mode == 'lines+markers'


def test_combo_area_opacity_and_stack_in_figure():
    c = combo('area', 'area', area={'stack': 'S', 'axis': 'y', 'look': {'opacity': .25, 'color': '#336699'}})
    t = render.to_plotly(c).data
    assert t[0].fill == 'tonexty' and t[0].stackgroup == 'S' and t[0].fillcolor == 'rgba(51,102,153,0.25)'
    assert t[0].line.color == '#336699'


def test_combo_bars_stack_barmode():
    c = combo('bar', 'bar', bar={'stack': 'S', 'axis': 'y'})
    fig = render.to_plotly(c)
    assert fig.layout.barmode == 'stack' and fig.data[0].offsetgroup == fig.data[1].offsetgroup == 'S'


@pytest.mark.parametrize('fmt', ['png', 'svg', 'pdf', 'xlsx'])
def test_combo_files(fmt):
    c = combo('bar', 'area', 'step', 'line_points', 'points')
    content, name, _ = render.chart_file(c, fmt, 150)
    assert content and name.endswith(fmt)


def test_combo_png_stacks_and_bar_width():
    from atlas.engine.core.export_combo import Bars, step_of
    import numpy as np
    assert step_of(np.array([3.0, 1.0, 2.0, 2.0])) == 1.0 and step_of(np.array([5.0])) == 1.0
    c = combo('bar', 'bar', bar={'stack': 'S', 'axis': 'y'})
    svg = render.chart_file(c, 'svg', 150)[0].decode()
    assert svg.count('<path') > 8
    solo = render.chart_file(combo('bar', 'bar', bar={'axis': 'y'}), 'svg', 150)[0]
    assert solo != render.chart_file(c, 'svg', 150)[0]       # стопка и «рядом» рисуются по-разному


def test_old_charts_not_touched():
    from atlas.contract import Axis, Chart, Series
    import numpy as np
    x = np.array(['2025-01-01', '2025-01-02'], dtype='datetime64[ns]')
    ch = Chart('other-1', 't', Axis('X', scale='time'), Axis('Y'), series=[Series('a', x, [1.0, 2.0], 'bar', stack='s')])
    bar = render.to_plotly(ch).data[0]
    assert bar.yaxis is None and bar.meta is None and bar.offsetgroup is None
