"""Файлы выгрузки читают ту же модель оформления v2, что и экран (atlas/chart_style.py): каждое поле меняет рисунок."""
import plotly.graph_objects as go
import pytest

from atlas import chart_style
from atlas.contract import Axis, Chart, Series
from atlas.engine.core.export import figure_bytes
from atlas.render import to_plotly


def figure(style=None, legend=None):
    f = go.Figure([go.Scatter(x=[0, 1, 2, 3], y=[0, 2, 1, 3], mode='lines', name='a'),
                   go.Scatter(x=[0, 1, 2, 3], y=[3, 1, 2, 0], mode='lines', name='b')])
    f.update_layout(xaxis_title='X', yaxis_title='Y', yaxis=dict(range=[0, 4]), title='График')
    meta = {}
    if style:
        meta['style'] = style
    if legend:
        meta['format'] = {'legend': legend}
    f.update_layout(meta=meta)
    return f


def png(f):
    return figure_bytes(f, 'png', 150, 120)


BASE = png(figure())

# поле модели → (куда пишется, пример значения). Поля оси лежат в style.axes.y, поля графика — в style.chart.
AXIS = {'ticks': 'in', 'minor_ticks': 'out', 'line': False, 'line_color': '#cc0000', 'line_width': 3, 'label_rotate': 45,
        'units': 'thousands', 'title_place': 'end', 'decimals': 3, 'tick_size': 14, 'title_size': 16, 'title_bold': True,
        'title_italic': True, 'tick_bold': True, 'tick_italic': True, 'font': 'times', 'color': '#2255aa', 'minor_step': 0.25, 'cross': 1.5}
CHART = {'subtitle': 'Подзаголовок', 'legend_columns': 1, 'legend_border': True, 'legend_background': '#ffffcc', 'grid_dash': 'dash',
         'minor_grid_dash': 'dot', 'border_color': '#aa0000', 'border_width': 4, 'plot_border_color': '#00aa00', 'plot_border_width': 3,
         'title_size': 20, 'title_bold': True, 'title_color': '#aa00aa', 'title_align': 'center', 'font': 'times', 'text_color': '#115599',
         'legend_size': 12, 'grid_color': '#ff0000', 'grid_width': 2, 'minor_grid_color': '#00ff00', 'minor_grid_width': 1,
         'background': '#eeeeee', 'plot_background': '#ddeeff'}
# поля, которые для файла не имеют смысла или проверяются отдельно (дата, положение легенды, шрифт легенды)
SEPARATE = {'date_format', 'legend', 'legend_font', 'title_font', 'grid', 'minor_grid', 'subtitle_size'}


def test_every_model_field_is_covered():
    """Новое поле модели без проверки отрисовки в файле не проходит: добавь пример или внеси в SEPARATE с причиной."""
    known = set(AXIS) | SEPARATE
    assert set(chart_style.AXIS_FMT) <= known, set(chart_style.AXIS_FMT) - known
    known = set(CHART) | SEPARATE
    assert set(chart_style.CHART_FMT) <= known, set(chart_style.CHART_FMT) - known


@pytest.mark.parametrize('key,value', AXIS.items())
def test_axis_field_changes_file(key, value):
    spec = {key: value, **({'step': 1} if key == 'minor_step' else {})}
    assert png(figure({'axes': {'y': spec}})) != BASE


@pytest.mark.parametrize('key,value', CHART.items())
def test_chart_field_changes_file(key, value):
    extra = {'minor_grid_dash': {'minor_grid': 'show'}, 'minor_grid_color': {'minor_grid': 'show'}, 'minor_grid_width': {'minor_grid': 'show'},
             'grid_dash': {'grid': 'both'}}.get(key, {})
    assert png(figure({'chart': {key: value, **extra}})) != BASE


def test_legend_left_and_subtitle_size():
    assert png(figure(legend='left')) != BASE
    one = png(figure({'chart': {'subtitle': 'Т'}}))
    assert png(figure({'chart': {'subtitle': 'Т', 'subtitle_size': 18}})) != one


def chart(look):
    s = Series(name='ряд', kind='line', x=[0, 1, 2], y=[1.234, 2.5, 3.1], look=look, markers=True)
    return Chart(id='x-1', title='t', x=Axis(label='x', unit='', scale='value'), y=Axis(label='y', unit='', scale='value'), series=[s])


@pytest.mark.parametrize('look', [{'dash': 'dashdot'}, {'dash': 'longdash'}, {'hollow': True, 'marker': True}, {'marker': True, 'marker_border': '#ff0000'},
                                  {'marker': True, 'marker_border_width': 3}, {'valueLabels': True}, {'valueLabels': True, 'label_position': 'bottom'},
                                  {'valueLabels': True, 'label_decimals': 2}, {'valueLabels': True, 'label_size': 14}])
def test_series_look_reaches_file(look):
    assert figure_bytes(to_plotly(chart(look)), 'png', 150, 120) != figure_bytes(to_plotly(chart({'marker': True})), 'png', 150, 120)


def test_legend_name_renames_traces():
    f = to_plotly(chart({'legend_name': 'Своё имя'}))
    assert [t.name for t in f.data] == ['Своё имя']


def test_special_charts_read_v2_fields():
    """Спец-графики (chart_special, Matplotlib) тоже рисуют подзаголовок, рамки, штрих сетки, деления и линию оси."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import pandas as pd
    from atlas import chart_special, render
    from atlas.modules import an_wells
    from atlas.modules import an_charts
    counts = pd.DataFrame({'group': ['ГСП 1'], 'zero_numbers': ['0'], **{k: [v] for k, v in zip(an_wells.CLASS_KEYS, (0, 1, 0, 3, 0, 0, 60))}})
    chart = an_charts.class_share_chart('withdrawal', '2023-2024', counts)
    fig = chart_special._stack_figure(plt, chart, render.group_colors(chart), render.series_color)
    style = {'subtitle': 'Подзаголовок', 'border_color': '#aa0000', 'border_width': 2, 'grid': 'h', 'grid_dash': 'dash'}
    chart_special._dress(fig, chart, {'style': style, 'axes': {'y': {'ticks': 'in', 'line': False, 'label_rotate': 30}}})
    ax = fig.axes[0]
    assert 'Подзаголовок' in [t.get_text() for t in ax.texts]
    assert fig.patch.get_edgecolor()[0] > 0.6 and ax.spines['left'].get_visible() is False
    assert ax.yaxis.get_gridlines()[0].get_linestyle() == '--'
    plt.close('all')


def _xlsx_chart_xml(chart_):
    import io
    import zipfile
    from atlas.render import chart_xlsx
    data = chart_xlsx(chart_)[0]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read('xl/charts/chart1.xml').decode()


def test_xlsx_chart_gets_model_v2():
    """Диаграмма Excel остаётся настоящей и получает оформление: штрих, маркер, деления, единицы, шаги, легенда, подписи, рамки."""
    s = Series(name='ряд', kind='line', x=[0, 1, 2, 3], y=[1000.5, 2500, 3100, 2000], markers=True,
               look={'width': 3, 'dash': 'dashdot', 'marker': True, 'shape': 'square', 'size': 9, 'hollow': True, 'marker_border': '#cc0000',
                     'valueLabels': True, 'label_decimals': 1, 'label_position': 'bottom', 'legend_name': 'Мой ряд'})
    c = Chart(id='x-1', title='Заголовок', series=[s],
              x=Axis(label='X', unit='', scale='value', style={'ticks': 'in', 'line_color': '#cc0000', 'label_rotate': 30}),
              y=Axis(label='Y', unit='т', scale='value', step=500, inverse=True,
                     style={'units': 'thousands', 'decimals': 1, 'minor_step': 250, 'minor_ticks': 'out', 'title_bold': True}),
              style={'subtitle': 'Подзаг', 'legend': 'left', 'grid': 'both', 'grid_dash': 'dash', 'border_color': '#336699', 'plot_background': '#f4f8ff'})
    xml = _xlsx_chart_xml(c)
    for mark in ('dashDot', '<legendPos val="l"', 'majorTickMark val="in"', 'minorTickMark val="out"', '<dispUnits>', '<minorUnit val="250',
                 'orientation val="maxMin"', 'Мой ряд', 'Подзаг', 'showVal val="1"', '<dLblPos val="b"'):
        assert mark in xml, mark
    assert _xlsx_chart_xml(chart({'dash': 'longdash'})).count('lgDash') >= 1


def test_xlsx_without_style_keeps_default_chart():
    xml = _xlsx_chart_xml(chart({}))
    assert 'dispUnits' not in xml and 'legendPos val="l"' not in xml
