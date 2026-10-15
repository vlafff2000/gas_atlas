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
    assert any('Глава 1.1.1' in n['text'] for n in body['notes'])
    assert any('Давление объекта не загружено' in n['text'] for n in body['notes'])
    assert 'Выберите сезон' in ' '.join(n['text'] for n in body['notes'])
    r = client.post('/api/modules/an_report/run', json={'project': pid, 'params': {'kind': 'withdrawal', 'periods': ['2023-2024']}})
    assert r.status_code == 200, r.text
    assert [t['id'] for t in r.json()['tables']] == ['an-season', 'an-season-means']
