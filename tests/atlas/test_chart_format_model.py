"""Единая модель оформления (atlas/chart_style.py): документ, уровни, наложение на график, перевод старых мест хранения."""
import pytest

from atlas.chart_style import (apply_format, clean_axis, clean_chart, clean_format, clean_look, format_from_any, format_from_layout,
                               format_from_view, merge_formats)
from atlas.contract import Axis, Chart, ParamError, Series


def chart():
    return Chart(id='c', title='График', x=Axis(label='Дата', unit='', scale='value'), y=Axis(label='Q', unit='тыс. м³/сут'),
                 y2=Axis(label='P', unit='кгс/см²'),
                 series=[Series(name='№ 1', x=[1, 2, 3], y=[10, 20, 30], kind='line'), Series(name='№ 2', x=[1, 2], y=[5, 6], axis='y2', kind='points')])


def test_v2_fields_validated():
    assert clean_look({'hollow': True, 'marker_border': '#AA0000', 'label_position': 'top', 'label_decimals': '2', 'dash': 'dashdot'}, 1) == \
        {'hollow': True, 'marker_border': '#aa0000', 'label_position': 'top', 'label_decimals': 2, 'dash': 'dashdot'}
    assert clean_axis({'ticks': 'in', 'units': 'thousands', 'label_rotate': '-45', 'minor_step': '5', 'cross': '0'}, 'Y') == \
        {'ticks': 'in', 'units': 'thousands', 'label_rotate': -45.0, 'minor_step': '5', 'cross': '0'}
    assert clean_chart({'legend': 'left', 'legend_columns': 3, 'subtitle': ' Сезон 2025 ', 'grid_dash': 'dot'}) == \
        {'legend': 'left', 'legend_columns': 3, 'subtitle': 'Сезон 2025', 'grid_dash': 'dot'}


@pytest.mark.parametrize('bad', [{'chart': {'legend_columns': 0}}, {'axes': {'y': {'ticks': 'вверх'}}},
                                 {'series': {'a|line': {'label_position': 'везде'}}}, {'axes': {'x': {'label_rotate': 120}}}])
def test_bad_values_explained(bad):
    with pytest.raises(ParamError):
        clean_format(bad)


def test_empty_parts_dropped_and_unknown_ignored():
    assert clean_format({'chart': {'чужое': 1}, 'axes': {'y': {}}, 'series': {'a|line': {}}, 'лишнее': {}}) == {}


def test_levels_merge_field_by_field():
    theme = {'chart': {'font': 'times', 'legend': 'bottom'}, 'axes': {'y': {'ticks': 'in', 'decimals': 1}}}
    kind = {'chart': {'legend': 'top'}, 'series': {'№ 1|line': {'color': '#ff0000', 'width': 3}}}
    own = {'axes': {'y': {'decimals': 2}}, 'series': {'№ 1|line': {'width': 1}}}
    assert merge_formats(theme, None, kind, own) == {
        'chart': {'font': 'times', 'legend': 'top'}, 'axes': {'y': {'ticks': 'in', 'decimals': 2}},
        'series': {'№ 1|line': {'color': '#ff0000', 'width': 1}}}
    assert theme['axes']['y']['decimals'] == 1          # уровни не портятся


def test_apply_format_to_chart():
    doc = clean_format({'chart': {'legend': 'left'}, 'axes': {'y': {'min': '0', 'max': '40', 'step': '10', 'minor_step': '5', 'ticks': 'in'},
                                                             'y2': {'color': '#123456', 'cross': '3'}, 'y5': {'min': '1'}},
                        'series': {'№ 1|line': {'color': '#ff0000', 'opacity': 0.5}}})
    notes = []
    out = apply_format(chart(), doc, notes)
    assert out.style == {'legend': 'left'}
    assert (out.y.minimum, out.y.maximum, out.y.step) == (0, 40, 10)
    assert out.y.style == {'ticks': 'in', 'minor_step': 5.0}
    assert out.y2.color == '#123456' and out.y2.style == {'cross': 3.0}
    assert out.series[0].look == {'color': '#ff0000', 'opacity': 0.5} and out.series[0].opacity == 0.5
    assert out.series[1].look is None
    assert chart().y.minimum is None and not notes         # исходный график не меняется


def test_log_refused_for_non_positive_values():
    notes = []
    c = chart()
    c.series[0].y[0] = 0
    out = apply_format(c, {'axes': {'y': {'log': True}}}, notes)
    assert out.y.scale == 'value' and 'логарифмическая' in notes[0].text


def test_minor_step_on_dates_is_a_note():
    c = chart()
    c.x.scale = 'time'
    notes = []
    apply_format(c, {'axes': {'x': {'minor_step': '5'}}}, notes)
    assert 'доп. шаг' in notes[0].text


def test_legacy_sources_convert():
    layout = {'chart_style': {'legend': 'top'}, 'axis_style': {'y': {'decimals': 1}}, 'series': [{'look': {'color': '#00ff00'}}]}
    assert format_from_layout(layout) == {'chart': {'legend': 'top'}, 'axes': {'y': {'decimals': 1}}}
    assert format_from_view({'looks': {'№ 1|line': {'width': 4}, 'плохой|line': {'width': 'много'}}}) == {'series': {'№ 1|line': {'width': 4.0}}}
    assert format_from_view(None) == {}
    any_settings = {'format': 'png', 'chart': {'title': 'Свой', 'grid': 'h'}, 'axes': {'x': {'min': '1'}},
                    'view': {'looks': {'№ 2|points': {'size': 10}}, 'hidden': ['№ 1']}}
    assert format_from_any(any_settings) == {'chart': {'grid': 'h'}, 'axes': {'x': {'min': '1'}}, 'series': {'№ 2|points': {'size': 10.0}}}


def test_store_validated_and_cleaned():
    from atlas.chart_style import clean_store
    assert clean_store({'theme': {'chart': {'legend': 'top'}, 'series': {}}, 'types': {'gdi': {'axes': {'y': {'decimals': 1}}}, 'пусто': {}}}) == \
        {'theme': {'chart': {'legend': 'top'}}, 'types': {'gdi': {'axes': {'y': {'decimals': 1}}}}}
    for bad in ([], {'other': {}}, {'types': []}, {'theme': {'chart': {'legend': 'внизу'}}}):
        with pytest.raises(ParamError):
            clean_store(bad)


def test_store_applies_theme_then_type():
    from atlas.chart_style import apply_store
    from atlas.contract import Note, Result
    settings = {'chart_formats': {'theme': {'chart': {'legend': 'top', 'font': 'times'}, 'series': {'№ 1|line': {'color': '#ff0000'}}},
                                  'types': {'gdi': {'chart': {'legend': 'right'}}}}}
    result = Result(charts=[chart()], notes=[Note('из модуля')])
    gdi = apply_store(result, settings, 'gdi')
    assert gdi.charts[0].style == {'legend': 'right', 'font': 'times'} and gdi.charts[0].series[0].look == {'color': '#ff0000'}
    other = apply_store(result, settings, 'production')
    assert other.charts[0].style == {'legend': 'top', 'font': 'times'}
    assert apply_store(result, {}, 'gdi') is result and result.charts[0].style == {}
    bad = apply_store(result, {'chart_formats': {'theme': {'axes': {'y': {'min': '50', 'max': '10'}}}}}, 'gdi')
    assert bad.charts[0].y.minimum is None and 'не применено' in bad.notes[-1].text and bad.notes[0].text == 'из модуля'
