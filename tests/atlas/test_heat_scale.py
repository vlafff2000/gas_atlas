"""Цветовые шкалы тепловой карты: экран (heatScale.ts) и файл (heat_scale.py) берут одни и те же цвета."""
import re
from pathlib import Path

from atlas import heat_scale

TS = Path(__file__).resolve().parents[2] / 'web' / 'src' / 'heatScale.ts'


def test_ts_mirror_has_same_stops():
    text = TS.read_text(encoding='utf-8')
    for name, stops in heat_scale.STOPS.items():
        block = re.search(r'\b%s: \[(.*?)\],\n' % name, text.split('export const STOPS')[1], re.S).group(1)
        found = [tuple(int(v) for v in row.split(',')) for row in re.findall(r'\[([\d, ]+)\]', block)]
        assert found == stops, name
    assert 'DARK_LUMA = %d' % heat_scale.DARK_LUMA in text


def test_color_ends_and_reverse():
    assert heat_scale.color(0, 'blue') == (247, 251, 255) and heat_scale.color(1, 'blue') == (8, 48, 107)
    assert heat_scale.color(0, 'blue', reverse=True) == (8, 48, 107)
    assert heat_scale.color(0.5, 'gray') == (150, 150, 150)
    assert heat_scale.is_dark(heat_scale.color(1, 'orange')) and not heat_scale.is_dark(heat_scale.color(0, 'orange'))


def _heat():
    from atlas.contract import Axis, Chart, HeatMap
    h = HeatMap(['ГСП 1', 'ГСП 2'], ['2023/24', '2024/25'], [[10, 20], [None, 5]], [['10', '20'], ['', '5']], 'Скважин')
    return Chart('x', 'Карта', Axis('Сезон'), Axis('ГСП'), heat=h)


def test_style_validated_and_changes_file():
    import pytest
    from atlas.chart_special import figure_file
    from atlas.chart_style import clean_chart
    from atlas.contract import ParamError
    assert clean_chart({'heat_scale': 'blue', 'heat_reverse': True, 'heat_max': 40, 'heat_values': False})['heat_scale'] == 'blue'
    with pytest.raises(ParamError):
        clean_chart({'heat_scale': 'rainbow'})
    plain = figure_file(_heat(), 'png', 100)
    for style in ({'heat_scale': 'gray'}, {'heat_max': 40}, {'heat_values': False}, {'heat_bar': 'hide'}, {'heat_missing': 'пусто'}):
        chart = _heat()
        chart.style = style
        assert figure_file(chart, 'png', 100) != plain, style


def _strips():
    from atlas.contract import Axis, Chart, WellStrips
    rows = [f'№ {n}' for n in (12, 3, 101, 7)]
    s = WellStrips(rows, ['ГСП 1'] * 4, ['2023/24', '2024/25'], [[1, 0], [1, 1], [None, 1], [0, 0]], [1, 2, 1, 0])
    return Chart('s', 'Полосы', Axis('Сезон'), Axis('Скважина'), strips=s)


def test_strip_order_and_style_change_file():
    import pytest
    from atlas.chart_special import figure_file, strip_order
    from atlas.chart_style import clean_chart
    from atlas.contract import ParamError
    c = _strips().strips
    assert strip_order(c.rows, c.counts, [0, 1, 2, 3], None) == [0, 1, 2, 3]
    assert strip_order(c.rows, c.counts, [0, 1, 2, 3], 'count') == [1, 0, 2, 3]
    assert strip_order(c.rows, c.counts, [0, 1, 2, 3], 'number') == [1, 3, 0, 2]
    assert clean_chart({'strip_per_row': 4, 'strip_order': 'count', 'strip_counts': False})['strip_per_row'] == 4
    with pytest.raises(ParamError):
        clean_chart({'strip_order': 'random'})
    plain = figure_file(_strips(), 'png', 100)
    for style in ({'strip_per_row': 3}, {'strip_order': 'count'}, {'strip_counts': False}, {'strip_legend': False}, {'strip_empty_color': '#ff0000'}):
        chart = _strips()
        chart.style = style
        assert figure_file(chart, 'png', 100) != plain, style


def test_heat_layout_order_and_totals():
    from atlas import heat_layout
    rows, values = ['ГСП 10', 'ГСП 2', 'ГСП 1'], [[1, None], [5, 5], [2, 3]]
    assert heat_layout.row_order(rows, values, None) == [0, 1, 2]
    assert heat_layout.row_order(rows, values, 'sum') == [1, 2, 0]
    assert heat_layout.row_order(rows, values, 'name') == [2, 1, 0]          # «ГСП 2» перед «ГСП 10»
    assert heat_layout.total([1, None, 2], 'sum') == 3 and heat_layout.total([1, None, 2], 'mean') == 1.5 and heat_layout.total([None], 'sum') is None
    lay = heat_layout.layout(rows, values, {'heat_sort': 'sum', 'heat_totals': 'both', 'heat_total': 'mean'})
    assert lay['order'] == [1, 2, 0] and lay['row_totals'] == [5, 2.5, 1] and lay['col_totals'][0] == (5 + 2 + 1) / 3
    assert heat_layout.layout(rows, values, {})['row_totals'] is None
    assert heat_layout.text(2.25) == '2.2' and heat_layout.text(12.0) == '12'


def test_heat_sort_and_totals_change_file():
    from atlas.chart_special import figure_file
    plain = figure_file(_heat(), 'png', 100)
    for style in ({'heat_totals': 'rows'}, {'heat_totals': 'cols', 'heat_total': 'mean'}):
        chart = _heat()
        chart.style = style
        assert figure_file(chart, 'png', 100) != plain, style
    low_first = _heat()
    low_first.heat.values, low_first.heat.texts = [[1, 2], [30, 40]], [['1', '2'], ['30', '40']]
    sorted_ = _heat()
    sorted_.heat.values, sorted_.heat.texts = low_first.heat.values, low_first.heat.texts
    sorted_.style = {'heat_sort': 'sum'}
    assert figure_file(low_first, 'png', 100) != figure_file(sorted_, 'png', 100)
