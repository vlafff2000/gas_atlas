"""Копии данных проекта: хранятся последние 10, любую можно вернуть; импорт откатывается кнопкой «Откатить этот импорт»."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from app.core import config
from app.core.storage import KEEP_SNAPSHOTS, Store
from atlas.api import create_app
from atlas.projects import Projects
from tests.atlas.test_import import EXAMPLES, import6, upload


def frame(i):
    return {'production': pd.DataFrame({'well': ['1'], 'date': [pd.Timestamp('2024-01-01')], 'q': [float(i)]})}


def test_store_keeps_last_snapshots_and_rolls_back(tmp_path):
    store = Store(tmp_path)
    pid = store.create('Объект')
    for i in range(KEEP_SNAPSHOTS + 3):
        store.commit(pid, frame(i), action='Импорт данных')
    versions = store.versions(pid)
    assert KEEP_SNAPSHOTS == 10 and len(versions) == KEEP_SNAPSHOTS
    assert versions[0]['current'] and not any(v['current'] for v in versions[1:])
    assert len(list((store.path(pid) / 'snapshots').iterdir())) == KEEP_SNAPSHOTS
    old = versions[4]                                           # q = 12 - 4 = 8
    saved = store.rollback(pid, old['snapshot'], expected=store.manifest(pid)['revision'])
    assert store.load(pid)[1]['production'].q.tolist() == [8.0]
    assert saved['revision'] == KEEP_SNAPSHOTS + 4              # откат — новая ревизия, история не стёрта
    assert store.history(pid).iloc[0]['Действие'] == 'Откат данных'
    assert store.versions(pid)[0]['current']


def test_rollback_refuses_unknown_and_pruned_copies(tmp_path):
    store = Store(tmp_path)
    pid = store.create('Объект')
    store.commit(pid, frame(1), action='Импорт данных')
    with pytest.raises(ValueError, match='Неверная копия'):
        store.rollback(pid, '../../etc')
    with pytest.raises(ValueError, match='уже удалена'):
        store.rollback(pid, 'a' * 32)
    with pytest.raises(ValueError, match='изменен'):
        store.rollback(pid, store.versions(pid)[0]['snapshot'], expected=999)


def test_env_limit_is_read(monkeypatch):
    import importlib
    from app.core import storage
    monkeypatch.setenv('GAS_ATLAS_SNAPSHOTS', '4')
    assert importlib.reload(storage).KEEP_SNAPSHOTS == 4
    monkeypatch.setenv('GAS_ATLAS_SNAPSHOTS', 'много')
    assert importlib.reload(storage).KEEP_SNAPSHOTS == 10
    monkeypatch.delenv('GAS_ATLAS_SNAPSHOTS')
    importlib.reload(storage)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path)
    projects = Projects(tmp_path)
    return TestClient(create_app(projects)), projects.store


def test_import_can_be_undone_through_api(env):
    client, store = env
    pid = store.create('Объект')
    token = upload(client, '01_long_format.xlsx')
    _, applied = import6(client, pid, [{'token': token}])
    assert applied['undo'] and applied['undo']['snapshot']
    imported = store.manifest(pid)
    assert imported['tables']
    r = client.post(f'/api/projects/{pid}/rollback', json={'snapshot': applied['undo']['snapshot'],
                                                           'revision': applied['project']['revision']})
    assert r.status_code == 200, r.text
    assert not store.manifest(pid)["tables"]
    listed = client.get(f'/api/projects/{pid}/versions').json()
    assert listed['keep'] == KEEP_SNAPSHOTS and listed['versions'][0]['current']
    assert any(v['action'] == 'Импорт данных' for v in listed['versions'])


def test_rollback_api_errors_are_user_text(env):
    client, store = env
    pid = store.create('Объект')
    r = client.post(f'/api/projects/{pid}/rollback', json={'snapshot': 'x'})
    assert r.status_code == 400 and 'Неверная копия' in r.json()['error']
    assert client.get('/api/projects/нет/versions').status_code == 404
