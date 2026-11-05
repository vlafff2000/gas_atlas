"""Графики реагирования: замеры давления ГИС (термобарика), приведённые к −670 м а.о., отдельным рядом с пояснением; ручное исключение точки."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.api import create_app
from atlas.engine.core.demo import demo_frames
from atlas.projects import Projects

DATE = pd.Timestamp('2024-03-30')


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    pid = projects.store.create('ГИС-давление')
    frames = {'response': demo_frames()['response']}
    frames['well_geo'] = pd.DataFrame({'well': ['31'], 'altitude': [110.0]})      # MD 780 м = −670 м а.о.
    frames['gis_thermobaric'] = pd.DataFrame({'well': '31', 'date': DATE, 'depth_m': [0.0, 740.0, 800.0], 'pressure_kgs': [0.0, 70.0, 76.0],
                                              'depth_kind': ['начало замера', '', ''], 'confidence': 'средняя'})
    projects.store.commit(pid, frames=frames, settings={}, action='Загрузка')
    return TestClient(create_app(projects)), pid


def run(client, pid, **params):
    r = client.post('/api/modules/response/run', json={'project': pid, 'params': {'wells': ['31'], **params}})
    assert r.status_code == 200, r.text
    return r.json()


def gis_series(body):
    return [s for c in body['charts'] for s in c['series'] if s['name'].startswith('Рпл ГИС')]


def test_gis_pressure_is_a_separate_series_with_reason_in_tooltip(env):
    client, pid = env
    body = run(client, pid, view='pressure', split='well')
    [s] = gis_series(body)
    assert s['kind'] == 'points' and s['y'] == [74.0] and 'на -670 м а.о.' in s['name'].replace('−', '-')
    assert '740,0 м MD' in s['labels'][0] and '800,0 м MD' in s['labels'][0]
    assert any(c['series'][0]['name'] != s['name'] for c in body['charts'])          # прежний ряд давления остался


def test_gis_tables_and_manual_exclusion_recalculates(env):
    client, pid = env
    body = run(client, pid, view='pressure', split='well')
    result = next(t for t in body['tables'] if t['id'] == 'gis-pressure')
    assert result['count'] == 1
    points = next(t for t in body['tables'] if t['id'] == 'points-gis')
    assert points['action']['dataset'] == 'gis_thermobaric' and points['count'] == 2           # строка с нулевым давлением в фильтр не идёт
    bad = points['action']['ids'][0]
    assert client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'gis_thermobaric', 'add': [bad]}).json()['added'] == 1
    again = run(client, pid, view='pressure', split='well')
    assert gis_series(again) == []                              # одна точка осталась: значения нет, причина — в таблице
    assert 'один замер' in next(t for t in again['tables'] if t['id'] == 'gis-pressure')['rows'][5][0]


def test_switch_off_and_custom_depth(env):
    client, pid = env
    assert gis_series(run(client, pid, view='pressure', split='well', gis_pressure=False)) == []
    [s] = gis_series(run(client, pid, view='pressure', split='well', gis_depth=-630))
    assert s['y'] == [70.0]


def test_project_without_thermobaric_is_unchanged(tmp_path):
    projects = Projects(tmp_path)
    pid = projects.store.create('без ГИС')
    projects.store.commit(pid, frames={'response': demo_frames()['response']}, settings={}, action='Загрузка')
    body = run(TestClient(create_app(projects)), pid, view='pressure')
    assert gis_series(body) == [] and not any(t['id'] in ('gis-pressure', 'points-gis') for t in body['tables'])
