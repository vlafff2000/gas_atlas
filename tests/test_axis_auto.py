from __future__ import annotations

import numpy as np

from atlas import axis_auto
from atlas.contract import Axis, Chart, Result, Series


def chart(y, kind='line', **axis):
    return Chart('c', 'T', Axis('Дата', scale='time'), Axis('Давление', 'кгс/см²', **axis),
                 series=[Series('s', np.arange(len(y)), np.array(y, float), kind)])


def bounds(c):
    return c.y.minimum, c.y.maximum, c.y.step


def test_tight_round_bounds_cover_all_points():
    c = axis_auto.auto_chart(chart([44.3, 60, 87.2]))
    assert bounds(c) == (40.0, 90.0, 10.0)
    assert c.y.auto == {'min': 40.0, 'max': 90.0, 'step': 10.0, 'n': 5, 'zero': False, 'why': 'cut', 'lo': 44.3, 'hi': 87.2, 'anchor': False}


def test_data_is_not_squeezed_into_half_of_the_field():
    """Сбои прежнего подбора (5 делений, шаги 1–2–5): 10–100 → 0…250, 0–523 → 0…1000, столбцы 41–100,5 → 0…250."""
    assert bounds(axis_auto.auto_chart(chart([10, 55, 100]))) == (0.0, 100.0, 20.0)
    assert bounds(axis_auto.auto_chart(chart([0, 300, 523]))) == (0.0, 600.0, 100.0)
    assert bounds(axis_auto.auto_chart(chart([41, 100.5], kind='bar'))) == (0.0, 120.0, 20.0)


def test_no_binary_tails_in_bounds():
    """Прежде: 98,7–99,4 → (98.60000000000001, 99.60000000000001)."""
    assert bounds(axis_auto.auto_chart(chart([98.7, 99.0, 99.4]))) == (98.6, 99.4, 0.2)


def test_axis_starts_above_zero_when_data_is_far_from_it():
    """Давление 40–100: шкала срезана (30…100), а не от нуля; с запасом — минимум не лежит на оси X."""
    assert bounds(axis_auto.auto_chart(chart([40, 70, 100]))) == (30.0, 100.0, 10.0)


def test_manual_parts_are_kept_and_the_rest_is_fitted():
    """Последнее слово за инженером: заданное не трогается, подбирается только незаданное."""
    assert bounds(axis_auto.auto_chart(chart([44, 87], minimum=0.0))) == (0.0, 100.0, 20.0)
    assert bounds(axis_auto.auto_chart(chart([44, 87], maximum=100.0))) == (40.0, 100.0, 10.0)
    assert bounds(axis_auto.auto_chart(chart([44, 87], step=25.0))) == (25.0, 100.0, 25.0)
    for c in (chart([44, 87], minimum=0.0, maximum=150.0), chart([44, 87], scale='log'), chart([44, 87], kind='box')):
        assert axis_auto.auto_chart(c) is c
    assert axis_auto.auto_chart(chart([])).y.minimum is None


def test_fit_modes():
    assert bounds(axis_auto.auto_chart(chart([44, 87], from_zero=True))) == (0.0, 100.0, 20.0)
    assert bounds(axis_auto.auto_chart(chart([44, 87], style={'fit': 'zero'}))) == (0.0, 100.0, 20.0)
    assert bounds(axis_auto.auto_chart(chart([41, 100.5], kind='bar', style={'fit': 'data'}))) == (30.0, 110.0, 10.0)


def test_bars_start_at_zero_with_round_top():
    assert bounds(axis_auto.auto_chart(chart([3, 41, 87], kind='bar'))) == (0.0, 100.0, 20.0)
    assert bounds(axis_auto.auto_chart(chart([-40, 20, 60], kind='bar'))) == (-40.0, 60.0, 20.0)


def test_stack_uses_sums():
    c = Chart('c', 'T', Axis('x', scale='category', categories=['a', 'b']), Axis('v'),
              series=[Series('s1', ['a', 'b'], np.array([40., 10.]), 'bar', stack='k'),
                      Series('s2', ['a', 'b'], np.array([30., 10.]), 'bar', stack='k'),
                      Series('s3', ['a', 'b'], np.array([-5., None]), 'bar', stack='k')])
    assert axis_auto.extent(c, 'y') == (-5.0, 70.0, True)              # сумма 70, а не 40; отрицательная часть стопки отдельно
    assert bounds(axis_auto.auto_chart(c)) == (-10.0, 70.0, 10.0)


def test_all_axes_share_tick_count():
    c = chart([44.3, 60, 87.2])
    c.y2 = Axis('Уровень', 'м', inverse=True)
    c.y3 = Axis('Расход', 'тыс. м³/сут')
    c.series.append(Series('lvl', np.arange(3), np.array([300., 500., 900.]), 'line', axis='y2'))
    c.series.append(Series('q', np.arange(3), np.array([150., 2000., 5000.]), 'line', axis='y3'))
    out = axis_auto.auto_chart(c)
    counts = {round((a.maximum - a.minimum) / a.step) for a in (out.y, out.y2, out.y3)}
    assert counts == {out.y.auto['n']} and all(a.minimum <= lo and a.maximum >= hi for a, lo, hi in ((out.y, 44.3, 87.2), (out.y2, 300, 900), (out.y3, 150, 5000)))
    c.y2 = Axis('Уровень', 'м', minimum=0.0, maximum=1000.0)          # вручную — границы не трогаем, шаг по общей сетке
    kept = axis_auto.auto_chart(c)
    assert (kept.y2.minimum, kept.y2.maximum) == (0.0, 1000.0) and kept.y2.step == 1000.0 / kept.y.auto['n']


def test_refit_recomputes_own_values_and_keeps_changed_ones():
    """Повторный подбор (после оформления, вида с экрана): своё пересчитывает, изменённое кем-то считает ручным."""
    import dataclasses
    once = axis_auto.auto_chart(chart([44.3, 60, 87.2]))
    assert axis_auto.auto_chart(once) is once
    more = dataclasses.replace(once, series=[Series('s', np.arange(3), np.array([44.3, 60., 187.2]), 'line')])
    assert bounds(axis_auto.auto_chart(more)) == (40.0, 200.0, 40.0) or axis_auto.auto_chart(more).y.maximum >= 187.2
    zoomed = dataclasses.replace(once, y=dataclasses.replace(once.y, minimum=50.0, maximum=80.0))      # границы с экрана
    out = axis_auto.auto_chart(zoomed)
    assert (out.y.minimum, out.y.maximum) == (50.0, 80.0) and out.y.auto is None and out.y.step is None


def test_non_negative_data_never_goes_below_zero():
    assert axis_auto.auto_chart(chart([0.2, 3.0])).y.minimum >= 0
    assert axis_auto.auto_chart(chart([-5, 3.0])).y.minimum < 0


def test_missing_values_are_skipped():
    assert bounds(axis_auto.auto_chart(chart([None, 44.3, float('nan'), 87.2, float('inf')]))) == (40.0, 90.0, 10.0)


def test_apply_keeps_result_without_charts():
    r = Result()
    assert axis_auto.apply(r) is r


def test_export_preview_bar_chart_converts_and_starts_at_zero():
    """Интерактивный предпросмотр выгрузки: столбцы Plotly (у них нет line и marker.symbol) переводятся в график, шкала от нуля."""
    import plotly.graph_objects as go
    from atlas.export_chart import to_chart
    fig = go.Figure(go.Bar(x=['1', '2', '3'], y=[44, 60, 87]))
    fig.update_xaxes(type='category')
    out = axis_auto.auto_chart(to_chart(fig))
    assert out.series[0].kind == 'bar' and (out.y.minimum, out.y.maximum) == (0.0, 100.0)


def test_fit_mode_from_format_is_stronger_than_module_flag():
    """Режим «Подбор пределов» из оформления (панель «Формат») главнее признака раздела «от нуля»; ручная граница главнее режима."""
    from atlas import chart_style
    base = chart([44.3, 60, 87.2], from_zero=True)
    assert bounds(axis_auto.auto_chart(base)) == (0.0, 100.0, 20.0)
    by_data = chart_style.apply_format(base, chart_style.clean_format({'axes': {'y': {'fit': 'auto'}}}))
    assert by_data.y.style['fit'] == 'auto' and bounds(axis_auto.auto_chart(by_data)) == (40.0, 90.0, 10.0)
    manual = chart_style.apply_format(base, chart_style.clean_format({'axes': {'y': {'fit': 'data', 'min': '10'}}}))
    assert bounds(axis_auto.auto_chart(manual)) == (10.0, 90.0, 20.0)
    import pytest
    with pytest.raises(Exception):
        chart_style.clean_format({'axes': {'y': {'fit': 'smart'}}})


def test_format_after_fit_is_refitted_not_stuck():
    """Оформление накладывается на уже подобранный график (файлы): подобранное раньше не мешает новому режиму и логарифму."""
    from atlas import chart_style
    fitted = axis_auto.auto_chart(chart([44.3, 60, 87.2]))
    zero = axis_auto.auto_chart(chart_style.apply_format(fitted, chart_style.clean_format({'axes': {'y': {'fit': 'zero'}}})))
    assert bounds(zero) == (0.0, 100.0, 20.0)
    log = axis_auto.auto_chart(chart_style.apply_format(fitted, chart_style.clean_format({'axes': {'y': {'log': True}}})))
    assert log.y.scale == 'log' and bounds(log) == (None, None, None) and log.y.auto is None


def test_outlier_is_reported_not_dropped():
    """Единичный выброс: шкала накрывает все точки, а в подсказке — сколько выбросов и какие пределы были бы без них. Решает инженер."""
    y = list(60 + 10 * np.sin(np.linspace(0, 12, 200))) + [5000.0]
    out = axis_auto.auto_chart(chart(y))
    assert bounds(out) == (0.0, 5000.0, 1000.0)
    hint, = out.y.auto['hints']
    assert (hint['kind'], hint['count'], hint['values'], hint['min'], hint['max']) == ('outlier', 1, [5000.0], 45.0, 70.0) and hint['share'] < 0.01
    assert 'hints' not in axis_auto.auto_chart(chart(y[:-1])).y.auto                       # без выброса подсказки нет
    assert 'hints' not in axis_auto.auto_chart(chart(y, maximum=100.0)).y.auto             # пределы уже заданы инженером
    many = list(60 + 10 * np.sin(np.linspace(0, 12, 200))) + [5000.0] * 20                   # 20 высоких точек — не выбросы, а данные
    assert 'hints' not in axis_auto.auto_chart(chart(many)).y.auto
    assert 'hints' not in axis_auto.auto_chart(chart([3, 4, 5000], kind='bar')).y.auto     # мало точек и столбцы
