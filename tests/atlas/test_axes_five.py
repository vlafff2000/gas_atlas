"""Пять шкал Y у графика: правые шкалы идут подряд, каждая со своим цветом; Plotly, Excel и разбор обратно — без потери шкал."""
import numpy as np
import pytest

from atlas.contract import Axis, Chart, Series
from atlas.export_chart import to_chart
from atlas.render import chart_xlsx, to_plotly


def five_axes_chart() -> Chart:
    x = np.arange(4)
    chart = Chart('axes-5', 'Пять шкал', Axis('X'), Axis('Расход', 'тыс. м³/сут', from_zero=True), crosshair=True,
                  y2=Axis('A', color='#111111'), y3=Axis('B', color='#222222'),
                  y4=Axis('C', color='#333333'), y5=Axis('D', color='#444444'))
    chart.series.append(Series('q', x, [1, 2, 3, 4], 'line'))
    for n, name in enumerate(('y2', 'y3', 'y4', 'y5'), start=2):
        chart.series.append(Series(f'r{n}', x, [n, n + 1, n + 2, n + 3], 'line', axis=name))
    return chart


def test_right_axes_go_in_order_without_gaps():
    chart = five_axes_chart()
    assert [name for name, _ in chart.right_axes()] == ['y2', 'y3', 'y4', 'y5']
    assert chart.axis_names() == ['y', 'y2', 'y3', 'y4', 'y5']
    assert chart.axis_at('y4').label == 'C'
    # пропуск (нет y3) — дальше ряд не идёт
    gap = Chart('g', 'g', Axis('X'), Axis('Y'), y2=Axis('A'), y4=Axis('C'))
    assert [name for name, _ in gap.right_axes()] == ['y2']


def test_plotly_has_five_axes_with_colors():
    fig = to_plotly(five_axes_chart())
    assert [fig.layout.yaxis2.title.text, fig.layout.yaxis5.title.text] == ['A', 'D']
    assert fig.layout.yaxis4.tickfont.color == '#333333'
    assert fig.layout.yaxis5.anchor == 'free' and fig.layout.yaxis5.overlaying == 'y'


def test_excel_and_round_trip_keep_all_series():
    data, _, _ = chart_xlsx(five_axes_chart())
    assert data[:2] == b'PK'                      # xlsx — zip-архив
    fig = to_plotly(five_axes_chart())
    back = to_chart(fig, 'back')
    assert [name for name, _ in back.right_axes()] == ['y2', 'y3', 'y4', 'y5']
    assert {s.axis for s in back.series} == {'y', 'y2', 'y3', 'y4', 'y5'}


@pytest.mark.parametrize('count', [1, 2])
def test_existing_one_and_two_right_axes_unchanged(count):
    chart = Chart('c', 'c', Axis('X'), Axis('Y'), y2=Axis('A'), y3=Axis('B') if count == 2 else None)
    fig = to_plotly(chart)
    assert fig.layout.yaxis2.title.text == 'A'
    if count == 2:
        assert fig.layout.xaxis.domain == (0.0, 0.88) and fig.layout.yaxis3.position == pytest.approx(0.97)
