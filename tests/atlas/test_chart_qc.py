"""Проверка качества рисунка графика (atlas/chart_qc.py): что на файле читается плохо.

Находка — подсказка: файл выгружается в любом случае, а снятая инженером находка не пропадает, а помечается «снято».
Проверяется три вещи: хороший график находок не даёт, каждый дефект находится на настоящем рисунке (а не только на
придуманных рамках), и решение инженера переживает перерисовку."""
from __future__ import annotations

import pytest

from atlas import axis_auto, chart_qc, export_any
from atlas.chart_style import apply_format, clean_format, clean_store, merge_formats
from atlas.contract import Axis, Chart, ParamError, Series
from atlas.render import chart_file

DATES = ['2024-01-01', '2024-02-01', '2024-03-01', '2024-04-01']
DAYS = [f'2024-{m:02d}-{d:02d}' for m in (1, 2, 3, 4) for d in range(1, 29)]


def _chart():
    c = Chart('builder-1', 'Проба сцены', Axis('Дата', scale='time'), Axis('Расход, тыс. м³/сут', from_zero=True), y2=Axis('Давление, кгс/см²'))
    c.series.append(Series('расход', DATES, [3.0, 47.0, 120.0, 80.0], 'bar'))
    c.series.append(Series('пласт', DATES, [31.0, 50.0, 97.0, 88.0], 'line', axis='y2', look={'valueLabels': True}))
    return c


def _bars(count, name='Скв. {}'):
    c = Chart('t', 'Категории', Axis('Скважина', scale='category'), Axis('Дебит'))
    c.series.append(Series('а', [name.format(i) for i in range(count)], [float(i) for i in range(count)], 'bar'))
    return c


def _found(chart, doc=None, **kw):
    if doc:
        chart = apply_format(chart, clean_format(doc))
    scene: list = []
    chart_file(chart, 'png', 150, scene=scene)
    return chart_qc.check(scene, chart, (chart.style.get('checks') or {}).get('skip') or (), **kw)


def _keys(found, live=True):
    return [f['key'] for f in found if not live or not f.get('skipped')]


# ---- настоящие рисунки ----

def test_good_chart_has_no_findings():
    assert _found(_chart()) == [] and _found(_bars(8)) == []


@pytest.mark.parametrize('doc, key, elements', [
    ({'elements': {'legend': {'dx': -0.3, 'dy': -0.94}}}, 'overlap:legend|title', ['legend', 'title']),
    ({'elements': {'legend': {'dy': -0.04}}}, 'overlap:axis-title:x|legend', ['axis-title:x', 'legend']),
    ({'elements': {'legend': {'dx': -0.2, 'dy': -0.08}}}, 'overlap:axis:x|legend', ['axis:x', 'legend']),
    ({'elements': {'label:пласт:2024-03-01': {'dx': -0.5, 'dy': -0.2}}}, 'overlap:labels|title', ['title', 'label:пласт:2024-03-01']),
    ({'elements': {'title': {'dx': -0.2}}}, 'off-edge:title', ['title']),
    ({'elements': {'legend': {'dy': -0.4}}}, 'legend-on-plot:legend', ['legend']),
])
def test_moved_element_is_found_where_it_hurts(doc, key, elements):
    """Инженер подвинул элемент туда, где он что-то закрыл или ушёл за край: находка называет оба элемента сцены."""
    found = _found(_chart(), doc)
    assert _keys(found) == [key], found
    assert found[0]['elements'] == elements and found[0]['code'] == key.split(':')[0] and found[0]['text']


def test_levels_and_plain_words():
    found = _found(_chart(), {'elements': {'legend': {'dx': -0.3, 'dy': -0.94}}})[0]
    assert found['level'] == 'warn' and found['text'] == 'Легенда и заголовок «Проба сцены» накладываются: один текст закрывает другой.'
    assert _found(_chart(), {'elements': {'legend': {'dy': -0.4}}})[0]['level'] == 'info'      # легенда на поле — не ошибка, а «посмотрите»


def test_crowded_value_labels_give_one_finding():
    c = Chart('t', 'Подписи', Axis('Дата', scale='time'), Axis('Давление, кгс/см²'))
    c.series.append(Series('пласт', DAYS, [50.0] * len(DAYS), 'line', look={'valueLabels': True}))
    found = _found(c)
    assert _keys(found) == ['overlap:labels']
    assert 'Подписи точек накладываются друг на друга' in found[0]['text'] and len(found[0]['elements']) <= chart_qc.SHOWN
    assert all(name.startswith('label:пласт:') for name in found[0]['elements'])


def test_tick_labels_that_run_into_each_other():
    """30 длинных подписей категорий рисовальщик наклоняет, но они всё равно сливаются; 8 коротких — нет."""
    found = _found(_bars(30, 'Скважина номер {}'))
    assert _keys(found) == ['ticks:axis:x'] and '29 из 29' in found[0]['text'] and found[0]['elements'] == ['axis:x']
    assert _found(_bars(8)) == []


def test_small_font_counts_from_the_page_width():
    """Рисунок шире листа при вставке уменьшат: шрифт проверяется уменьшенным, а в натуральную величину находки нет."""
    doc = {'chart': {'title_size': 7}}
    scene: list = []
    chart = apply_format(_chart(), clean_format(doc))
    chart_file(chart, 'png', 150, scene=scene)
    width = next(e for e in scene if e['id'] == 'plot')['mm'][0]
    assert width > chart_qc.PAGE_MM      # рисунок по умолчанию шире текста листа A4
    found = chart_qc.check(scene, chart)
    assert _keys(found) == ['small-font'] and found[0]['elements'] == ['title']
    assert 'после уменьшения рисунка до ширины листа (170 мм)' in found[0]['text'] and 'заголовок' in found[0]['text']
    assert chart_qc.check(scene, chart, page_mm=None) == []      # 7 пт в натуральную величину читается


def test_data_findings_empty_series_axis_and_outlier():
    c = _chart()
    c.series.append(Series('пусто', DATES, [None] * 4, 'line'))
    assert _keys(_found(c)) == ['empty:series:пусто']
    c = Chart('t', 'Пустая шкала', Axis('Дата', scale='time'), Axis('Давление'), y2=Axis('Темп'))
    c.series.append(Series('темп', DATES, [1.0, 2.0, 3.0, 4.0], 'line', axis='y2'))
    assert 'empty:axis:y' in _keys(_found(c))
    c = Chart('t', 'Ничего', Axis('Дата', scale='time'), Axis('Давление'))
    c.series.append(Series('а', DATES, [None] * 4, 'line'))
    found = chart_qc.check([], c)
    assert _keys(found) == ['empty:chart'] and found[0]['level'] == 'warn'
    c = Chart('t', 'Выброс', Axis('Дата', scale='time'), Axis('Давление'))
    c.series.append(Series('а', DAYS[:28], [50.0 + d % 3 for d in range(27)] + [900.0], 'line'))
    c = axis_auto.auto_chart(c)
    found = [f for f in _found(c) if f['code'] == 'outlier']
    assert [f['key'] for f in found] == ['outlier:axis:y'] and '1 выброс сжимает' in found[0]['text'] and found[0]['level'] == 'info'
    manual = apply_format(c, clean_format({'axes': {'y': {'min': '49', 'max': '53'}}}))      # инженер задал пределы: подсказка о выбросе снята
    assert not [f for f in chart_qc.check([], manual) if f['code'] == 'outlier']


# ---- придуманные рамки: пороги ----

def _box(key, kind, box, **extra):
    return {'id': key, 'kind': kind, 'box': box, **extra}


PLOT = _box('plot', 'plot', [0.1, 0.1, 0.9, 0.85], mm=[160.0, 100.0])


@pytest.mark.parametrize('scene, keys', [
    ([PLOT], []),
    # две строки вплотную (рамки текста заходят друг на друга полями) — не наложение; текст на тексте — наложение
    ([PLOT, _box('title', 'title', [0.1, 0.01, 0.5, 0.05]), _box('subtitle', 'subtitle', [0.1, 0.045, 0.4, 0.08])], []),
    ([PLOT, _box('title', 'title', [0.1, 0.01, 0.5, 0.05]), _box('subtitle', 'subtitle', [0.1, 0.03, 0.4, 0.065])], ['overlap:subtitle|title']),
    # скрытая подпись и элемент, которого нет на рисунке, в проверке не участвуют
    ([PLOT, _box('title', 'title', [0.1, 0.01, 0.5, 0.05]), _box('label:а:1', 'label', [0.2, 0.02, 0.25, 0.05], series='а', hidden=True)], []),
    ([PLOT, {'id': 'label:а:1', 'kind': 'label', 'missing': True}], []),
    # за край: чуть-чуть (округление) — нет, заметно — да
    ([PLOT, _box('axis-title:y', 'axis-title', [-0.002, 0.3, 0.03, 0.6], axis='y')], []),
    ([PLOT, _box('axis-title:y', 'axis-title', [-0.02, 0.3, 0.03, 0.6], axis='y')], ['off-edge:axis-title:y']),
    # деления: прямые подписи с зазором, прямые внахлёст, наклонные редкие и наклонные частые
    ([PLOT, _box('axis:x', 'axis', [0.1, 0.86, 0.9, 0.9], axis='x', size=10.0, rotation=0.0, ticks=[[0.1, 0.86, 0.2, 0.9], [0.21, 0.86, 0.3, 0.9]])], []),
    ([PLOT, _box('axis:x', 'axis', [0.1, 0.86, 0.9, 0.9], axis='x', size=10.0, rotation=0.0, ticks=[[0.1, 0.86, 0.2, 0.9], [0.18, 0.86, 0.3, 0.9]])], ['ticks:axis:x']),
    ([PLOT, _box('axis:x', 'axis', [0.1, 0.86, 0.9, 0.99], axis='x', size=10.0, rotation=45.0, ticks=[[0.1, 0.86, 0.2, 0.99], [0.14, 0.86, 0.24, 0.99]])], []),
    ([PLOT, _box('axis:x', 'axis', [0.1, 0.86, 0.9, 0.99], axis='x', size=10.0, rotation=45.0, ticks=[[0.1, 0.86, 0.2, 0.99], [0.12, 0.86, 0.22, 0.99]])], ['ticks:axis:x']),
    # поле: тесное и нормальное; кривые сжаты в полоску, прямая линия — не «сжато»
    ([_box('plot', 'plot', [0.3, 0.3, 0.8, 0.8], mm=[160.0, 100.0])], ['small-plot']),
    ([PLOT, _box('series:а', 'series', [0.1, 0.4, 0.9, 0.5], series='а', axis='y')], ['flat:axis:y']),
    ([PLOT, _box('series:а', 'series', [0.1, 0.4, 0.9, 0.405], series='а', axis='y')], []),
    ([PLOT, _box('series:а', 'series', [0.1, 0.2, 0.9, 0.7], series='а', axis='y')], []),
])
def test_thresholds(scene, keys):
    assert _keys(chart_qc.check(scene, page_mm=None)) == keys


# ---- решение инженера ----

def test_skipped_finding_stays_in_the_list_marked():
    move = {'elements': {'legend': {'dx': -0.3, 'dy': -0.94}, 'title': {'dx': 0.0}}}
    found = _found(_chart(), {**move, 'checks': {'skip': ['overlap:legend|title']}})
    assert _keys(found) == [] and _keys(found, live=False) == ['overlap:legend|title'] and found[0]['skipped'] is True
    assert chart_qc.summary(found) == ''
    by_code = _found(_chart(), {**move, 'checks': {'skip': ['overlap']}})      # снять можно и всю проверку разом
    assert by_code[0].get('skipped') is True
    live = _found(_chart(), move)
    assert chart_qc.summary(live) == 'Проверка качества: 1 замечание (наложение).'


def test_skipped_go_last_and_warnings_first():
    scene = [_box('plot', 'plot', [0.3, 0.3, 0.8, 0.8], mm=[160.0, 100.0]), _box('title', 'title', [-0.05, 0.01, 0.5, 0.05]),
             _box('legend', 'legend', [0.2, 0.02, 0.4, 0.06])]
    assert _keys(chart_qc.check(scene, page_mm=None)) == ['overlap:legend|title', 'off-edge:title', 'small-plot']
    found = chart_qc.check(scene, skip=['overlap:legend|title'], page_mm=None)
    assert [(f['key'], bool(f.get('skipped'))) for f in found] == [('off-edge:title', False), ('small-plot', False), ('overlap:legend|title', True)]


def test_model_keeps_skipped_checks_for_one_chart_only():
    doc = clean_format({'checks': {'skip': ['overlap:legend|title', 'overlap:legend|title', '', 'small-font']}, 'chart': {'title_size': 14}})
    assert doc == {'chart': {'title_size': 14.0}, 'checks': {'skip': ['overlap:legend|title', 'small-font']}}
    assert clean_format({'checks': {'skip': []}}) == {} and clean_format({'checks': {}}) == {}
    with pytest.raises(ParamError, match='Проверка качества'):
        clean_format({'checks': {'skip': 'overlap'}})
    assert merge_formats(doc, clean_format({'checks': {'skip': ['ticks:axis:x']}}))['checks'] == {'skip': ['ticks:axis:x']}
    store = clean_store({'theme': doc, 'types': {'gdi': doc}, 'charts': {'gdi::ipr': doc}, 'templates': {'отчёт': doc}})
    assert store['charts']['gdi::ipr']['checks'] == {'skip': ['overlap:legend|title', 'small-font']}
    for shared in (store['theme'], store['types']['gdi'], store['templates']['отчёт']):
        assert shared == {'chart': {'title_size': 14.0}}


def test_preview_returns_findings_and_file_is_not_blocked():
    doc = clean_format({'elements': {'legend': {'dx': -0.3, 'dy': -0.94}}})
    body = export_any.preview(_chart(), {'doc': doc})
    assert [f['key'] for f in body['checks']] == ['overlap:legend|title']
    assert export_any.preview(_chart(), {})['checks'] == []
    skipped = export_any.preview(_chart(), {'doc': {**doc, 'checks': {'skip': ['overlap:legend|title']}}})
    assert [(f['key'], f.get('skipped')) for f in skipped['checks']] == [('overlap:legend|title', True)]
    assert skipped['image'] == body['image']      # снятая находка рисунок не меняет
    assert export_any.export(_chart(), {'format': 'png', 'dpi': 150, 'doc': doc})[0][:4] == b'\x89PNG'      # с находкой файл всё равно выгружается
