"""Вынос воды и водный фактор: объём газа в пласте, вода по объекту, факторы по сезонам."""
import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.api import create_app
from atlas.domain import DatasetKind
from atlas.modules.water import gas_balance, season_frame
from atlas.projects import Projects
from tests.atlas._wells_data import make_project


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    return client, make_project(projects), projects


def run(client, pid, **params):
    r = client.post('/api/modules/water/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def test_balance_and_factors_by_hand():
    dates = pd.to_datetime(['2025-01-01', '2025-01-02', '2025-01-03'])
    df = pd.DataFrame({'date': list(dates) + [dates[0]], 'kind': ['withdrawal'] * 3 + ['injection'],
                       'q': [1e6, 2e6, 1e6, 5e6], 'period': ['2024-2025'] * 4})
    balance, seasons = gas_balance(df, 100.0)
    # 100 + 5 - 1, затем -2, затем -1 (млн м³)
    assert balance.v.round(6).tolist() == [104.0, 102.0, 101.0]
    water = pd.Series([4.0, np.nan, 3.0], index=dates).dropna()
    s = season_frame(balance, seasons, water, '2024-2025')
    assert s.cum_water.tolist() == [4.0, 4.0, 7.0]
    assert s.daily.round(6).tolist()[0] == 4.0 and np.isnan(s.daily.iloc[1])     # 4 м³ / 1 млн м³
    assert s.cumulative.round(6).tolist() == [4.0, round(4 / 3, 6), round(7 / 4, 6)]


def test_module_charts_and_export(env):
    client, pid, projects = env
    opts = client.post('/api/modules/water/options', json={'project': pid, 'param': 'periods', 'params': {}}).json()
    assert opts
    body = run(client, pid, periods=opts, start=1000)
    assert [c['id'] for c in body['charts']] == ['water-carry', 'water-daily', 'water-cumulative']
    assert all(c['series'] for c in body['charts'])
    assert body['tables'][0]['id'] == 'seasons'
    one = run(client, pid, periods=opts, metric='cumulative', inverse=False)
    assert [c['id'] for c in one['charts']] == ['water-cumulative'] and not one['charts'][0]['x']['inverse']
    r = client.post('/api/modules/water/export', json={'project': pid, 'params': {'periods': opts}, 'target': 'chart', 'chart': 'water-daily', 'format': 'svg'})
    assert r.status_code == 200, r.text


def test_without_seasons_is_a_note(env):
    client, pid, _ = env
    body = run(client, pid, periods=[])
    assert not body['charts'] and body['notes']


HEADER = ['Дата', 'Накопленный расход газа, млн.м3', 'Водный фактор нарастающий', 'Накопленная вода,м3', 'Расход воды,м3',
          'Водный Фактор', 'Объем газа в пласте, млн.м3']
ROWS = [['24.10.15', 28.886, 0.0, 0.0, None, 0.0, 21971.1144], ['25.10.15', 60.1, 0.5, 15.0, 15.0, 0.48, 21940.0],
        ['26.10.15', 90.0, 0.6, 30.0, 15.0, 0.5, 21910.0]]


def test_new_table_import_and_chart(tmp_path):
    from atlas.engine.core.loader import load_file
    f = tmp_path / 'wf.xlsx'
    pd.DataFrame(ROWS, columns=HEADER).to_excel(f, index=False)
    r = load_file(str(f))
    assert list(r.frames) == ['water_factor'] and not r.issues
    frame = r.frames['water_factor']
    assert frame.date.iloc[0] == pd.Timestamp('2015-10-24') and frame.water_day.isna().iloc[0]
    assert frame.gas_in_place.iloc[0] == 21971.1144 and frame.wf_cum.iloc[2] == 0.6

    projects = Projects(tmp_path / 'p')
    client = TestClient(create_app(projects))
    pid = projects.create_demo()
    projects.store.commit(pid, frames={'water_factor': frame}, action='Тест')
    opts = client.post('/api/modules/water/options', json={'project': pid, 'param': 'periods', 'params': {}}).json()
    assert opts == ['2015']
    body = run(client, pid, periods=opts)
    assert [c['id'] for c in body['charts']] == ['water-carry', 'water-daily', 'water-cumulative']
    carry, daily, cumulative = body['charts']
    assert carry['series'][0]['y'] == [0.0, 15.0, 30.0] and cumulative['series'][0]['y'] == [0.0, 0.5, 0.6]
    assert carry['series'][0]['x'][0] == 21971.1144


def test_x_axis_by_season_take(env):
    client, pid, _ = env
    opts = client.post('/api/modules/water/options', json={'project': pid, 'param': 'periods', 'params': {}}).json()
    base = run(client, pid, periods=opts, metric='carry')
    by_take = run(client, pid, periods=opts, metric='carry', xaxis='cumulative')
    assert by_take['charts'][0]['x']['label'].startswith('Накопленный отбор')
    for s in by_take['charts'][0]['series']:
        assert s['x'][0] == 0 and s['x'] == sorted(s['x'])
    assert base['charts'][0]['x']['label'].startswith('Объём газа')


def test_export_includes_water(env):
    from atlas.api_export import WATERFACTOR, options_from, with_water
    from atlas.engine.core import reporting
    client, pid, projects = env
    data = projects.data(pid)
    opts = client.post('/api/modules/water/options', json={'project': pid, 'param': 'periods', 'params': {}}).json()
    options, source, raw = options_from({'modules': [WATERFACTOR], 'waterfactor_periods': opts, 'waterfactor_xaxis': 'cumulative'}, data)
    plan = with_water(reporting.plan(source, data.mapping, data.settings, options, raw), data, options)
    assert plan.jobs and all(j.module == WATERFACTOR for j in plan.jobs)
    assert plan.jobs[0].render().layout.xaxis.title.text.startswith('Накопленный отбор')
