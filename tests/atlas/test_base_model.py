"""Базовая модель проекта: сверка параметров скважин из модели с загруженным well_geo и перенос по команде инженера."""
import os
import sys
import types

import numpy as np
import pandas as pd
import pytest

from atlas import base_model, model_source
from atlas.engine.core import config
from atlas.imports import Imports
from atlas.projects import Projects

NAN = np.nan
CALLS = []      # с какими аргументами читалка модели вызывалась


def frame(rows):
    return pd.DataFrame(rows, columns=['well', 'x', 'y', 'altitude', 'perf_top', 'perf_bottom'])


MODEL = frame([['1', 10.0, 20.0, 80.0, -1000.0, -1010.0], ['2', 11.0, 21.0, NAN, NAN, NAN]])
FILE = frame([['1', 10.4, 25.0, 85.0, NAN, NAN], ['3', 1.0, 2.0, NAN, NAN, NAN]])


def test_compare_marks_differences_and_gaps_without_changing_anything():
    c = base_model.compare(MODEL, FILE)
    cnt = c['counts']
    assert cnt['x']['same'] == 1 and cnt['y']['diff'] == 1 and cnt['altitude']['diff'] == 1
    assert cnt['perf']['only_model'] == 1 and cnt['x']['only_model'] == 1          # скважина 2 есть только в модели
    row = [r for r in c['rows'] if r['well'] == '1'][0]
    assert row['y'] == {'model': 20.0, 'file': 25.0, 'state': 'diff'}
    assert FILE.loc[0, 'y'] == 25.0                                                  # исходная таблица не тронута


def test_apply_fill_keeps_file_values_replace_overrides_chosen_fields_only():
    fill = base_model.apply(FILE, MODEL, ['x', 'y', 'perf'], 'fill').set_index('well')
    assert fill.loc['1', ['x', 'y', 'altitude']].tolist() == [10.4, 25.0, 85.0]         # файл главнее
    assert fill.loc['1', ['perf_top', 'perf_bottom']].tolist() == [-1000.0, -1010.0]    # пропуск заполнен моделью
    assert fill.loc['2', 'x'] == 11.0 and fill.loc['3', 'x'] == 1.0
    rep = base_model.apply(FILE, MODEL, ['y'], 'replace').set_index('well')
    assert rep.loc['1', 'y'] == 20.0 and rep.loc['1', 'x'] == 10.4 and np.isnan(rep.loc['1', 'perf_top'])
    assert np.isnan(base_model.apply(None, MODEL, ['x'], 'fill').set_index('well').loc['1', 'altitude'])


@pytest.fixture()
def project(tmp_path, monkeypatch):
    CALLS.clear()
    monkeypatch.setenv('PXG_HOME', str(tmp_path / 'pxg'))
    monkeypatch.setattr(config, 'STORAGE', tmp_path / 'storage')
    projects = Projects(tmp_path / 'storage')
    saved = []
    catalog = types.SimpleNamespace(load_folders=lambda: ['/m'] + saved, save_folders=lambda f: saved.extend(x for x in f if x not in ['/m'] + saved),
                                    scan=lambda folders: [{'id': '/m/A.SMSPEC', 'name': 'Модель A', 'folder': '/m', 'summary': False, 'indicators': False}])
    monkeypatch.setattr(model_source, '_tnav', lambda: (types.SimpleNamespace(), catalog))
    monkeypatch.setattr(base_model, 'read', lambda anchor, folder='': (CALLS.append((anchor, folder)), (MODEL, {}, ['заметка']))[1])
    monkeypatch.setattr(base_model, 'data_files', lambda anchor, folder='': {'used': ['M.data'], 'auto': ['Z.data'], 'source': 'folder' if folder else 'auto'})
    return Imports(projects), projects, projects.store.create('Тест')


def test_choose_compare_apply_roundtrip(project):
    imports, projects, pid = project
    st = imports.base_model_state(pid)
    assert st['selected'] == '' and [m['name'] for m in st['models']] == ['Модель A'] and st['compare'] is None
    imports.geo_load(pid, 'xy.txt', b'1\t10.4\t25\n3\t1\t2\n', 'new')
    st = imports.base_model_choose(pid, {'model': '/m/A.SMSPEC'})
    assert st['selected'] == '/m/A.SMSPEC' and st['notes'] == ['заметка'] and st['compare']['counts']['y']['diff'] == 1
    assert projects.manifest(pid)['settings']['base_model'] == '/m/A.SMSPEC'
    with pytest.raises(Exception, match='Отметьте'):
        imports.base_model_apply(pid, {'fields': []})
    out = imports.base_model_apply(pid, {'fields': ['x', 'perf'], 'mode': 'fill'})
    geo = projects.store.load(pid)[1]['well_geo'].set_index('well')
    assert geo.loc['1', 'x'] == 10.4 and geo.loc['1', 'perf_top'] == -1000.0 and geo.loc['2', 'x'] == 11.0
    assert out['state']['compare']['counts']['perf']['same'] == 1
    assert imports.base_model_choose(pid, {'model': ''})['selected'] == ''


def test_read_with_real_reader(tmp_path):
    scripts = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'all_scripts')
    if not os.path.isdir(os.path.join(scripts, 'tnav_results')):
        pytest.skip('рядом нет all_scripts')
    sys.path.insert(0, scripts)
    try:
        (tmp_path / 'M.data').write_text("WELSPECS\n 'W5' 'G' 1 1 1* GAS /\n/\nWELLTRACK 'W5'\n 100 200 -80 0\n 100 200 900 980 /\n"
                                         "COMPDAT\n 'W5' 1* 1* 2 3 OPEN /\n/\n", encoding='utf-8')
        (tmp_path / 'M.SMSPEC').write_bytes(b'')
        frame_, sources, notes = base_model.read(str(tmp_path / 'M.SMSPEC'))
    finally:
        sys.path.remove(scripts)
    row = frame_.iloc[0]
    assert (row.well, row.x, row.y, row.altitude) == ('5', 100.0, 200.0, 80.0) and np.isnan(row.perf_top)
    assert any('EGRID' in n for n in notes) and 'x' in sources['5']


def test_routes_answer(project):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    from atlas import api_import
    imports, projects, pid = project
    client = TestClient(Starlette(routes=api_import.routes(projects)))
    r = client.get(f'/api/projects/{pid}/import/base-model')
    assert r.status_code == 200 and r.json()['selected'] == ''
    r = client.post(f'/api/projects/{pid}/import/base-model', json={'model': '/m/A.SMSPEC'})
    assert r.json()['selected'] == '/m/A.SMSPEC'
    assert client.post(f'/api/projects/{pid}/import/base-model/apply', json={'fields': []}).status_code == 400


def test_models_without_summary_are_listed_and_data_dir_is_used_and_folder_can_be_added(project, tmp_path):
    imports, projects, pid = project
    assert [m['name'] for m in imports.base_model_state(pid)['models']] == ['Модель A']        # сводка SMSPEC/UNSMRY не обязательна
    st = imports.base_model_choose(pid, {'model': '/m/A.SMSPEC', 'data_dir': '/inputs'})
    assert st['data_dir'] == '/inputs' and st['data_files']['source'] == 'folder' and st['data_files']['auto'] == ['Z.data']
    assert CALLS[-1] == ('/m/A.SMSPEC', '/inputs')                                    # читается из явной папки, а не рядом с результатами
    assert imports.base_model_choose(pid, {'data_dir': ''})['data_dir'] == ''                  # сброс не трогает модель
    assert projects.manifest(pid)['settings']['base_model'] == '/m/A.SMSPEC'
    added = tmp_path / 'models'
    added.mkdir()
    assert str(added) in imports.base_model_add_folder({'folder': str(added)})['folders']
    with pytest.raises(Exception, match='не найдена'):
        imports.base_model_add_folder({'folder': str(tmp_path / 'нет')})
