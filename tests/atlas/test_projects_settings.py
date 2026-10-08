"""«Проекты» и «Настройки»: паритет с 5.8 (тот же Store, те же записи журнала и форматы архивов)."""
import io
import json
import zipfile

import pandas as pd
import pytest
from starlette.testclient import TestClient

import atlas.api_projects as api_projects
from atlas.engine.core.storage import Store
from atlas import navigation
from atlas.engine.core.config import parse_wells
from atlas.api import create_app
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(api_projects, 'LOG_DIR', tmp_path / 'logs')
    client = TestClient(create_app(Projects(tmp_path / 'storage')))
    pid = client.post('/api/projects/demo').json()['id']
    return client, pid, Store(tmp_path / 'storage')


def last_action(store, pid):
    return store.history(pid).iloc[0]


def test_rules_commit_like_58(env):
    client, pid, store = env
    r = client.patch(f'/api/projects/{pid}/settings', json={'values': {
        'season_start': 10, 'season_end': 3, 'r2_threshold': .9, 'manometer_wells': '№31, 45;  #70 132'}})
    assert r.status_code == 200, r.text
    s = store.manifest(pid)['settings']
    assert (s['season_start'], s['season_end'], s['r2_threshold']) == (10, 3, .9)
    assert s['manometer_wells'] == parse_wells('№31, 45;  #70 132') == ['31', '45', '70', '132']
    assert last_action(store, pid)['Действие'] == 'Изменение правил'
    assert r.json()['settings']['season_start'] == 10
    # Список тоже принимается и нормализуется так же.
    client.patch(f'/api/projects/{pid}/settings', json={'values': {'manometer_wells': ['132', '№31']}})
    assert store.manifest(pid)['settings']['manometer_wells'] == ['31', '132']


@pytest.mark.parametrize('values', [{'season_start': 0}, {'season_end': 13}, {'season_start': 2.5}, {'r2_threshold': 2},
                                    {'visible_pages': ['Нет такой страницы']}, {'chart_style': {'grid': 'да'}},
                                    {'unknown': 1}])
def test_invalid_settings_rejected(env, values):
    client, pid, store = env
    before = store.manifest(pid)['revision']
    r = client.patch(f'/api/projects/{pid}/settings', json={'values': values})
    assert r.status_code == 400 and 'Недопустимое значение' in r.json()['error']
    assert store.manifest(pid)['revision'] == before


def test_menu_composition_like_58(env):
    client, pid, store = env
    assert client.get(f'/api/projects/{pid}').json()['menu'] == navigation.visible(store.manifest(pid)['settings'])
    pages = ['ГДИ', 'Динамика', 'Экспорт']           # старое имя страницы переводится, как ALIASES в 5.8
    r = client.patch(f'/api/projects/{pid}/settings', json={'values': {'visible_pages': pages}})
    s = store.manifest(pid)['settings']
    assert s['visible_pages'] == ['ГДИ', 'Производительность скважин', 'Экспорт'] and s['pressure_module_menu_seen'] is True
    assert last_action(store, pid)['Действие'] == 'Состав меню'
    assert r.json()['menu'] == navigation.visible(s) == ['Производительность скважин', 'ГДИ', 'Экспорт', 'Настройки']
    client.patch(f'/api/projects/{pid}/settings', json={'values': {'visible_pages': None}})    # «по умолчанию»
    assert store.manifest(pid)['settings']['visible_pages'] == navigation.DEFAULT
    details = client.get(f'/api/projects/{pid}/details').json()
    assert details['pages'] == navigation.PAGES and details['visible_pages'] == navigation.DEFAULT


def test_chart_style(env):
    client, pid, store = env
    style = {'points': False, 'legend': True, 'grid': False}
    client.patch(f'/api/projects/{pid}/settings', json={'values': {'chart_style': style}})
    assert store.manifest(pid)['settings']['chart_style'] == style
    assert last_action(store, pid)['Действие'] == 'Оформление графиков'


def test_create_rename_copy(env):
    client, pid, store = env
    r = client.post('/api/projects', json={'name': '  Новый объект  '})
    assert r.status_code == 201 and store.manifest(r.json()['id'])['name'] == 'Новый объект'
    assert client.post('/api/projects', json={'name': ' '}).status_code == 400
    revision = store.manifest(pid)['revision']
    r = client.post(f'/api/projects/{pid}/rename', json={'name': 'Объект А', 'revision': revision})
    assert r.status_code == 200 and r.json()['name'] == 'Объект А'
    row = last_action(store, pid)
    assert row['Действие'] == 'Переименование' and json.loads(row['Подробности'])['after'] == 'Объект А'
    assert client.post(f'/api/projects/{pid}/rename', json={'name': 'Б', 'revision': revision}).status_code == 409
    copy = client.post(f'/api/projects/{pid}/copy').json()
    m, data = store.load(copy['id'])
    assert m['name'] == 'Объект А (копия)'
    _, original = store.load(pid)
    for name in original:
        pd.testing.assert_frame_equal(data[name], original[name])


def members(content):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_backup_and_restore_like_58(env, tmp_path):
    client, pid, store = env
    (store.path(pid) / 'originals' / 'abc_source.xlsx').write_bytes(b'original')
    r = client.get(f'/api/projects/{pid}/backup')
    assert r.status_code == 200 and "gasatlas.zip" in r.headers['content-disposition']
    ours, theirs = members(r.content), members(store.backup(pid, True))
    assert set(ours) == set(theirs) and 'originals/abc_source.xlsx' in ours
    assert all(ours[n] == theirs[n] for n in ours if n != 'history.csv')
    lean = members(client.get(f'/api/projects/{pid}/backup', params={'originals': '0'}).content)
    assert not any(n.startswith('originals/') for n in lean)

    preview = client.post('/api/projects/restore/preview', params={'name': 'copy.zip'}, content=r.content).json()
    assert preview['kind'] == 'backup' and preview['info']['name'] == 'Демонстрационный объект'
    restored = client.post('/api/projects/restore', params={'name': 'copy.zip'}, content=r.content)
    assert restored.status_code == 201
    new = restored.json()['id']
    assert store.manifest(new)['name'] == 'Демонстрационный объект (копия)'
    assert (store.path(new) / 'originals' / 'abc_source.xlsx').read_bytes() == b'original'

    bad = client.post('/api/projects/restore', params={'name': 'x.zip'}, content=b'not a zip')
    assert bad.status_code == 400
    assert client.post('/api/projects/restore', params={'name': 'x.txt'}, content=b'1').status_code == 400


def test_restore_legacy_gas_json(env):
    client, _, store = env
    legacy = {'version': 1, 'name': 'Старый', 'settings': {'start': 10, 'end': 3},
              'records': [{'well': '1', 'date': '2020-01-01', 'flow': 5, 'kind': 'withdrawal'},
                          {'well': '2', 'date': '2020-01-02', 'flow': 7, 'kind': 'injection'}]}
    content = json.dumps(legacy).encode()
    preview = client.post('/api/projects/restore/preview', params={'name': 'old.gas.json'}, content=content).json()
    assert preview['kind'] == 'legacy' and preview['count'] == 2
    pid = client.post('/api/projects/restore', params={'name': 'old.gas.json'}, content=content).json()['id']
    expected = store.import_legacy(content)
    a, b = store.load(pid), store.load(expected)
    assert a[0]['settings'] == b[0]['settings'] and a[0]['name'] == 'Старый'
    pd.testing.assert_frame_equal(a[1]['production'], b[1]['production'])
    bad = client.post('/api/projects/restore', params={'name': 'x.gas.json'}, content=b'{"version": 2}')
    assert bad.status_code == 400 and 'версии 1' in bad.json()['error']


def test_saved_exports_and_log(env, tmp_path):
    client, pid, store = env
    path = store.save_export(pid, 'Паспорт.pdf', b'%PDF-1', {'well': '31'})
    listed = client.get(f'/api/projects/{pid}/exports').json()
    assert [x['name'] for x in listed] == [path.name]          # метаданные .json не показываются, как в 5.8
    r = client.get(f'/api/projects/{pid}/exports/{path.name}')
    assert r.status_code == 200 and r.content == b'%PDF-1' and r.headers['content-type'] == 'application/pdf'
    assert client.get(f'/api/projects/{pid}/exports/{path.name}.json').status_code == 404
    assert client.get(f'/api/projects/{pid}/exports/..%2Fmanifest.json').status_code == 404

    assert client.get('/api/log').status_code == 404
    (tmp_path / 'logs').mkdir(exist_ok=True)
    (tmp_path / 'logs' / 'gas_atlas.log').write_text('ошибка 5.8\n', encoding='utf8')
    r = client.get('/api/log')
    assert r.status_code == 200 and 'ошибка 5.8' in r.text
    assert client.get(f'/api/projects/{pid}/details').json()['log'] is True


def test_season_schedule_setting_roundtrip_and_errors(env):
    client, pid, store = env
    url = f'/api/projects/{pid}/settings'
    r = client.patch(url, json={'values': {'season_schedule': '28.06.2021 inj\n25.10.2021 none\n01.11.2021 prod\n10.01.2022 12.01.2022 peak',
                                           'auto_seasons': True}})
    assert r.status_code == 200, r.text
    assert store.manifest(pid)['settings']['season_schedule'] == [['2021-06-28', 'injection'], ['2021-10-25', 'none'],
                                                                  ['2021-11-01', 'withdrawal']]
    assert store.manifest(pid)['settings']['peak_windows'] == [['2022-01-10', '2022-01-12']]
    bad = client.patch(url, json={'values': {'season_schedule': '28.06.2021 xx'}})
    assert bad.status_code == 400 and 'Строка 1' in bad.text
    assert client.patch(url, json={'values': {'season_schedule': ''}}).status_code == 200
    assert store.manifest(pid)['settings']['season_schedule'] is None
    assert store.manifest(pid)['settings']['peak_windows'] is None
