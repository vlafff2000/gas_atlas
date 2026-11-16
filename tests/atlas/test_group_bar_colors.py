"""Столбцы по группам в итогах по сезонам: цвет — цвет группы из общей палитры, а не один на все столбцы."""
import pandas as pd

from atlas import group_colors, group_paint
from atlas.contract import Axis, Chart, Result, Series
from atlas.modules import an_charts


def _means():
    return pd.DataFrame({'period': ['Весь сезон'] * 3, 'scope': ['ГСП 1', 'ГСП 2', 'Объект'], 'mean': [100.0, 150.0, 250.0], 'days': [10, 12, 12]})


def test_group_means_chart_has_a_bar_per_group_in_its_color():
    group_colors.set_known_groups(['ГСП 1', 'ГСП 2'])
    chart = an_charts.group_means_chart('withdrawal', '2024', _means())
    want = group_colors.colors_for(['ГСП 1', 'ГСП 2'])
    assert {s.name: s.color for s in chart.series} == want and len(set(want.values())) == 2


def test_paint_colors_any_single_bar_series_over_groups_but_not_seasons():
    group_colors.set_known_groups(['ГСП 1', 'ГСП 2'])
    by_group = Chart('g', 'Т', Axis('Группа', scale='category', categories=['ГСП 1', 'ГСП 2']), Axis('Скв.'),
                     series=[Series('Скважин', ['ГСП 1', 'ГСП 2'], [3, 4], 'bar')])
    by_season = Chart('s', 'Т', Axis('Сезон', scale='category', categories=['2023', '2024']), Axis('Скв.'),
                      series=[Series('Скважин', ['2023', '2024'], [3, 4], 'bar')])
    painted = group_paint.paint(Result(charts=[by_group, by_season])).charts
    want = group_colors.colors_for(['ГСП 1', 'ГСП 2'])
    assert {s.name: s.color for s in painted[0].series} == want
    assert len(painted[1].series) == 1 and painted[1].series[0].color == ''
