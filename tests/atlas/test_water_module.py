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
