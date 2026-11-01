"""Поле «Объект» проекта: по умолчанию — название, правка меняет ревизию, копия и архив его сохраняют, старые проекты открываются."""
import json

from atlas.engine.core.storage import Store
from atlas.projects import Projects


def test_object_default_set_and_clear(tmp_path):
    store = Store(tmp_path)
    pid = store.create('Касимовское 2025')
    m = store.manifest(pid)
    assert m['object'] == ''
    s = Projects.summary(m)
    assert s['object'] == 'Касимовское 2025' and s['object_set'] is False
    store.set_object(pid, '  Касимовское   ПХГ ', m['revision'])
    m = store.manifest(pid)
    assert m['object'] == 'Касимовское ПХГ' and m['revision'] == 1
    assert Projects.summary(m)['object_set'] is True
    store.set_object(pid, '', 1)
    assert Projects.summary(store.manifest(pid))['object'] == 'Касимовское 2025'


def test_object_stale_revision_rejected(tmp_path):
    store = Store(tmp_path)
    pid = store.create('П')
    try:
        store.set_object(pid, 'О', 5)
    except ValueError as e:
        assert 'изменен' in str(e)
    else:
        raise AssertionError


def test_object_survives_backup_restore_and_legacy_manifest(tmp_path):
    store = Store(tmp_path)
    pid = store.create('П', obj='Щелково')
    new = store.restore(store.backup(pid, False))
    assert store.manifest(new)['object'] == 'Щелково'
    # манифест без поля (проект 5.8 или старого Атласа 6) открывается, объект = название
    path = store.path(pid) / 'manifest.json'
    m = json.loads(path.read_text('utf8'))
    del m['object']
    path.write_text(json.dumps(m, ensure_ascii=False), 'utf8')
    assert Projects.summary(store.manifest(pid))['object'] == 'П'
    store.commit(pid, settings=m['settings'])
    assert store.manifest(pid)['name'] == 'П'


def test_object_api(tmp_path):
    from starlette.testclient import TestClient
    from atlas.api import create_app
    api = TestClient(create_app(Projects(tmp_path)))
    made = api.post('/api/projects', json={'name': 'П', 'object': 'Касимовское'}).json()
    assert made['object'] == 'Касимовское' and made['object_set'] is True
    out = api.post('/api/projects/%s/object' % made['id'], json={'object': 'Другое', 'revision': made['revision']}).json()
    assert out['object'] == 'Другое' and out['revision'] == made['revision'] + 1
    assert any(p['object'] == 'Другое' for p in api.get('/api/projects').json())
