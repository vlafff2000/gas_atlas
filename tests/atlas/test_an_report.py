"""«Авторский надзор: сезон» — общий расчёт сезона на малом примере, рассчитанном вручную."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.api import create_app
from atlas.modules import an_report
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
    assert any('Глава 1.1.2' in n['text'] for n in body['notes'])
    assert not any('Глава 1.1.1' in n['text'] for n in body['notes'])
    assert any('Давление объекта не загружено' in n['text'] for n in body['notes'])
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
