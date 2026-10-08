"""«История фильтра»: записи и сравнение ГДИ как в 5.8, восстановление состояния «Восстановление фильтра»."""
import copy
import json

import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.engine.core.history import comparison, filter_details
from atlas.engine.core.storage import Store
from atlas.api import create_app
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    return client, pid, Store(tmp_path), projects


def run(client, pid, module, **params):
    r = client.post(f'/api/modules/{module}/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def table(body, tid):
    return next((t for t in body['tables'] if t['id'] == tid), None)


def exclude(client, pid, well, count=2):
    ids = table(run(client, pid, 'gdi', wells=[well], last_n=1), 'points')['action']['ids'][:count]
    client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'gdi', 'add': ids, 'reason': 'Проверка'})
    return ids


def records_58(store, pid):
    """Отбор записей, как render_extra('История фильтра') в app/ui/extras.py."""
    out = []
    for _, row in store.history(pid).iterrows():
        details = json.loads(row['Подробности'])
        if 'before_exclusions' in details:
            out.append((row, details))
    return out


def test_empty_history_is_a_note(env):
    client, pid, _, _ = env
    body = run(client, pid, 'filter_history')
    assert body['tables'] == [] and 'История начнет заполняться' in body['notes'][0]['text']


def test_records_and_gdi_comparison_match_58(env):
    client, pid, store, _ = env
    exclude(client, pid, '31')
    exclude(client, pid, '45', 1)
    records = records_58(store, pid)
    body = run(client, pid, 'filter_history', record=2)
    listed = table(body, 'records')
    assert listed['count'] == len(records) == 2
    keys = [c['key'] for c in listed['columns']]
    assert listed['rows'][keys.index('date')] == [r['Дата'] for r, _ in records]
    assert listed['rows'][keys.index('added')] == [1, 2]
    assert listed['rows'][keys.index('after')] == [3, 2]

    expected = comparison(records[1][1])
    got = table(body, 'gdi')
    gkeys = [c['key'] for c in got['columns']]
    assert gkeys == list(expected.columns)
    for k in ('Состояние', 'Скважина', 'Точек'):
        assert got['rows'][gkeys.index(k)] == expected[k].tolist()
    for k in ('a', 'b', 'R²', 'Qmax'):
        assert got['rows'][gkeys.index(k)] == pytest.approx(expected[k].tolist(), nan_ok=True)
    assert [pd.Timestamp(v) for v in got['rows'][gkeys.index('Дата')]] == [pd.Timestamp(v) for v in expected['Дата']]
    assert 'Добавлено исключений: 2, восстановлено: 0' in body['notes'][0]['text']


def test_restore_state_writes_58_action(env):
    client, pid, store, projects = env
    first = exclude(client, pid, '31')
    exclude(client, pid, '45', 1)
    m = store.manifest(pid)
    before_settings = copy.deepcopy(m['settings'])
    body = run(client, pid, 'filter_history', record=1, state='before')       # до последнего изменения
    command = body['commands'][0]
    assert command['path'] == 'exclusions/state' and command['body']['revision'] == m['revision']
    r = client.post(f'/api/projects/{pid}/{command["path"]}', json=command['body'])
    assert r.status_code == 200, r.text
    assert r.json() == {'added': 0, 'removed': 1, 'excluded': 2, 'revision': m['revision'] + 1}

    target = records_58(store, pid)[1][1]['before_exclusions']        # запись 1 теперь вторая
    after = store.manifest(pid)['settings']
    assert after['excluded_points'] == target and set(target) == set(first)
    event = store.history(pid).iloc[0]
    assert event['Действие'] == 'Восстановление фильтра'
    details = json.loads(event['Подробности'])
    # Подробности — тот же filter_details 5.8 с теми же входами.
    raw = projects._raw_frames(pid, m)
    old = before_settings['excluded_points']
    cfg = {**copy.deepcopy(before_settings), 'excluded_points': target}
    expected = filter_details(raw, before_settings, cfg, [v for k, v in target.items() if k not in old],
                              [k for k in old if k not in target])
    expected = json.loads(json.dumps(expected, ensure_ascii=False, default=str))
    assert {k: details[k] for k in expected} == expected
    # Запись восстановления сама попадает в историю фильтра (её видит 5.8).
    assert run(client, pid, 'filter_history')['tables'][0]['rows'][2][0] == 'Восстановление фильтра'


def test_restore_state_errors(env):
    client, pid, store, _ = env
    exclude(client, pid, '31')
    body = run(client, pid, 'filter_history', state='after')
    command = body['commands'][0]
    url = f'/api/projects/{pid}/exclusions/state'
    assert client.post(url, json={**command['body'], 'side': 'later'}).status_code == 400
    assert client.post(url, json={**command['body'], 'at': '1999-01-01'}).status_code == 404
    exclude(client, pid, '45', 1)                                   # проект изменился после расчёта
    assert client.post(url, json=command['body']).status_code == 409
    over = run(client, pid, 'filter_history', record=9)
    assert any('Изменения № 9 нет' in n['text'] for n in over['notes']) and over['commands'] == []
