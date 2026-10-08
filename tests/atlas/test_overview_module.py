"""«Обзор»: паритет показателей и состава проекта с app/main.py 5.8; журнал действий."""
import json

import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.engine.core.config import DEFAULT_SETTINGS, MODULES
from atlas.engine.core.demo import well_demo_frames
from atlas.engine.core.performance import Project as FrameCache
from atlas.engine.core.storage import Store
from atlas.api import create_app
from atlas.modules.overview import describe, local_time, summary
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path):
    store = Store(tmp_path)
    pid = store.create('Объект', demo=True)
    store.commit(pid, well_demo_frames(), settings={**DEFAULT_SETTINGS}, action='Загрузка демонстрационных данных')
    return TestClient(create_app(Projects(tmp_path))), pid, store


def run(client, pid, module, **params):
    r = client.post(f'/api/modules/{module}/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def rows(table):
    keys = [c['key'] for c in table['columns']]
    return [dict(zip(keys, values)) for values in zip(*table['rows'])]


def table(body, tid):
    return next((t for t in body['tables'] if t['id'] == tid), None)


def test_metrics_and_composition_match_58(env, tmp_path):
    client, pid, store = env
    m = store.manifest(pid)
    catalog = FrameCache(tmp_path, pid, m['snapshot'], tuple(m['tables'])).catalog()
    # app/main.py: metrics() и «Состав проекта».
    expected_metrics = {'wells': len(catalog['wells']), 'production': m['tables'].get('production', 0),
                        'gdi': m['tables'].get('gdi', 0), 'response': m['tables'].get('response', 0)}
    expected_parts = [{'module': MODULES[mod], 'rows': info['rows'], 'wells': len(info['wells']),
                       'start': info['start'], 'end': info['end']} for mod, info in catalog['modules'].items()]
    body = run(client, pid, 'overview')
    assert rows(table(body, 'metrics')) == [expected_metrics]
    got = rows(table(body, 'composition'))
    assert [{k: r[k] for k in ('module', 'rows', 'wells')} for r in got] == \
        [{k: r[k] for k in ('module', 'rows', 'wells')} for r in expected_parts]
    assert [pd.Timestamp(r['start']) for r in got] == [pd.Timestamp(r['start']) for r in expected_parts]
    assert [pd.Timestamp(r['end']) for r in got] == [pd.Timestamp(r['end']) for r in expected_parts]
    texts = ' '.join(n['text'] for n in body['notes'])
    assert 'ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ' in texts and 'перевернутой осью' in texts and '«Объект»' in texts


def test_history_rows_and_gdi_calcs(env):
    client, pid, store = env
    client.post(f'/api/projects/{pid}/state/gdi', json={'params': {'wells': ['31']}})
    body = run(client, pid, 'overview')
    history = store.history(pid)
    shown = rows(table(body, 'history'))
    assert [r['action'] for r in shown] == history['Действие'].tolist()
    assert [r['date'] for r in shown] == [local_time(d) for d in history['Дата']]
    assert any('Сохраненных расчетов ГДИ: 1' in n['text'] for n in body['notes'])
    spec = next(s for s in client.get('/api/modules').json() if s['id'] == 'overview')
    assert spec['needs'] == [] and spec['save_label'] == ''


def test_history_details_are_short():
    big = {'before_exclusions': {str(i): {} for i in range(1000)}, 'after_exclusions': {},
           'added_ids': [], 'removed_ids': [str(i) for i in range(1000)], 'gdi_before': [], 'gdi_after': [],
           'revision': 7, 'rows': {'gdi': 1}}
    text = summary(json.dumps(big))
    assert json.loads(text) == {'исключено': 0, 'возвращено': 1000, 'всего исключено': 0, 'revision': 7}
    assert len(summary(json.dumps({'x': 'я' * 1000}))) == 300
    assert summary('не json') == 'не json'


def test_empty_project_is_a_note(tmp_path):
    store = Store(tmp_path)
    pid = store.create('Пустой')
    client = TestClient(create_app(Projects(tmp_path)))
    body = run(client, pid, 'overview')
    assert table(body, 'composition') is None
    assert any('Данных пока нет' in n['text'] for n in body['notes'])
    assert all(c['count'] in (0, 1) for c in body['tables'] if c['id'] == 'metrics')


def test_history_details_are_human_readable():
    text = describe('Импорт данных', json.dumps({'revision': 3, 'rows': {'production': 7908, 'gdi': 120}, 'snapshot': 'x' * 32}))
    assert text == 'в проекте: Производительность скважин 7\u00a0908, ГДИ 120'
    assert describe('Переименование', json.dumps({'before': 'А', 'after': 'Б'})) == 'было: А; стало: Б'
    assert describe('Создание', json.dumps({'name': 'Объект'})) == 'название: Объект'
    assert describe('Результат импорта', json.dumps({'removed_duplicates': 2, 'rejected': 0})) == 'удалено повторов: 2'
    out = describe('Ручной фильтр точек', json.dumps({'added_ids': ['a'], 'removed_ids': [], 'after_exclusions': {'a': {}}}))
    assert out.startswith('исключено точек 1, возвращено 0, всего исключено 1')
    assert '{' not in out and describe('x', '{}') == '' and describe('x', 'не json') == 'не json'
    assert local_time('2026-10-03T22:28:00+00:00')[10] == 'T' and local_time('мусор') == 'мусор'
