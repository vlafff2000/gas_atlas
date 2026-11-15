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
