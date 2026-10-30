"""«Авторский надзор: сезон» — общий расчёт сезона на малом примере, рассчитанном вручную."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.api import create_app
from atlas.contract import Data
from atlas.modules import an_charts, an_report, an_wells
from atlas.projects import Projects
from atlas.registry import modules

MAPPING = {'1': {'group': 'ГСП-1'}, '2': {'group': 'ГСП 1'}, '3': {'group': 'ГСП_2'}}


def production(rows, period):
    frame = pd.DataFrame(rows, columns=['well', 'date', 'q'])
    frame['date'] = pd.to_datetime(frame.date)
    frame['kind'] = 'withdrawal'
    frame['period'] = period
    return frame


# Сезон, в котором 29 февраля 2024 (високосный год): 27.02 — 01.03 — это 4 календарных суток.
LEAP = production([
    ('1', '2024-02-27', 1000), ('2', '2024-02-27', 500),
    ('1', '2024-02-28', 0), ('2', '2024-02-28', 500),
    ('1', '2024-02-29', 2000), ('2', '2024-02-29', 0), ('3', '2024-02-29', 300),
    ('1', '2024-03-01', 0), ('2', '2024-03-01', 0), ('3', '2024-03-01', 400),
], '2023-2024')

PRESSURE = pd.DataFrame({'date': pd.to_datetime(['2024-02-26', '2024-02-29', '2024-03-05']), 'pressure': [100.0, 95.0, 90.0]})


def test_season_summary_by_hand():
    summary, means = an_report.season_report(LEAP, MAPPING, PRESSURE, 'withdrawal', '2023-2024')
    assert summary['start'] == pd.Timestamp('2024-02-27')
    assert summary['stop'] == pd.Timestamp('2024-03-01')
    assert summary['days'] == 4                       # 27, 28, 29 февраля и 1 марта: високосный год учтён календарём
    assert summary['active_days'] == 4
    assert summary['wells'] == 3
    assert summary['mean'] == pytest.approx((1500 + 500 + 2300 + 400) / 4 / 1000)
    assert summary['peak'] == pytest.approx(2.3)
    assert summary['peak_date'] == pd.Timestamp('2024-02-29')
    assert summary['pressure_start'] == 100.0        # ближайшая дата — 26.02
    assert summary['pressure_peak'] == 95.0          # та же дата


def test_group_means_use_unified_names_and_skip_empty_days():
    _, means = an_report.season_report(LEAP, MAPPING, PRESSURE, 'withdrawal', '2023-2024')
    whole = means[means.period.eq(an_report.WHOLE)].set_index('scope')
    assert set(whole.index) == {an_report.OBJECT_SCOPE, 'ГСП 1', 'ГСП 2'}   # «ГСП-1» и «ГСП 1» — одна группа
    assert whole.loc['ГСП 1', 'days'] == 3          # 01.03 у ГСП 1 нулевой расход: не сутки с расходом
    assert whole.loc['ГСП 1', 'mean'] == pytest.approx((1500 + 500 + 2000) / 3 / 1000)
    assert whole.loc['ГСП 2', 'mean'] == pytest.approx((300 + 400) / 2 / 1000)
    feb = means[means.scope.eq(an_report.OBJECT_SCOPE) & means.period.eq('Февраль 2024')]
    assert feb['mean'].iloc[0] == pytest.approx((1500 + 500 + 2300) / 3 / 1000)


def test_non_leap_season_counts_calendar_days():
    frame = production([('1', '2023-02-27', 1000), ('1', '2023-03-01', 1000)], '2022-2023')
    summary, _ = an_report.season_report(frame, MAPPING, None, 'withdrawal', '2022-2023')
    assert summary['days'] == 3                       # 27.02, 28.02, 01.03 — без 29 февраля
    assert summary['pressure_start'] is None          # давления нет — пустое значение, не ошибка


def test_pressure_tie_takes_earlier_date():
    p = pd.DataFrame({'date': pd.to_datetime(['2024-02-27', '2024-03-01']), 'pressure': [1.0, 2.0]})
    assert an_report.pressure_near(p, pd.Timestamp('2024-02-28')) == 1.0      # 28.02 — ровно между датами


def test_empty_season_is_a_note_not_an_error():
    summary, means = an_report.season_report(LEAP, MAPPING, PRESSURE, 'injection', '2023-2024')
    assert summary is None and means.empty


def test_module_is_discovered_and_runs_on_demo(tmp_path):
    assert 'an_report' in modules()
    client = TestClient(create_app(Projects(tmp_path)))
    pid = client.post('/api/projects/demo').json()['id']
    r = client.post('/api/modules/an_report/run', json={'project': pid, 'params': {'kind': 'withdrawal', 'periods': []}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert not any('раздел в разработке' in n['text'] for n in body['notes'])
    assert any('Давление объекта: опорная сетка' in n['text'] for n in body['notes'])
    assert 'Выберите сезон' in ' '.join(n['text'] for n in body['notes'])
    r = client.post('/api/modules/an_report/run', json={'project': pid, 'params': {'kind': 'withdrawal', 'periods': ['2023-2024']}})
    assert r.status_code == 200, r.text
    ids = [t['id'] for t in r.json()['tables']]
    assert ids[:2] == ['an-season', 'an-season-means'] and {'an-fund', 'an-fund-classes'} <= set(ids)


def water_factor(rows):
    frame = pd.DataFrame(rows, columns=['date', 'water_day', 'wf', 'wf_cum'])
    frame['date'] = pd.to_datetime(frame.date)
    return frame


WATER = water_factor([
    ('2024-02-26', 5, 1.0, 1.0),        # до сезона: в сводку не попадает
    ('2024-02-28', 10, 2.0, 1.5),
    ('2024-02-29', 40, 4.0, 2.0),       # максимум выноса и суточного фактора
    ('2024-03-01', 20, 3.0, 2.5),       # максимум накопленного фактора (в конце сезона)
])


def test_water_peaks_use_season_window_and_peak_day_indicators():
    summary, _ = an_report.season_report(LEAP, MAPPING, PRESSURE, 'withdrawal', '2023-2024', an_report.water_table(WATER))
    assert summary['water_peak'] == 40
    assert summary['water_peak_date'] == pd.Timestamp('2024-02-29')
    assert summary['water_peak_q'] == pytest.approx(2.3)      # Q объекта на дату выноса: 2300 м³/сут
    assert summary['water_peak_wells'] == 2                    # 29.02: скважины 1 и 3
    assert summary['water_peak_pressure'] == 95.0
    assert summary['wf_peak'] == 4.0 and summary['wf_peak_date'] == pd.Timestamp('2024-02-29')
    assert summary['wf_cum_peak'] == 2.5 and summary['wf_cum_peak_date'] == pd.Timestamp('2024-03-01')


def test_no_water_table_gives_no_water_keys_and_peak_wells_counted():
    summary, _ = an_report.season_report(LEAP, MAPPING, PRESSURE, 'withdrawal', '2023-2024')
    assert 'water_peak' not in summary                         # воды не загружено — ключей нет
    assert summary['peak_wells'] == 2                          # 29.02: работали скважины 1 и 3; скважина 2 — ноль


def test_neutral_period_before_season_in_calendar_days():
    neutral = production([('1', '2024-01-01', 0), ('1', '2024-02-10', 0)], 'Нейтральный период Осень 2023')
    neutral['kind'] = 'injection'
    frame = pd.concat([neutral, LEAP], ignore_index=True)
    summary, _ = an_report.season_report(frame, MAPPING, PRESSURE, 'withdrawal', '2023-2024')
    assert summary['neutral_days'] == 41                       # 01.01 — 10.02 включительно
    summary, _ = an_report.season_report(LEAP, MAPPING, PRESSURE, 'withdrawal', '2023-2024')
    assert summary['neutral_days'] is None                     # нейтрального периода в данных нет


# Табл. 1.10: ГСП 9 в закачке — скважины 1 и 3 (написания «ГСП-9» и «гсп_9» — одна группа), скважина 2 — ГСП 1.
INJ_MAPPING = {'1': {'group': 'ГСП-9'}, '2': {'group': 'ГСП 1'}, '3': {'group': 'гсп_9'}}
INJECTION = pd.DataFrame([
    ('1', '2023-05-01', 1e9, '2023'), ('2', '2023-05-01', 1e9, '2023'),
    ('1', '2023-05-02', 1e9, '2023'), ('3', '2023-05-02', 0, '2023'),     # 2023: всего 3e9, ГСП 9 — 2e9
    ('2', '2024-05-01', 3e9, '2024'), ('3', '2024-05-01', 1e9, '2024'),   # 2024: всего 4e9, ГСП 9 — 1e9
], columns=['well', 'date', 'q', 'period'])
INJECTION['date'] = pd.to_datetime(INJECTION.date)
INJECTION['kind'] = 'injection'
PLAN_INJ = pd.DataFrame({'group': ['ГСП_9', 'гсп 9', 'ГСП 1'], 'date': pd.to_datetime(['2023-05-01', '2024-05-01', '2024-05-01']),
                         'plan_volume': [2500.0, 900.0, 700.0], 'kind': 'injection'})


def test_injection_table_by_hand():
    frame = an_report.injection_group_table(INJECTION, PLAN_INJ, INJ_MAPPING, {})
    assert frame.season.tolist() == ['2023', '2024']
    assert frame.recommended.tolist() == pytest.approx([2.5, 0.9])        # млн м³ плана → млрд м³
    assert frame.fact.tolist() == pytest.approx([2.0, 1.0])               # м³ → млрд м³
    assert frame.percent.tolist() == pytest.approx([200 / 3, 25.0])       # доля группы в общем факте сезона


def test_injection_table_without_plan_and_without_group():
    frame = an_report.injection_group_table(INJECTION, None, INJ_MAPPING, {})
    assert frame.recommended.isna().all() and frame.fact.notna().all()
    assert an_report.injection_group_table(INJECTION, PLAN_INJ, {'1': {'group': 'ГСП-1'}}, {}).empty


# Глава 2 (закачка): сезон 2024 — скважина 1 (ГСП-9) работает 01.05 и 02.05 по 150 тыс., скважина 2 (ГСП 1) — 02.05 на 50 тыс.,
# скважина 3 (ГСП 9) — 01.06 на 350 тыс.; 01.05 скважина 2 — ноль (в фонде сезона, но не работала в этот день).
INJ_SEASON = pd.DataFrame([
    ('1', '2024-05-01', 150_000), ('2', '2024-05-01', 0), ('1', '2024-05-02', 150_000), ('2', '2024-05-02', 50_000),
    ('3', '2024-06-01', 350_000),
], columns=['well', 'date', 'q'])
INJ_SEASON['date'] = pd.to_datetime(INJ_SEASON.date)
INJ_SEASON['kind'] = 'injection'
INJ_SEASON['period'] = '2024'
INJ_PRESSURE = pd.DataFrame({'date': pd.to_datetime(['2024-04-30', '2024-05-02', '2024-06-01']), 'pressure': [60.0, 65.0, 80.0]})


def test_injection_curve_cumulative_with_pressure_and_well_counts():
    daily, wells = an_charts.daily_of(INJ_SEASON, 'injection', '2024')
    chart = an_charts.curve_chart('injection', '2024', daily, wells, INJ_PRESSURE)
    rate, pres = chart.series
    assert rate.y == pytest.approx([150.0, 200.0, 350.0])            # тыс. м³/сут по датам
    assert list(rate.x) == pytest.approx([0.15, 0.35, 0.70])         # накопленная закачка, млн м³
    assert '2' in rate.labels[1] and '1' in rate.labels[0]          # скважин в работе: 01.05 — 1, 02.05 — 2
    assert list(pres.x) == pytest.approx([0.35, 0.70])               # замер 30.04 — до сезона, на рисунке не выводится
    assert list(pres.y) == [65.0, 80.0]
    assert pres.axis == 'y2'


def test_curve_series_selection_and_water():
    daily, wells = an_charts.daily_of(INJ_SEASON, 'injection', '2024')
    pres, cnt = an_charts.curve_chart('injection', '2024', daily, wells, INJ_PRESSURE, ('Скважин в работе', 'Среднее Рпл (замеры)')).series
    assert list(cnt.x) == pytest.approx([0.15, 0.35, 0.70]) and list(cnt.y) == [1, 2, 1]     # скважины — по накопленному объёму
    assert (pres.axis, cnt.axis) == ('y', 'y2') and list(pres.y) == [65.0, 80.0]     # без расхода первая величина — на левой шкале
    water = pd.DataFrame({'date': pd.to_datetime(['2024-05-01', '2024-05-02']), 'water_day': [10.0, 20.0],
                          'wf': [1.0, 2.0], 'wf_cum': [1.0, 1.5]})
    only = an_charts.curve_chart('injection', '2024', daily, wells, None, ('Вынос воды',), water)
    assert [s.name for s in only.series] == ['Вынос воды'] and list(only.series[0].x) == pytest.approx([0.15, 0.35])
    assert only.y.unit == 'м³/сут' and only.y2 is None
    assert an_charts.curve_chart('injection', '2024', daily, wells, INJ_PRESSURE, []) is None


def test_canvas_series_selection_and_axes():
    daily, wells = an_charts.daily_of(INJ_SEASON, 'injection', '2024')
    chart = an_charts.canvas_chart('injection', '2024', ['rate', 'pressure', 'wells'], daily, wells, INJ_PRESSURE)
    rate, pres, cnt = chart.series
    assert (rate.axis, pres.axis, cnt.axis) == ('y', 'y2', 'y3')
    assert chart.y2.unit == an_charts.P_UNIT and chart.y3.unit == 'скв.'
    assert list(pres.y) == [65.0, 80.0]                              # замер 30.04 — до сезона, не входит
    assert list(cnt.y) == [1, 2, 1]
    only = an_charts.canvas_chart('injection', '2024', ['wells'], daily, wells, None)
    assert [s.name for s in only.series] == ['Скважин в работе'] and only.y2 is None and only.y3 is None and only.y.unit == 'скв.'
    assert an_charts.canvas_chart('injection', '2024', [], daily, wells, None) is None
    empty, none = an_charts.daily_of(INJ_SEASON.iloc[0:0], 'injection', '2024')
    assert an_charts.canvas_chart('injection', '2024', ['rate'], empty, none, None) is None
    assert an_charts.curve_chart('injection', '2024', empty, none, None) is None


def test_group_series_views():
    data = Data({an_report.PRODUCTION: INJ_SEASON, an_report.OBJECT: INJ_PRESSURE})
    data.mapping = INJ_MAPPING
    module = an_report.AuthorReportModule()
    base = {'kind': 'injection', 'periods': ['2024']}
    ids = lambda **p: {c.id for c in module.run(data, {**base, **p}).charts}
    assert 'an-cum-groups-injection-2024' in ids(view='cum_season')
    assert 'an-cum-months-injection-2024' in ids(view='cum_months')
    assert 'an-group-means-injection-2024' in ids(view='group_mean')
    assert 'an-monthly-groups-injection-2024' in ids(view='group_mean_months')
    assert 'an-canvas-injection-2024' in ids(view='canvas', show=['rate'])
    assert [s.name for s in module.run(data, {**base, 'view': 'curve', 'show_curve': ['Скважин в работе'], 'side': 'none'}).charts[0].series] == ['Скважин в работе']
    right = module.run(data, {**base, 'view': 'canvas', 'side': 'curve', 'show_curve': ['Скважин в работе']}).charts
    assert [c.id for c in right] == ['an-canvas-injection-2024', 'an-curve-injection-2024']
    assert [s.name for s in right[1].series] == ['Скважин в работе']
    assert 'an-fund-injection-2024' in ids()                          # правый график по умолчанию — фонд
    assert 'an-fund-injection-2024' not in ids(side='none')
    side = ids(side='cum_months')
    assert 'an-cum-months-injection-2024' in side and 'an-fund-injection-2024' not in side
    assert [c.id for c in module.run(data, {**base, 'view': 'group_mean', 'side': 'group_mean'}).charts].count('an-group-means-injection-2024') == 1
    groups = module.options('groups', data, base)
    assert groups
    chart = next(c for c in module.run(data, {**base, 'view': 'group_months', 'groups': [groups[-1]]}).charts if c.id.startswith('an-cum-group-months'))
    assert groups[-1] in chart.title
    total = next(c for c in module.run(data, {**base, 'view': 'cum_season'}).charts if c.id.startswith('an-cum-groups'))
    obj = next(s for s in total.series if s.name == 'Объект')
    assert obj.y[-1] == pytest.approx(INJ_SEASON.q.sum() / 1e6)      # накопленное по объекту = весь объём сезона


def test_monthly_wells_and_classes_by_hand():
    frame, months = an_report.monthly_wells(INJ_SEASON, INJ_MAPPING, '2024')
    assert [m.strftime('%m') for m in months] == ['05', '06']
    whole = frame.set_index('group')
    assert whole.loc['Всего', 'fund'] == 3 and whole.loc['Всего', 'm0'] == 2 and whole.loc['Всего', 'm1'] == 1
    assert whole.loc['ГСП 9', 'fund'] == 2 and whole.loc['ГСП 9', 'm0'] == 1 and whole.loc['ГСП 9', 'm1'] == 1
    assert whole.loc['ГСП 1', 'fund'] == 1 and whole.loc['ГСП 1', 'm0'] == 1 and whole.loc['ГСП 1', 'm1'] == 0

    wells = an_wells.season_wells(INJ_SEASON, 'injection', '2024')
    scopes = an_report.well_scopes(INJ_MAPPING, ['1', '2', '3'])
    classes = an_report.injection_class_table(wells, scopes).set_index('group')
    assert classes.loc['Всего', 'c0'] == '1 (2)'            # 2: 50 тыс. — менее 100
    assert classes.loc['Всего', 'c2'] == '1 (1)'            # 1: 150 тыс. — от 150 до 200
    assert classes.loc['Всего', 'c5'] == '1 (3)'            # 3: 350 тыс. — более 300
    assert classes.loc['Всего', 'zero'] == '0'
    assert classes.loc['ГСП 9', 'c2'] == '1 (1)' and classes.loc['ГСП 9', 'c5'] == '1 (3)'


def test_plan_tables_from_comparison():
    cmp = pd.DataFrame({'period': ['2024'] * 4, 'month': pd.to_datetime(['2024-05-01', '2024-06-01'] * 2),
                        'group': ['ГСП 9', 'ГСП 9', 'ГСП 1', 'ГСП 1'], 'plan': [10.0, 20.0, 5.0, 5.0],
                        'fact': [8.0, 25.0, 6.0, 4.0]})
    table = an_report.plan_fact_by_group(cmp, '2024').set_index('group')
    assert table.loc['ГСП 9', 'plan'] == 30 and table.loc['ГСП 9', 'fact'] == 33
    assert table.loc['Всего', 'plan'] == 40 and table.loc['Всего', 'fact'] == 43
    assert table.loc['Всего', 'delta'] == 3                          # факт минус план, итог по всем группам
    card, months = an_report.plan_card(cmp, '2024')
    assert len(months) == 2 and card.set_index('group').loc['ГСП 1', 'm1'] == 5.0


def test_injection_season_run_builds_chapter2_items():
    plan = pd.DataFrame({'group': ['ГСП-9', 'ГСП 1'], 'date': pd.to_datetime(['2024-05-01', '2024-06-01']),
                         'plan_volume': [300.0, 200.0], 'kind': 'injection'})
    data = Data({an_report.PRODUCTION: INJ_SEASON, an_report.OBJECT: INJ_PRESSURE, an_report.PLAN: plan})
    data.mapping = INJ_MAPPING
    result = an_report.AuthorReportModule().run(data, {'kind': 'injection', 'periods': ['2024']})
    charts = {c.id for c in result.charts}
    assert {'an-canvas-injection-2024', 'plan-fact-months-2024', 'an-fund-injection-2024'} <= charts
    assert not any(c.title.lower().startswith(('табл', 'рис')) for c in result.charts)
    assert not any(t.title.lower().startswith(('табл', 'рис')) for t in result.tables)
    tables = [t.id for t in result.tables]
    assert {'an-inj-plan-fact', 'an-inj-wells-0', 'an-inj-classes', 'an-inj-plan-card-0'} <= set(tables)
    stat = next(s for s in result.summary if s.label == 'Рпл за сезон · 2024')
    assert stat.value.startswith('+20,0')                              # 60 (30.04, ближе к 01.05 — ничья, раньше) → 80 на 01.06
    assert not any(n.level == 'warning' and 'не загружен' in n.text for n in result.notes)
    assert any('Не построены' in n.text for n in result.notes)


def test_plan_and_fact_groups_match_across_spellings():
    # План написан «ГСП 9», в закачке скважины 1 и 3 — «ГСП-9» и «гсп_9»: факт ГСП 9 по месяцам — 0,30 (май) и 0,35 (июнь).
    plan = pd.DataFrame({'group': ['ГСП 9', 'ГСП 9'], 'date': pd.to_datetime(['2024-05-01', '2024-06-01']),
                         'plan_volume': [1.0, 1.0], 'kind': 'injection'})
    data = Data({an_report.PRODUCTION: INJ_SEASON, an_report.PLAN: plan})
    data.mapping = INJ_MAPPING
    result = an_report.AuthorReportModule().run(data, {'kind': 'injection', 'periods': ['2024']})
    table = next(t for t in result.tables if t.id == 'an-inj-plan-fact').frame.set_index('group')
    assert table.loc['ГСП 9', 'fact'] == pytest.approx(0.65)
    assert table.loc['ГСП 9', 'plan'] == 2.0


def test_injection_gets_month_and_class_charts_like_withdrawal():
    data = Data({an_report.PRODUCTION: INJ_SEASON, an_report.OBJECT: INJ_PRESSURE})
    data.mapping = INJ_MAPPING
    module = an_report.AuthorReportModule()
    plain = module.run(data, {'kind': 'injection', 'periods': ['2024']})
    assert not any(c.id.startswith(('an-month-working', 'an-class-')) for c in plain.charts)
    result = module.run(data, {'kind': 'injection', 'periods': ['2024'], 'month_chart': 'table', 'class_chart': 'box'})
    ids = [c.id for c in result.charts]
    assert 'an-month-working-injection-2024' in ids and 'an-class-share-injection-2024' in ids and 'an-class-total-injection-2024' in ids
    months = next(c for c in result.charts if c.id.startswith('an-month-working'))
    assert [s.y[0] for s in months.series] == [2.0, 1.0, 2.0] and months.table.aligned       # третий ряд — кривая максимума за сутки          # май: работало 2 из 3 скважин
    total = next(c for c in result.charts if c.id.startswith('an-class-total'))
    assert sum(sum(s.y) for s in total.series) == 3                                          # три скважины сезона разложены по классам
    tables = {t.id for t in result.tables}
    assert 'an-fund-class-counts' in tables and 'an-fund-months' not in tables and 'an-inj-classes' in tables


def test_withdrawal_class_table_follows_count_and_thresholds():
    data = Data({an_report.PRODUCTION: LEAP})
    data.mapping = MAPPING
    module = an_report.AuthorReportModule()
    for text in ('50, 300', '20, 40, 60, 80, 100, 120'):
        edges = an_wells.parse_edges(text)
        result = module.run(data, {'kind': 'withdrawal', 'periods': ['2023-2024'], 'class_mode': 'manual', 'class_edges': text})
        table = next(t for t in result.tables if t.id == 'an-fund-classes')
        assert [c.key for c in table.columns] == ['season', 'group', 'zero', *an_wells.class_keys(edges)[1:]]
        assert len(table.columns) == 3 + len(edges) + 1                    # нулевой класс + классы с расходом на одно больше границ


def test_auto_classes_are_hint_with_visible_note_and_manual_edges_win():
    data = Data({an_report.PRODUCTION: INJ_SEASON, an_report.OBJECT: INJ_PRESSURE})
    data.mapping = INJ_MAPPING
    module = an_report.AuthorReportModule()
    auto = module.run(data, {'kind': 'injection', 'periods': ['2024'], 'class_chart': 'box', 'class_mode': 'auto', 'class_count': 3})
    assert any('Автоматические границы классов' in n.text for n in auto.notes)
    manual = module.run(data, {'kind': 'injection', 'periods': ['2024'], 'class_chart': 'box', 'class_mode': 'manual', 'class_edges': '50, 300'})
    labels = [c.name for c in next(c for c in manual.charts if c.id.startswith('an-class-total')).series]
    assert labels == ['0', 'Менее 50 тыс. м³/сут', 'От 50 до 300 тыс. м³/сут', 'Более 300 тыс. м³/сут']
    bad = module.run(data, {'kind': 'injection', 'periods': ['2024'], 'class_chart': 'box', 'class_mode': 'manual', 'class_edges': '12.5'})
    assert any(n.level == 'warning' and 'стандартные' in n.text for n in bad.notes)


def test_class_seasons_chart_compares_groups_across_seasons():
    # Два сезона: в первом две скважины ГСП 1 и одна ГСП 2 (скв. 3), во втором — по одной скважине в каждой группе.
    first = production([('1', '2024-02-01', 150000), ('2', '2024-02-01', 50000), ('3', '2024-02-01', 80000)], '2023-2024')
    second = production([('1', '2025-02-01', 60000), ('3', '2025-02-01', 0)], '2024-2025')
    prod = pd.concat([first, second], ignore_index=True)
    counts = pd.concat([an_wells.class_counts(an_wells.season_wells(prod, 'withdrawal', s), an_report.well_scopes(MAPPING, ['1', '2', '3']))
                        .assign(season=s) for s in ('2023-2024', '2024-2025')], ignore_index=True)
    chart = an_charts.class_seasons_chart('withdrawal', counts, ['2023-2024', '2024-2025'])
    cats = chart.x.categories
    assert [c.split(' · ')[1] for c in cats] == ['2023-2024', '2024-2025'] * 2           # внутри группы сезоны по порядку
    assert cats[0].split(' · ')[0] == cats[1].split(' · ')[0] and cats[0] != cats[2]       # пара группа · сезон
    assert [sum(s.y[j] for s in chart.series) for j in range(len(cats))] == [2, 1, 1, 1]   # скважин в группе сезона, «Всего» не попадает
    assert an_wells.TOTAL not in ' '.join(cats)
    assert an_charts.class_seasons_chart('withdrawal', counts, ['2023-2024']) is None     # меньше двух сезонов — графика нет
    dot = an_charts.class_seasons_chart('withdrawal', counts, ['2023-2024', '2024-2025'])
    assert dot.callouts == 'dot' and dot.table is not None


def test_class_seasons_option_lists_project_seasons_and_builds_chart_alone():
    prod = pd.concat([production([('1', '2024-02-01', 150000)], '2023-2024'), production([('1', '2025-02-01', 60000)], '2024-2025')],
                     ignore_index=True)
    data = Data({an_report.PRODUCTION: prod})
    data.mapping = MAPPING
    module = an_report.AuthorReportModule()
    assert module.options('class_seasons', data, {'kind': 'withdrawal'}) == ['2023-2024', '2024-2025']
    result = module.run(data, {'kind': 'withdrawal', 'periods': ['2023-2024'], 'class_seasons': ['2024-2025', '2023-2024']})
    ids = [c.id for c in result.charts]
    assert 'an-class-seasons-withdrawal' in ids and not any(c.startswith('an-class-share') for c in ids)     # без «Классы производительности» график всё равно есть
    chart = next(c for c in result.charts if c.id == 'an-class-seasons-withdrawal')
    assert chart.x.categories[0].endswith('2023-2024') and chart.x.categories[1].endswith('2024-2025')
    single = module.run(data, {'kind': 'withdrawal', 'periods': ['2023-2024'], 'class_seasons': ['2023-2024']})
    assert not any(c.id.startswith('an-class-seasons') for c in single.charts)
