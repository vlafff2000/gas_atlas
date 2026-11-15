"""Удаление наборов данных проекта: показ, что будет удалено, резервная копия, отмена."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.api import create_app
from atlas.engine.core import config
from atlas.projects import Projects


def frames():
    return {
        'production': pd.DataFrame({'well': ['1'], 'date': [pd.Timestamp('2024-01-01')], 'q': [1.0]}),
        'gis_packs': pd.DataFrame({'well': ['1', '2'], 'pack': ['A', 'A']}),
        'gis_annotations': pd.DataFrame({'well': ['1'], 'text': ['глина']}),
    }


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path)
    projects = Projects(tmp_path)
    pid = projects.store.create('Объект')
    projects.store.commit(pid, frames(), action='Импорт данных')
    return TestClient(create_app(projects)), projects.store, pid


def test_available_lists_gis_bundle_with_rows(env):
    client, _, pid = env
    items = {i['key']: i for i in client.get(f'/api/projects/{pid}/datasets').json()['items']}
    assert items['gis']['rows'] == 3 and items['production']['rows'] == 1 and 'gdi' not in items


def test_without_confirm_nothing_is_deleted(env):
    client, store, pid = env
    r = client.post(f'/api/projects/{pid}/datasets/delete', json={'keys': ['gis']})
    assert r.status_code == 200 and r.json()['total'] == 3 and r.json()['deleted'] is False
    assert set(store.manifest(pid)['tables']) == {'production', 'gis_packs', 'gis_annotations'}


def test_delete_backs_up_and_can_be_undone(env):
    client, store, pid = env
    rev = store.manifest(pid)['revision']
    r = client.post(f'/api/projects/{pid}/datasets/delete', json={'keys': ['gis'], 'confirm': True, 'revision': rev})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out['total'] == 3 and out['undo'] and out['backup']
    assert set(store.manifest(pid)['tables']) == {'production'}                      # остальное не тронуто
    assert any(p.name == out['backup'] for p in store.exports(pid))                   # резервная копия сохранена
    back = client.post(f'/api/projects/{pid}/rollback', json={'snapshot': out['undo'], 'revision': out['project']['revision']})
    assert back.status_code == 200
    assert set(store.manifest(pid)['tables']) == {'production', 'gis_packs', 'gis_annotations'}


def test_delete_refuses_empty_unknown_and_stale(env):
    client, store, pid = env
    post = lambda body: client.post(f'/api/projects/{pid}/datasets/delete', json=body)
    assert post({'keys': []}).status_code == 400
    assert post({'keys': ['gdi'], 'confirm': True}).status_code == 400               # в проекте нет
    assert post({'keys': ['../x'], 'confirm': True}).status_code == 400
    assert post({'keys': ['gis'], 'confirm': True, 'revision': 999}).status_code == 409
    assert len(store.manifest(pid)['tables']) == 3
