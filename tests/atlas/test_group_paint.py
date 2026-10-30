"""Преемственность цветов групп: ряд без цвета с именем группы получает сквозной цвет."""
import numpy as np

from atlas.contract import Axis, Chart, Result, Series
from atlas.group_colors import colors_for, set_known_groups
from atlas.group_paint import paint


def test_paint_only_group_named_series_without_color():
    set_known_groups(['ГСП-1', 'ГСП-2', 'ГСП-3'])
    x = np.arange(2)
    chart = Chart('c', 'c', Axis('x'), Axis('y'), [Series('ГСП 2', x, x), Series('Закачка', x, x), Series('ГСП-1', x, x, color='#123456'),
                                                      Series('к', x, x, group='ГСП-3')])
    out = paint(Result(charts=[chart])).charts[0]
    colors = colors_for(['ГСП 2'])
    assert out.series[0].color == colors['ГСП 2'] and out.series[1].color == '' and out.series[2].color == '#123456'
    assert out.series[3].color == colors_for(['ГСП-3'])['ГСП-3']
    assert chart.series[0].color == ''                                  # исходный результат не меняется
