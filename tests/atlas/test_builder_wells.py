"""Конструктор графиков: режим «Текущая скважина», {скважина} в подписях, серия по скважинам (zip, PDF, Word), старые макеты."""
import io
import re
import zipfile

import pytest
from starlette.testclient import TestClient

from atlas import builder_library as lib
from atlas.api import create_app
from atlas.contract import Data, ParamError
from atlas.modules import builder
from atlas.projects import Projects
from tests.atlas._wells_data import make_project
from tests.atlas.test_builder import frames, text

CURRENT = {'wells_mode': 'current'}
LAYOUT = {'series': [{'dataset': 'production', 'y': 'q', 'name': 'Расход скв. {скважина}', **CURRENT},
                     {'dataset': 'operations', 'y': 'p_wellhead', 'axis': 'y2', **CURRENT}],
          'title': 'Скважина {скважина}: расход и давление', 'current_well': '1'}


@pytest.fixture()
def data():
    return Data(frames())


def names(result):
    return [s.name for s in result.charts[0].series]


def test_current_well_switches_and_substitutes(data):
    one, two = builder.build(data, LAYOUT), builder.build(data, LAYOUT, well='2')
    assert one.charts[0].title == 'Скважина 1: расход и давление' and two.charts[0].title == 'Скважина 2: расход и давление'
    assert names(one)[0].startswith('Расход скв. 1') and names(two)[0].startswith('Расход скв. 2')
    assert len(one.charts[0].series[0].x) == 4 and len(two.charts[0].series) == 2
    assert builder.build(data, {**LAYOUT, 'current_well': '2'}).charts[0].title.startswith('Скважина 2')     # поле макета, как и параметр


def test_no_current_well_warns_and_does_not_show_all(data):
    r = builder.build(data, {**LAYOUT, 'current_well': ''})
    assert not r.charts and 'не выбрана скважина' in text(r)
    mixed = builder.build(data, {'series': [CURRENT | {'dataset': 'production', 'y': 'q'},
                                            {'dataset': 'production', 'y': 'q', 'wells': ['2']}]})
    assert len(mixed.charts[0].series) == 1 and 'не выбрана скважина' in text(mixed)       # фиксированный ряд остался, а не «все скважины»


def test_formula_over_current_rows(data):
    rows = [{'dataset': 'production', 'y': 'q', **CURRENT, 'hidden': True}, {'dataset': 'production', 'y': 'q', **CURRENT, 'hidden': True},
            {'source': 'formula', 'formula': 'A+B'}]
    r = builder.build(data, {'series': rows, 'current_well': '2'})
    assert r.charts and set(r.charts[0].series[0].facets.values()) >= {'№ 2'}


def test_old_layouts_unchanged(data):
    old = {'series': [{'dataset': 'production', 'y': 'q', 'wells': ['1']}], 'title': 'Дебит {скважина}'}
    assert not builder.uses_current(old)
    r = builder.build(data, old)
    assert len(r.charts[0].series) == 1 and 'не выбрана' not in text(r)
    assert builder.parse_layout(old)[0][0].well_mode == 'fixed'
    both = builder.build(data, {'series': [{'dataset': 'production', 'y': 'q'}]})
    assert len(both.charts[0].series) == 2                                      # без «текущей» все скважины, как раньше
    assert 'wells' in builder.catalog(data) and builder.catalog(data)['wells'] == ['1', '2']


def test_wells_with_data_and_groups(data):
    info = lib.wells_info(data, LAYOUT)
    assert info['enabled'] and info['wells'] == ['1', '2'] and info['with_data'] == ['1', '2']
    only_ops = {'series': [{'dataset': 'operations', 'y': 'p_wellhead', **CURRENT}]}
    assert lib.wells_info(data, only_ops)['with_data'] == ['1', '2']
    assert not lib.wells_info(data, {'series': [{'dataset': 'production', 'y': 'q'}]})['enabled']


def test_series_zip_pdf_docx(data):
    wells = ['1', '2', '999']
    content, name, _, notes = lib.series_file(data, LAYOUT, wells, 'png')
    z = zipfile.ZipFile(io.BytesIO(content))
    assert name.endswith('.zip') and len(z.namelist()) == 2 and all(z.read(n)[:4] == b'\x89PNG' for n in z.namelist())
    assert '999' in notes[0] and 'пропущены' in notes[0]
    content, name, _, _ = lib.series_file(data, LAYOUT, wells, 'pdf')
    assert content[:5] == b'%PDF-' and len(re.findall(rb'/Type\s*/Page\b', content)) == 2
    content, name, _, _ = lib.series_file(data, LAYOUT, wells, 'docx', title='Серия')
    z = zipfile.ZipFile(io.BytesIO(content))
    xml = z.read('word/document.xml').decode()
    assert len([n for n in z.namelist() if n.startswith('word/media/')]) == 2
    assert 'Рисунок' in xml and 'Скважина 1' in xml and 'Скважина 2' in xml and xml.count('w:type="page"') + xml.count('w:pageBreakBefore') >= 1


def test_series_errors(data):
    with pytest.raises(ParamError, match='Текущая скважина'):
        lib.series_file(data, {'series': [{'dataset': 'production', 'y': 'q'}]}, ['1'], 'png')
    with pytest.raises(ParamError, match='не больше 200'):
        lib.series_file(data, LAYOUT, [str(i) for i in range(201)], 'png')
    with pytest.raises(ParamError, match='хотя бы одну'):
        lib.series_file(data, LAYOUT, [], 'png')
    with pytest.raises(ParamError, match='нет данных'):
        lib.series_file(data, LAYOUT, ['998', '999'], 'pdf')
    with pytest.raises(ParamError, match='Формат'):
        lib.series_file(data, LAYOUT, ['1'], 'gif')


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    return TestClient(create_app(projects)), make_project(projects)


def test_library_keeps_current_well_and_api_and_an_report(env):
    client, pid = env
    layout = {**LAYOUT, 'current_well': '31'}
    base = f'/api/projects/{pid}/builder'
    lid = client.post(base + '/layouts', json={'name': 'Скв', 'layout': layout}).json()['item']['id']
    assert client.get(f'{base}/layouts/{lid}').json()['layout'] == layout
    assert client.post(base + '/layouts', json={'name': 'Без', 'layout': {**LAYOUT, 'current_well': ''}}).status_code == 200
    info = client.post(base + '/series/wells', json={'layout': layout}).json()
    assert '31' in info['with_data'] and info['limit'] == 200 and info['groups']
    r = client.post(base + '/series', json={'layout': layout, 'wells': ['31', '45', '9999'], 'format': 'png'})
    assert r.status_code == 200 and len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == 2 and '9999' in requote(r.headers['x-atlas-notes'])
    assert client.post(base + '/series', json={'layout': layout, 'wells': [], 'format': 'png'}).status_code == 400
    out = client.post('/api/modules/an_report/run', json={'project': pid, 'params': {'builder_layouts': ['Скв', 'Без']}}).json()
    assert sum(c['id'].startswith('builder-') for c in out['charts']) == 1
    assert any('«Без»' in n['text'] and 'не выбрана скважина' in n['text'] for n in out['notes'])


def requote(value):
    from urllib.parse import unquote
    return unquote(value)
