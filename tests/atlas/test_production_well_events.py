"""«Производительность скважин»: события скважины на графиках Q (ГДИ, ГИС, КРС, шаблонирование) и замеры Рпл на оси давления ЭЛПРО."""
import numpy as np
import pandas as pd

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules._elpro_series import axis_names, picked_extras
from atlas.modules._events import gis_events, krs_events, template_events
from atlas.modules._production import Selection, curve_chart

K = DatasetKind
DAYS = pd.date_range('2025-06-01', periods=10)


def sel(extra=None, periods=('2025',), **params):
    prod = pd.DataFrame({'well': '101', 'date': DAYS, 'q': np.arange(10) * 100.0, 'kind': 'withdrawal', 'period': '2025',
                         'hours': 24.0, 'file': 'f', 'sheet': 's', '_row': range(10), '_point_id': list('abcdefghij')})
    frames = {K.PRODUCTION: prod, **(extra or {})}
    data = Data(frames)
    data.mapping = {'101': {'group': 'ГСП 4'}}
    data.settings = {}
    base = {'kind': 'withdrawal', 'periods': list(periods), 'groups': ['ГСП 4'], 'wells': ['101'], 'direction': 'number', 'elpro': []}
    return Selection(data, {**base, **params})


def test_gis_krs_template_events_from_sources():
    gis = pd.DataFrame({'well': ['101', '101', '202'], 'date': pd.to_datetime(['2025-06-03', '2025-06-03', '2025-06-03'])})
    assert [e.label for e in gis_events(gis, ['101'])] == ['ГИС · № 101']
    krs = pd.DataFrame({'well': ['101', '202'], 'year': [2025.0, 2025.0], 'work_type': ['Ремонт колонны', 'x']})
    ev = krs_events(krs, ['101'])
    assert len(ev) == 1 and ev[0].kind == 'repair' and ev[0].x == pd.Timestamp('2025-07-01') and 'только год' in ev[0].label
    bottom = pd.DataFrame({'well': '101', 'date': pd.to_datetime(['2025-06-02', '2025-06-04', '2025-06-06']),
                           'bottom_m': 1.0, 'tool_diameter_mm': [58.0, np.nan, np.nan], 'method': ['', 'Шаблонировка', 'Замер забоя']})
    assert [e.x for e in template_events(bottom, ['101'])] == [pd.Timestamp('2025-06-02'), pd.Timestamp('2025-06-04')]


def test_events_on_both_charts_only_inside_selected_season():
    extra = {K.GIS_OBSERVATIONS: pd.DataFrame({'well': '101', 'date': pd.to_datetime(['2025-06-03', '2026-01-01'])}),
             K.KRS_WORKS: pd.DataFrame({'well': '101', 'year': [2025.0], 'work_type': ['КР']})}      # 1 июля 2025 — вне сезона
    s = sel(extra)
    by_date = curve_chart(s, ['101'], 'date').events
    kinds = [e.kind for e in by_date]
    assert 'gis' in kinds and 'repair' not in kinds and sum(k == 'gis' for k in kinds) == 1
    by_cum = curve_chart(s, ['101'], 'cumulative').events
    assert [e.kind for e in by_cum] == ['gis'] and isinstance(by_cum[0].x, float)


def test_pressure_overlay_shares_elpro_pressure_axis():
    elpro = pd.DataFrame({'well': '101', 'date': DAYS[[0, 2]], 'q': 1.0, 'kind': 'withdrawal', 't': 1.0, 'p': [50.0, 52.0], 'y': 1.0})
    gdi = pd.DataFrame({'well': ['101', '101', '202'], 'date': pd.to_datetime(['2025-06-04', '2025-12-01', '2025-06-04']),
                        'p_res': [120.5, 99.0, 1.0], 'q': 1.0, 'dp2': 1.0})
    s = sel({K.ELPRO: elpro, K.GDI: gdi}, elpro=['p', 'pres'])
    chart = curve_chart(s, ['101'], 'date')
    p, pres = chart.series[1:3]
    assert [name for name, _ in chart.right_axes()] == ['y2'] and p.axis == pres.axis == 'y2'     # одна шкала на оба ряда
    assert pres.kind == 'points' and list(pres.y) == [120.5] and pres.x[0] == pd.Timestamp('2025-06-04')   # чужая скважина и другой сезон — нет
    alone = curve_chart(sel({K.GDI: gdi}, elpro=['pres']), ['101'], 'cumulative')
    assert [name for name, _ in alone.right_axes()] == ['y2'] and alone.series[1].x[0] == alone.series[0].x[3]   # по накопленному объёму — на дате замера
    assert axis_names(['pres', 'p']) == {'p': 'y2', 'pres': 'y2'}
    assert picked_extras(['hours', 'cru', 'p', 't', 'pres']) == ['hours', 'cru', 'p', 't', 'pres']
