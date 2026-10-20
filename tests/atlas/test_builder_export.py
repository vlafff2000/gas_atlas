"""Ручное оформление конструктора в выгрузке: ряд, ось, график доходят до фигуры и файла."""
import re

import pytest

from atlas import render
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
