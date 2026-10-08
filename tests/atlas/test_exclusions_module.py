"""«Исключенные точки»: журнал как ``exclusions.journal`` 5.8, восстановление выбранных и всех, отбор."""
import pytest
from starlette.testclient import TestClient

from atlas.engine.core import exclusions as legacy
from atlas.engine.core.storage import Store
from atlas.api import create_app
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path):
    client = TestClient(create_app(Projects(tmp_path)))
    pid = client.post('/api/projects/demo').json()['id']
    return client, pid, Store(tmp_path)


def run(client, pid, module, **params):
    r = client.post(f'/api/modules/{module}/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def table(body, tid):
    return next((t for t in body['tables'] if t['id'] == tid), None)


def exclude(client, pid, wells, reason, count=2):
    ids = table(run(client, pid, 'gdi', wells=wells, last_n=1), 'points')['action']['ids'][:count]
    r = client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'gdi', 'add': ids, 'reason': reason})
    assert r.status_code == 200
    return ids


def test_empty_journal_is_a_note(env):
    client, pid, _ = env
    body = run(client, pid, 'exclusions')
    assert body['tables'] == [] and body['commands'] == []
    assert 'Исключенных точек нет' in body['notes'][0]['text']


def test_journal_matches_58_and_restores_selected(env):
    client, pid, store = env
    first = exclude(client, pid, ['31'], 'Проверка А')
    second = exclude(client, pid, ['45'], 'Проверка Б')
    settings = store.manifest(pid)['settings']
    body = run(client, pid, 'exclusions')
    journal = table(body, 'journal')
    assert sorted(journal['action']['ids']) == sorted(legacy.journal(settings)['id'])   # тот же журнал, что в 5.8
    assert all(journal['action']['checked']) and journal['action']['column'] == 'Исключено'
    labels = [c['label'] for c in journal['columns']]
    assert labels[:3] == ['Модуль', 'Показатель', 'Скважина'] and 'Причина' in labels and 'Исключено (UTC)' in labels
    assert journal['action']['ids'][:2] == second                                       # новые сверху

    # Снятый флажок → тот же запрос, что ручной фильтр; действие «Ручной фильтр точек», как PointControls.change.
    r = client.post(f'/api/projects/{pid}/exclusions',
                    json={'dataset': journal['action']['dataset'], 'remove': first[:1]})
    assert r.json()['removed'] == 1
    assert set(store.manifest(pid)['settings']['excluded_points']) == set(first[1:] + second)
    assert store.history(pid).iloc[0]['Действие'] == 'Ручной фильтр точек'


def test_filters_by_well_reason_and_module(env):
    client, pid, _ = env
    exclude(client, pid, ['31'], 'Проверка А')
    exclude(client, pid, ['45'], 'Проверка Б', count=1)
    assert table(run(client, pid, 'exclusions', wells=['45']), 'journal')['count'] == 1
    assert table(run(client, pid, 'exclusions', reasons=['Проверка А']), 'journal')['count'] == 2
    body = run(client, pid, 'exclusions', modules=['production'])
    assert table(body, 'journal') is None and any('По выбранным условиям' in n['text'] for n in body['notes'])
    options = client.post('/api/modules/exclusions/options',
                          json={'project': pid, 'param': 'wells', 'params': {'modules': ['gdi']}}).json()
    assert options == ['31', '45']
    reasons = client.post('/api/modules/exclusions/options',
                          json={'project': pid, 'param': 'reasons', 'params': {}}).json()
    assert reasons == ['Проверка А', 'Проверка Б']


def test_restore_all_command(env):
    client, pid, store = env
    exclude(client, pid, ['31'], 'А')
    exclude(client, pid, ['45'], 'Б')
    body = run(client, pid, 'exclusions', wells=['45'])
    command = next(c for c in body['commands'] if c['label'] == 'Восстановить все')
    assert len(command['body']['remove']) == 4 and command['confirm']          # весь журнал, не только отбор
    r = client.post(f'/api/projects/{pid}/{command["path"]}', json=command['body'])
    assert r.status_code == 200 and r.json()['removed'] == 4
    assert store.manifest(pid)['settings']['excluded_points'] == {}
    assert store.history(pid).iloc[0]['Действие'] == 'Ручной фильтр точек'


def test_undo_last_takes_whole_batch(env):
    client, pid, store = env
    exclude(client, pid, ['31'], 'А')
    second = exclude(client, pid, ['45'], 'Б')
    assert client.post(f'/api/projects/{pid}/exclusions/undo', json={}).json()['removed'] == 2
    assert not set(second) & set(store.manifest(pid)['settings']['excluded_points'])
