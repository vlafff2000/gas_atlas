"""Линии тренда ряда: математика (atlas/trend.py), совпадение с экраном (web/src/trend.ts) и применение через оформление."""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from atlas.chart_style import apply_format, clean_format
from atlas.contract import Axis, Chart, Series
from atlas.trend import fit

X = [1, 2, 3, 4, 5, 6]
Y = [2.1, 3.9, 6.2, 7.8, 10.1, 12.0]


def test_linear_matches_numpy_and_text():
    got = fit('linear', X, Y)
    slope, icpt = np.polyfit(X, Y, 1)
    assert got['equation'] == f'y = {slope:.4g} x'.replace('.', ',').replace(' x', 'x') + f' + {icpt:.4g}'.replace('.', ',')
    pred = slope * np.array(X) + icpt
    r2 = 1 - ((np.array(Y) - pred) ** 2).sum() / ((np.array(Y) - np.mean(Y)) ** 2).sum()
    assert got['r2'] == pytest.approx(r2) and len(got['x']) == 120


def test_poly_power_exp_log_and_moving():
    poly = fit('poly', X, Y, order=3)
    assert np.allclose(np.polyval(np.polyfit(X, Y, 3), [1, 6]), [poly['y'][0], poly['y'][-1]])
    assert fit('power', X, Y)['equation'].startswith('y = 2,06x^0,9793')
    assert fit('exp', X, Y)['equation'].startswith('y = 1,853e^(0,3371x)')
    assert fit('log', X, Y)['equation'] == 'y = 5,429 ln(x) + 1,063'
    mov = fit('moving', X, Y, period=3)
    assert mov['y'] == pytest.approx([(2.1 + 3.9 + 6.2) / 3, (3.9 + 6.2 + 7.8) / 3, (6.2 + 7.8 + 10.1) / 3, (7.8 + 10.1 + 12.0) / 3]) and mov['r2'] is None


def test_unsuitable_data_gives_none():
    assert fit('log', [0, 1, 2], [1, 2, 3]) is None and fit('power', X, [1, 2, -3, 4, 5, 6]) is None
    assert fit('linear', [1], [1]) is None and fit('moving', X, Y, period=9) is None and fit('linear', [2, 2, 2], [1, 2, 3]) is None
    assert fit('poly', X[:3], Y[:3], order=3) is None


def test_time_axis_has_no_equation():
    got = fit('linear', ['2024-01-01', '2024-01-11', '2024-01-21', '2024-02-01', '2024-02-10', '2024-02-20'], Y)
    assert got['equation'] == '' and got['r2'] > 0.99


def chart():
    return Chart(id='c', title='T', x=Axis(label='x'), y=Axis(label='y'), series=[Series(name='Ряд', x=X, y=Y, kind='points', group='Г')])


def test_format_adds_trend_series_with_label_and_skips_bad():
    doc = clean_format({'series': {'Г|points': {'trend': 'poly', 'trend_order': 2, 'trend_label': True}}})
    notes = []
    out = apply_format(chart(), doc, notes)
    assert [s.name for s in out.series][0] == 'Ряд' and out.series[1].name.startswith('Тренд: Ряд (y = ') and 'R² = 0,9985' in out.series[1].name
    assert out.series[1].kind == 'line' and out.series[1].legend is False and out.series[1].group == 'Г' and not notes
    again = apply_format(out, doc)
    assert len(again.series) == 2                                     # повторное применение второй тренд не добавляет
    bad = apply_format(chart(), clean_format({'series': {'Г|points': {'trend': 'log'}}}), notes)
    assert len(bad.series) == 2
    neg = Chart(id='c', title='T', x=Axis(label='x'), y=Axis(label='y'), series=[Series(name='Ряд', x=[-1, 1, 2], y=[1, 2, 3], group='Г')])
    assert len(apply_format(neg, doc and clean_format({'series': {'Г|points': {'trend': 'log'}}}), notes).series) == 1 and 'не построен' in notes[-1].text


@pytest.mark.parametrize('bad', [{'trend': 'cubic'}, {'trend_order': 9}, {'trend_period': 1}])
def test_trend_fields_validated(bad):
    from atlas.contract import ParamError
    with pytest.raises(ParamError):
        clean_format({'series': {'Г|points': bad}})


@pytest.mark.skipif(shutil.which('node') is None, reason='нужен node: сверка с экранной математикой')
def test_screen_math_matches_server():
    script = Path(__file__).resolve().parents[2] / 'web' / 'scripts' / 'trend-check.mjs'
    run = subprocess.run(['node', '--experimental-strip-types', str(script)], capture_output=True, text=True, timeout=60)
    if run.returncode != 0:
        pytest.skip(f'node не смог запустить проверку: {run.stderr[-200:]}')
    screen = json.loads(run.stdout.strip().splitlines()[-1])
    dates = ['2024-01-01', '2024-01-11', '2024-01-21', '2024-02-01', '2024-02-10', '2024-02-20']
    cases = {'linear': fit('linear', X, Y), 'poly2': fit('poly', X, Y, 2), 'poly3': fit('poly', X, Y, 3), 'log': fit('log', X, Y), 'power': fit('power', X, Y),
             'exp': fit('exp', X, Y), 'moving': fit('moving', X, Y, period=3), 'time': fit('linear', dates, Y)}
    for name, want in cases.items():
        got = screen[name]
        assert got['equation'] == want['equation'], name
        assert got['n'] == len(want['x']), name
        assert got['first'] == pytest.approx(want['y'][0], rel=1e-6, abs=1e-9) and got['last'] == pytest.approx(want['y'][-1], rel=1e-6, abs=1e-9), name
        assert (got['r2'] is None) == (want['r2'] is None) and (want['r2'] is None or got['r2'] == pytest.approx(want['r2'], abs=1e-9)), name


def test_trend_reaches_the_file():
    from atlas.render import to_plotly
    from atlas.engine.core.export import figure_bytes
    plain = figure_bytes(to_plotly(chart()), 'png', 150, 150)
    styled = apply_format(chart(), clean_format({'series': {'Г|points': {'trend': 'linear', 'trend_color': '#ff0000'}}}))
    fig = to_plotly(styled)
    assert len(fig.data) == 2
    assert figure_bytes(fig, 'png', 150, 150) != plain


def test_annotations_validated_and_reach_the_file():
    from atlas.contract import ParamError
    from atlas.render import to_plotly
    from atlas.engine.core.export import figure_bytes
    note = [{'kind': 'hline', 'value': '8,5', 'text': 'Норма'}, {'kind': 'vband', 'value': '2', 'to': '4', 'text': 'Период', 'color': '#2a78d6'},
            {'kind': 'vline', 'value': '5'}, {'kind': 'text', 'x': '3', 'y': '9', 'text': 'Пик'}, {'kind': 'hband', 'value': '3', 'to': '5'}]
    doc = clean_format({'chart': {'annotations': note}})
    assert doc['chart']['annotations'][0] == {'kind': 'hline', 'value': '8,5', 'text': 'Норма'}
    plain = figure_bytes(to_plotly(chart()), 'png', 150, 150)
    marked = apply_format(chart(), doc)
    assert marked.style['annotations'] and figure_bytes(to_plotly(marked), 'png', 150, 150) != plain
    unreadable = apply_format(chart(), clean_format({'chart': {'annotations': [{'kind': 'hline', 'value': 'много'}]}}))
    assert figure_bytes(to_plotly(unreadable), 'png', 150, 150)          # не разобранное значение пропускается, файл строится
    for bad in ([{'kind': 'hline'}], [{'value': '1'}], [{'kind': 'band', 'value': '1'}], [{'kind': 'vband', 'value': '1'}], [{'kind': 'text', 'text': 'x'}], 'строка', [{'kind': 'hline', 'value': '1'}] * 31):
        with pytest.raises(ParamError):
            clean_format({'chart': {'annotations': bad}})


def test_hatch_for_bars_reaches_the_file():
    from atlas.contract import ParamError
    from atlas.render import to_plotly
    from atlas.engine.core.export import figure_bytes
    bars = Chart(id='b', title='T', x=Axis(label='x', scale='category'), y=Axis(label='y'),
                 series=[Series(name='Ряд', x=['а', 'б', 'в'], y=[3, 5, 4], kind='bar', group='Г')])
    plain = figure_bytes(to_plotly(bars), 'png', 150, 150)
    hatched = apply_format(bars, clean_format({'series': {'Г|bar': {'hatch': 'diag', 'hatch_color': '#333333'}}}))
    fig = to_plotly(hatched)
    assert fig.data[0].meta['hatch'] == 'diag' and figure_bytes(fig, 'png', 150, 150) != plain
    with pytest.raises(ParamError):
        clean_format({'series': {'Г|bar': {'hatch': 'волны'}}})


def _err(style, mode='percent'):
    c = Chart(id='c', title='T', x=Axis(label='x'), y=Axis(label='y'), series=[Series(name='Р', x=[1, 2, 3], y=[10, 20, None], group='Г')])
    doc = clean_format({'series': {'Г|points': {'err_mode': mode, 'err_value': 10, 'err_style': style}}})
    return c, apply_format(c, doc)


def test_error_interval_bars_band_abs():
    _, bars = _err('bars')
    assert [(list(s.x), list(s.y)) for s in bars.series[1:]] == [([1, 1, 1, 2, 2, 2], [9.0, 11.0, None, 18.0, 22.0, None])]
    _, band = _err('band')
    assert [s.name for s in band.series[1:]] == ['Погрешность: Р (верх)', 'Погрешность: Р (низ)'] and list(band.series[1].y) == [11.0, 22.0]
    _, absolute = _err('bars', 'abs')
    assert list(absolute.series[1].y)[:2] == [0.0, 20.0] and len(apply_format(absolute, clean_format({'series': {'Г|points': {'err_value': 10}}})).series) == 2
    off = apply_format(chart(), clean_format({'series': {'Г|points': {'err_value': 0}}}))
    assert len(off.series) == 1


def test_error_interval_reaches_the_file():
    from atlas.render import to_plotly
    from atlas.engine.core.export import figure_bytes
    base, marked = _err('bars')
    assert figure_bytes(to_plotly(marked), 'png', 150, 150) != figure_bytes(to_plotly(base), 'png', 150, 150)


@pytest.mark.skipif(shutil.which('node') is None, reason='нужен node')
def test_error_interval_screen_matches_server():
    script = Path(__file__).resolve().parents[2] / 'web' / 'scripts' / 'trend-check.mjs'
    run = subprocess.run(['node', '--experimental-strip-types', str(script)], capture_output=True, text=True, timeout=60)
    if run.returncode != 0:
        pytest.skip(f'node не смог запустить проверку: {run.stderr[-200:]}')
    screen = json.loads(run.stdout.strip().splitlines()[-1])['errors']
    for key, (style, mode) in {'barspercent': ('bars', 'percent'), 'bandpercent': ('band', 'percent'), 'barsabs': ('bars', 'abs')}.items():
        _, out = _err(style, mode)
        assert screen[key] == [{'name': s.name, 'x': list(s.x), 'y': list(s.y)} for s in out.series[1:]], key
