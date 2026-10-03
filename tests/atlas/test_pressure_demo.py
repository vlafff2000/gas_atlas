"""Демонстрационные варианты кроссплота: книги проходят обычный импорт, вариант — только в демонстрационный проект."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from app.core import config, pressure_demo
from atlas.api import create_app
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path)
    projects = Projects(tmp_path)
    return TestClient(create_app(projects)), projects.store


@pytest.mark.parametrize('variant', list(pressure_demo.VARIANTS))
def test_variant_objects_scenarios_and_fonds(variant):
    data = pressure_demo.frame(variant)
    objects = pressure_demo.VARIANTS[variant][2]
    assert list(data.object.unique()) == [o[0] for o in objects]
    for name, wells, observation, scenarios, _ in objects:
        part = data[data.object == name]
        assert list(part.scenario.unique()) == [s[0] for s in scenarios]
        assert set(part.well) == set(wells) | set(observation)
        assert set(part.loc[part.well.isin(observation), 'fond']) == {'Наблюдательные'}
    complete = data[data.fact.notna() & data.model.notna()]
    assert len(complete) > 500 and (complete.fact == 0).any()


def test_books_through_api_import_equal_demo_frame(env):
    client, store = env
    pid = store.create('П')
    books = client.get('/api/import/pressure-demo').json()[1]['books']
    files = []
    for name in books:
        content = client.get(f'/api/import/pressure-demo/objects/{name}')
        assert content.status_code == 200
        files.append({'token': client.post('/api/import/files', params={'name': name}, content=content.content).json()['token']})
    r = client.post(f'/api/projects/{pid}/import/pressure', json={'files': files}).json()
    assert not r['errors'] and r['counts']['objects'] == 3
    assert client.post(f'/api/projects/{pid}/import/pressure/apply', json={'pending': r['ready']['id']}).status_code == 200
    stored = store.load(pid)[1]['pressure_match'].drop(columns=['_point_id'], errors='ignore')
    pd.testing.assert_frame_equal(stored, pressure_demo.frame('objects'), check_dtype=False)


def test_variant_only_into_demo_project(env):
    client, store = env
    work = store.create('Рабочий')
    r = client.post(f'/api/projects/{work}/import/pressure-demo', json={'variant': 'basic'})
    assert r.status_code == 400 and 'демонстрационный' in r.json()['error']
    assert 'pressure_match' not in store.manifest(work)['tables']
    demo = client.post('/api/projects/demo').json()['id']
    assert store.load(demo)[1]['pressure_match'].object.unique().tolist() == ['ПХГ Демонстрационное']
    assert client.post(f'/api/projects/{demo}/import/pressure-demo', json={'variant': 'nope'}).status_code == 400
    r = client.post(f'/api/projects/{demo}/import/pressure-demo', json={'variant': 'objects'})
    assert r.status_code == 200, r.text
    assert store.load(demo)[1]['pressure_match'].object.nunique() == 3
    assert store.history(demo)['Действие'].iloc[0] == 'Демонстрационные данные давлений'
    run = client.post(f'/api/modules/pressure/run', json={'project': demo, 'params': {}})
    assert run.status_code == 200, run.text
    assert run.json()['charts']
