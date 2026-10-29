"""Порядок подписей в легенде по возрастанию: сезоны, даты, номера скважин, группы; настройка проекта ``legend_order``."""
import dataclasses

from atlas import legend_order
from atlas.contract import Axis, Chart, ChartTable, Series
from atlas.projects import EDITABLE_SETTINGS
from atlas.render import to_plotly


def chart(*series, table=None):
    c = Chart('production-1', 'Тест', Axis('Дата'), Axis('Объём'), series=list(series))
    c.table = table
    return c


def names(c):
    return [s.name for s in c.series]


def test_seasons_years_and_wells_in_natural_order():
    c = chart(*[Series(n, [1], [1], 'bar') for n in ['2026-2027', '2025-2026', '2024-2025']])
    assert names(legend_order.apply(c)) == ['2024-2025', '2025-2026', '2026-2027']
    wells = chart(*[Series(n, [1], [1], 'line') for n in ['№ 10', '№ 9', '№ 101', '№ 2']])
    assert names(legend_order.apply(wells)) == ['№ 2', '№ 9', '№ 10', '№ 101']


def test_dates_sorted_by_day_month_year():
    c = chart(*[Series(n, [1], [1], 'points') for n in ['Конец закачки 15.02.2024', 'Конец закачки 01.12.2023', 'Конец закачки 01.02.2024']])
    assert names(legend_order.apply(c)) == ['Конец закачки 01.12.2023', 'Конец закачки 01.02.2024', 'Конец закачки 15.02.2024']


def test_groups_use_group_not_name_and_keep_numbers_natural():
    c = chart(*[Series('Закачка', [1], [1], 'line', group=g) for g in ['ГСП-10', 'ГСП 2', 'Без группы', 'ГСП-1']])
    assert [s.group for s in legend_order.apply(c).series] == ['Без группы', 'ГСП-1', 'ГСП 2', 'ГСП-10']     # текст — по алфавиту, номера — по числу


def test_facet_values_order_within_one_name():
    series = [Series('Замер', [1], [1], 'points', facets={'Скважина': f'№ {w}'}) for w in (12, 3, 7)]
    assert [s.facets['Скважина'] for s in legend_order.apply(chart(*series)).series] == ['№ 3', '№ 7', '№ 12']


def test_module_mode_and_small_charts_untouched():
    c = chart(*[Series(n, [1], [1], 'bar') for n in ['2026-2027', '2025-2026']])
    assert legend_order.apply(c, 'module') is c
    single = chart(Series('b', [1], [1], 'bar'))
    assert legend_order.apply(single) is single
    assert legend_order.apply([c]) == [c]          # не график — без изменений


def test_source_chart_is_not_mutated_and_table_follows_series():
    c = chart(Series('2026', [1], [1], 'bar'), Series('2025', [1], [2], 'bar'),
              table=ChartTable(['2026', '2025'], ['A'], [['5'], ['7']], colors=['#111111', '#222222']))
    out = legend_order.apply(c)
    assert names(c) == ['2026', '2025']                      # исходный объект (кэш) не тронут
    assert names(out) == ['2025', '2026']
    assert out.table.rows == ['2025', '2026'] and out.table.cells == [['7'], ['5']]
    assert out.table.colors == ['#222222', '#111111']


def test_table_not_aligned_to_series_is_kept():
    c = chart(Series('2026', [1], [1], 'bar'), Series('2025', [1], [1], 'bar'),
              table=ChartTable(['ГСП 1', 'ГСП 2'], ['A'], [['1'], ['2']], swatches=False))
    assert legend_order.apply(c).table is c.table


def test_export_legend_follows_sorted_order():
    fig = to_plotly(legend_order.apply(chart(Series('2026-2027', [1], [1], 'line'), Series('2025-2026', [1], [1], 'line'))))
    assert [t.name for t in fig.data] == ['2025-2026', '2026-2027']


def test_setting_is_editable_and_defaults_to_asc():
    assert EDITABLE_SETTINGS['legend_order']('module') and EDITABLE_SETTINGS['legend_order']('asc')
    assert not EDITABLE_SETTINGS['legend_order']('desc')
    assert legend_order.mode_of({}) == 'asc' and legend_order.mode_of({'legend_order': 'module'}) == 'module'
    assert legend_order.mode_of({'legend_order': 'bad'}) == 'asc'
