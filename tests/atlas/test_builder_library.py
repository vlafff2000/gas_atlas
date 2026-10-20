"""Конструктор графиков, этап 5: библиотека макетов проекта, файл JSON, Word одного графика, вставка в отчёт АН."""
import io
import json
import zipfile

import pytest
from starlette.testclient import TestClient

from atlas import builder_library as lib
from atlas.api import create_app
from atlas.contract import Data, ParamError
from atlas.projects import Projects
from tests.atlas._wells_data import make_project
from tests.atlas.test_builder import frames

LAYOUT = {'series': [{'dataset': 'production', 'y': 'q', 'wells': ['31']}], 'title': 'Дебит 31'}


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    return client, make_project(projects), projects


def url(pid, tail=''):
    return f'/api/projects/{pid}/builder/layouts{tail}'


def test_save_open_rename_duplicate_delete(env):
    client, pid, projects = env
    assert client.get(url(pid)).json() == {'items': []}
    r = client.post(url(pid), json={'name': 'Дебит', 'layout': LAYOUT})
    assert r.status_code == 200, r.text
    lid = r.json()['item']['id']
    assert client.post(url(pid), json={'name': 'дебит', 'layout': LAYOUT}).status_code == 400      # имя занято
    assert client.post(url(pid), json={'name': ' ', 'layout': LAYOUT}).status_code == 400
    opened = client.get(url(pid, '/' + lid)).json()
    assert opened['layout'] == LAYOUT and opened['missing'] == []
    assert client.patch(url(pid, '/' + lid), json={'name': 'Дебит 31'}).json()['item']['name'] == 'Дебит 31'
    copy = client.post(url(pid, f'/{lid}/duplicate')).json()
    assert copy['item']['name'] == 'Дебит 31 (копия)' and len(copy['items']) == 2
    assert client.post(url(pid, f'/{lid}/duplicate')).json()['item']['name'] == 'Дебит 31 (копия) 2'
    changed = {**LAYOUT, 'title': 'Другой'}
    client.patch(url(pid, '/' + lid), json={'layout': changed})
    assert client.get(url(pid, '/' + lid)).json()['layout']['title'] == 'Другой'
    assert len(client.delete(url(pid, '/' + lid)).json()['items']) == 2
    assert client.get(url(pid, '/' + lid)).status_code == 404
    assert client.delete(url(pid, '/' + lid)).status_code == 404
    # лежит в проекте и переживает перезапуск
    again = TestClient(create_app(Projects(projects.store.root if hasattr(projects.store, 'root') else projects.store.path(pid).parent)))
    assert len(again.get(url(pid)).json()['items']) == 2


def test_invalid_layout_rejected_in_russian(env):
    client, pid, _ = env
    r = client.post(url(pid), json={'name': 'X', 'layout': {'series': [{'dataset': 'нет такого', 'y': 'q'}]}})
    assert r.status_code == 400 and r.json()['error']
    assert client.post(url(pid), json={'name': 'X', 'layout': 'текст'}).status_code == 400


def test_missing_field_warns_instead_of_failing(env):
    client, pid, _ = env
    layout = {'series': [{'dataset': 'production', 'y': 'q', 'wells': ['31', '999']},
                         {'dataset': 'ggh', 'y': 'gas'},
                         {'dataset': 'operations', 'y': 'нет_поля'}]}
    lid = client.post(url(pid), json={'name': 'Старый', 'layout': layout}).json()['item']['id']
    r = client.get(url(pid, '/' + lid))
    assert r.status_code == 200
    text = ' '.join(r.json()['missing'])
    assert '999' in text and 'нет данных набора' in text and 'нет поля' in text
    run = client.post('/api/modules/builder/run', json={'project': pid, 'params': {'layout': layout}})
    assert run.status_code == 200 and run.json()['charts']          # остальное строится


def test_file_roundtrip_and_bad_json(env):
    client, pid, _ = env
    f = client.post(url(pid, '/file'), json={'name': 'Мой макет', 'layout': LAYOUT})
    assert f.status_code == 200 and 'attachment' in f.headers['content-disposition']
    doc = json.loads(f.content)
    assert doc['version'] == 1 and doc['layout'] == LAYOUT
    r = client.post(url(pid, '/import'), json={'content': f.text, 'file_name': 'm.json'})
    assert r.status_code == 200 and r.json()['item']['name'] == 'Мой макет'
    again = client.post(url(pid, '/import'), json={'content': f.text})
    assert again.json()['item']['name'] == 'Мой макет (импорт)'
    bare = client.post(url(pid, '/import'), json={'content': json.dumps(LAYOUT), 'file_name': 'голый.json'})
    assert bare.json()['item']['name'] == 'голый'
    for bad in ('{не json', '[1, 2]', '"текст"', json.dumps({'format': 'other', 'layout': {}}),
                json.dumps({'format': lib.FILE_FORMAT, 'version': 99, 'layout': LAYOUT}),
                json.dumps({'format': lib.FILE_FORMAT, 'layout': {'series': 'ряды'}}),
                json.dumps({'layout': {'series': [{'dataset': 'x', 'y': 'q'}]}})):
        r = client.post(url(pid, '/import'), json={'content': bad})
        assert r.status_code == 400 and r.json()['error'], bad
    assert client.post(url(pid, '/import'), json={'content': 5}).status_code == 400
    assert len(client.get(url(pid)).json()['items']) == 3          # неудачный импорт ничего не сохранил


def test_old_project_without_layouts_and_broken_store(env):
    _, pid, projects = env
    assert lib.listing(projects.manifest(pid).get('settings', {})) == []
    assert lib.items_of({lib.KEY: {'items': [{'id': 'a'}, 5, {'id': 'b', 'name': 'ok', 'layout': {}}]}})[0]['id'] == 'b'
    assert lib.items_of({lib.KEY: 'мусор'}) == []


def test_word_one_chart_with_caption(env):
    client, pid, _ = env
    r = client.post(f'/api/projects/{pid}/builder/word', json={'layout': LAYOUT, 'title': 'Дебит скважины 31', 'caption': 'Суточный расход'})
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.testzip() is None
    xml = z.read('word/document.xml').decode()
    assert 'Дебит скважины 31' in xml and 'Рисунок' in xml and 'Суточный расход' in xml and 'SEQ' in xml
    media = [n for n in z.namelist() if n.startswith('word/media/')]
    assert len(media) == 1 and z.read(media[0])[:8] == b'\x89PNG\r\n\x1a\n'
    assert client.post(f'/api/projects/{pid}/builder/word', json={'layout': {'series': []}}).status_code == 400


def test_csv_of_chart(env):
    client, pid, _ = env
    r = client.post('/api/modules/builder/export', json={'project': pid, 'params': {'layout': LAYOUT}, 'target': 'chart',
                                                          'id': 'builder', 'format': 'csv'})
    assert r.status_code == 200, r.text
    head = r.content.decode('utf-8-sig').splitlines()
    assert head[0] == 'Ряд;Ось;X;Y' and len(head) > 5


def test_layout_in_an_report(env):
    client, pid, _ = env
    client.post(url(pid), json={'name': 'Дебит', 'layout': LAYOUT})
    client.post(url(pid), json={'name': 'Пустой', 'layout': {'series': [{'dataset': 'ggh', 'y': 'gas'}]}})
    opts = client.post('/api/modules/an_report/options', json={'project': pid, 'param': 'builder_layouts', 'params': {}}).json()
    assert opts == ['Дебит', 'Пустой']
    r = client.post('/api/modules/an_report/run', json={'project': pid, 'params': {'builder_layouts': ['Дебит', 'Пустой', 'Чужой']}})
    assert r.status_code == 200, r.text
    out = r.json()
    ids = [c['id'] for c in out['charts']]
    assert sum(i.startswith('builder-') for i in ids) == 1 and len(set(ids)) == len(ids)
    notes = ' '.join(n['text'] for n in out['notes'])
    assert 'Чужой' in notes and 'Пустой' in notes
    plain = client.post('/api/modules/an_report/run', json={'project': pid, 'params': {}}).json()
    assert len(plain['charts']) == len(ids) - 1                  # без макетов отчёт прежний
