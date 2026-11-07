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
    # БД давлений по замерам: чужая скважина и другой сезон не попадают на график
    gdi = pd.DataFrame({'well': ['101', '101', '202'], 'date': pd.to_datetime(['2025-06-04', '2025-12-01', '2025-06-04']),
                        'p_res': [120.5, 99.0, 1.0], 'p_wellhead': 90.0})
    s = sel({K.ELPRO: elpro, K.PRESSURE_SURVEY: gdi}, elpro=['p', 'pres'])
    chart = curve_chart(s, ['101'], 'date')
    p, pres = chart.series[1:3]
    assert [name for name, _ in chart.right_axes()] == ['y2'] and p.axis == pres.axis == 'y2'     # одна шкала на оба ряда
    assert pres.kind == 'points' and list(pres.y) == [120.5] and pres.x[0] == pd.Timestamp('2025-06-04')   # чужая скважина и другой сезон — нет
    alone = curve_chart(sel({K.PRESSURE_SURVEY: gdi}, elpro=['pres']), ['101'], 'cumulative')
    assert [name for name, _ in alone.right_axes()] == ['y2'] and alone.series[1].x[0] == alone.series[0].x[3]   # по накопленному объёму — на дате замера
    assert axis_names(['pres', 'p']) == {'p': 'y2', 'pres': 'y2'}
    assert picked_extras(['hours', 'cru', 'p', 't', 'pres']) == ['hours', 'cru', 'p', 't', 'pres']


def test_group_off_days_are_not_idle_days():
    """Сутки, когда вся группа без часов и расхода (не пущена, остановлена), — не простой и не «нет записи»; решение за инженером."""
    from atlas.modules._production import averages_table
    dates = pd.date_range('2025-06-01', periods=10)
    rows = []
    for well in ('101', '102'):
        for i, day in enumerate(dates):
            idle_group = i >= 8 or i == 0                    # первые и последние сутки вся группа стоит (нули)
            lone_zero = well == '102' and i == 4             # а здесь простаивает одна скважина
            q, h = (0.0, 0.0) if idle_group or lone_zero else (1000.0 * (i + 1), 24.0)
            rows.append({'well': well, 'date': day, 'q': q, 'hours': h, 'kind': 'withdrawal', 'period': '2025', 'file': 'f',
                         'sheet': 's', '_row': i, '_point_id': f'{well}{i}'})
    prod = pd.DataFrame(rows)
    # у скважины 101 нет строки в сутки 5: записи нет, но группа работает (102 в работе) — это «нет записи», не остановка
    prod = prod[~((prod.well == '101') & (prod.date == dates[5]))]
    s = sel(periods=('2025',))
    s.df = prod
    s.mapping = {'101': {'group': 'ГСП 4'}, '102': {'group': 'ГСП 4'}}
    chart = curve_chart(s, ['101', '102'], 'date')
    gaps = [x for x in chart.series if x.name.startswith('Нет записи')]
    assert len(gaps) == 1 and gaps[0].name.endswith('1 сут')               # только день 5 у скважины 101
    line = next(x for x in chart.series if x.name.startswith('№ 102'))
    assert np.isnan(np.asarray(line.y, float)[[0, 8, 9]]).all() and line.y[4] == 0   # остановка группы — разрыв, простой скважины — 0
    assert getattr(s, 'group_off_days', None) is not None
    zero = averages_table(s, ['102']).frame.set_index('well').zero['102'].sum()
    assert zero == 1                                                       # считается только простой одной скважины
    s.params = {**s.params, 'groupoff': 'show'}
    s._work_days = None
    shown = curve_chart(s, ['101', '102'], 'date')
    assert np.asarray(next(x for x in shown.series if x.name.startswith('№ 102')).y, float)[0] == 0


def test_gis_annotation_events_on_q_chart_and_response():
    from atlas.modules._events import annotation_events
    ann = pd.DataFrame({'well': ['101', '101', '202'], 'date': pd.to_datetime(['2025-06-03'] * 3),
                        'pack': [None, 'А', None], 'kind': ['Ремонт', 'Ремонт', 'Остановка'], 'text': ['т'] * 3})
    ev = annotation_events(ann, ['101'])
    assert [e.label for e in ev] == ['ГИС: Ремонт · № 101'] and ev[0].kind == 'gis' and ev[0].well == '101'
    s = sel({K.GIS_ANNOTATIONS: ann})
    assert [e.label for e in curve_chart(s, ['101'], 'date').events if 'Ремонт' in e.label] == ['ГИС: Ремонт · № 101']


def test_krs_plan_events_are_intervals_from_start_to_end():
    from atlas.modules._events import krs_plan_events
    plan = pd.DataFrame({'well': ['101', '101', '101', '202'], 'year': [2025.0] * 4, 'kind': ['КР', 'КР', 'КР', 'КР'], 'status': ['выполнен', 'в процессе', 'нет', 'x'], 'in_table': ['Да', 'Да', 'Да', 'Да'],
                         'start': pd.to_datetime(['2025-06-02', '2025-06-08', None, '2025-06-02']),
                         'end': pd.to_datetime(['2025-06-05', None, None, '2025-06-05'])})
    ev = krs_plan_events(plan, ['101'])
    assert len(ev) == 2 and ev[0].kind == 'repair' and ev[0].x == pd.Timestamp('2025-06-02') and ev[0].x_end == pd.Timestamp('2025-06-05')
    assert '02.06.2025–05.06.2025' in ev[0].label and ev[1].x_end is None and 'в процессе' in ev[1].label     # без даты окончания — отметка начала
    s = sel({K.KRS_PLAN: plan})
    assert any(e.x_end is not None for e in curve_chart(s, ['101'], 'date').events)


def test_krs_plan_events_follow_table_71_rule():
    from atlas.modules._events import krs_plan_events
    plan = pd.DataFrame({'well': ['101'] * 3, 'year': [2025.0] * 3, 'kind': ['КР', 'КР', 'ТР'], 'status': ['', '', ''],
                         'in_table': ['Да', 'Нет', 'Да'], 'start': pd.to_datetime(['2025-06-02'] * 3), 'end': pd.to_datetime(['2025-06-05'] * 3)})
    assert len(krs_plan_events(plan, ['101'])) == 1        # «Нет» в таблицу 7.1 и текущий ремонт ТР событиями не показываются
