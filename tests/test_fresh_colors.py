"""Цвета кривых по свежести: «самый свежий — красный, второй — синий…» сразу для всех графиков (общее ядро chart_style)."""
from atlas.chart_style import apply_format, clean_format, series_key
from atlas.contract import Axis, Chart, Series


def _chart():
    return Chart('c', 'ГДИ', Axis('x'), Axis('y'), [
        Series('03.2024', [1], [2], group='03.2024', color='#111111', age=2),
        Series('06.2025', [1], [2], group='06.2025', color='#222222', age=1),
        Series('09.2025', [1], [2], group='09.2025', color='#333333', age=0),
        Series('Прочее', [1], [2], color='#444444'),
    ])


def test_clean_accepts_list_and_rejects_bad_color():
    doc = clean_format({'chart': {'fresh_colors': ['#DC3545', '#2563EB']}})
    assert doc['chart']['fresh_colors'] == ['#dc3545', '#2563eb']
    import pytest
    from atlas.contract import ParamError
    with pytest.raises(ParamError):
        clean_format({'chart': {'fresh_colors': ['красный']}})


def test_freshness_palette_colors_series_by_age():
    out = apply_format(_chart(), {'chart': {'fresh_colors': ['#ff0000', '#0000ff']}})
    by = {s.name: (s.look or {}).get('color') for s in out.series}
    assert by == {'09.2025': '#ff0000', '06.2025': '#0000ff', '03.2024': '#ff0000', 'Прочее': None}


def test_manual_color_of_one_series_wins():
    chart = _chart()
    key = series_key(chart.series[2])
    out = apply_format(chart, {'chart': {'fresh_colors': ['#ff0000', '#0000ff']}, 'series': {key: {'color': '#00ff00'}}})
    by = {s.name: (s.look or {}).get('color') for s in out.series}
    assert by['09.2025'] == '#00ff00' and by['06.2025'] == '#0000ff'


def test_gdi_chart_marks_age_by_date():
    import numpy as np
    import pandas as pd
    from atlas.engine.modules import gdi as legacy
    from atlas.modules.gdi import GdiModule
    q = np.array([20., 50., 80., 120.])
    frames = []
    for date in ('2024-03-01', '2025-06-01', '2025-09-01'):
        frames.append(pd.DataFrame(dict(well='31', date=pd.Timestamp(date), q=q, dp2=.7 * q + .012 * q * q, method='', study='', p_res=75.)))
    points = pd.concat(frames, ignore_index=True)
    params = dict(orientation='normal', crosshair=False, curves=False, db_curves=False, show_excluded=False)
    chart = GdiModule.chart(points, legacy.analyze(points), points, '31', params)
    ages = {s.name: s.age for s in chart.series if s.kind == 'points'}
    assert ages == {'01.09.2025': 0, '01.06.2025': 1, '01.03.2024': 2}
