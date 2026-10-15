"""Папка проекта: роли файлов по именам и манифесту, известные результаты Базы ПХГ, отчёт проверки, ошибки."""
import json

import pytest
from starlette.testclient import TestClient

from atlas import project_folder as pf
from atlas.api import create_app
from atlas.contract import ParamError
from atlas.engine.core import config
from atlas.projects import Projects


def touch(folder, *names):
    for n in names:
        (folder / n).write_bytes(b'x')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path / 'storage')
    return TestClient(create_app(Projects(tmp_path / 'storage')))


def roles(scan):
    return {f['name']: (f['role'], f['role_source'], f['normalized']) for f in scan['files']}


def test_known_results_get_role_and_normalized_flag(tmp_path):
    touch(tmp_path, 'БД_расходы_нормированная_ПЗРГ.xlsx', 'БД_расходы.xlsx', 'БД_давлений_по_замерам.xlsx',
          'БД_давления_2006-2025.xlsx', 'БД_ГДИ_объединенная.xlsx', 'БД_замеров_воды.xlsx', 'БД_межколонки.xlsx')
    r = pf.scan(str(tmp_path))
    assert roles(r) == {
        'БД_давления_2006-2025.xlsx': ('pressure', 'name', False),
        'БД_давлений_по_замерам.xlsx': ('pressure', 'name', False),
        'БД_ГДИ_объединенная.xlsx': ('gdi', 'name', False),
        'БД_замеров_воды.xlsx': ('water', 'name', False),
        'БД_межколонки.xlsx': ('other', 'name', False),
        'БД_расходы.xlsx': ('production', 'name', False),
        'БД_расходы_нормированная_ПЗРГ.xlsx': ('production', 'name', True),
    }
    assert all(f['known'] for f in r['files'])


def test_name_hints_and_service_files_are_skipped(tmp_path):
    touch(tmp_path, 'Расходы_сырые.xlsx', 'readme.pdf', '~$БД_расходы.xlsx', 'БД_расходы.qc.json', 'что-то.xlsx')
    r = pf.scan(str(tmp_path))
    assert [f['name'] for f in r['files']] == ['Расходы_сырые.xlsx', 'что-то.xlsx']
    assert roles(r)['Расходы_сырые.xlsx'] == ('production', 'name', False)
    assert roles(r)['что-то.xlsx'] == (None, '', False)


def test_manifest_overrides_name_and_is_written_only_for_files_in_folder(tmp_path):
    touch(tmp_path, 'БД_расходы.xlsx', 'Отчёт.xlsx')
    r = pf.save_manifest(str(tmp_path), {'Отчёт.xlsx': {'role': 'gdi'}, 'БД_расходы.xlsx': {'normalized': True}})
    assert roles(r) == {'БД_расходы.xlsx': ('production', 'name', True), 'Отчёт.xlsx': ('gdi', 'manifest', False)}
    assert r['manifest'] is True
    saved = json.loads((tmp_path / pf.MANIFEST).read_text(encoding='utf-8'))
    assert saved['files']['Отчёт.xlsx'] == {'role': 'gdi'}
    # явно «не назначено» сохраняется и не подменяется именем файла
    r = pf.save_manifest(str(tmp_path), {'БД_расходы.xlsx': {'role': None}})
    assert roles(r)['БД_расходы.xlsx'][:2] == (None, '')


def test_manifest_rejects_bad_input(tmp_path):
    touch(tmp_path, 'a.xlsx')
    with pytest.raises(ParamError, match='неизвестная роль'):
        pf.save_manifest(str(tmp_path), {'a.xlsx': {'role': 'нефть'}})
    with pytest.raises(ParamError, match='нет в папке'):
        pf.save_manifest(str(tmp_path), {'../etc/passwd': {'role': 'water'}})
    with pytest.raises(ParamError, match='да или нет'):
        pf.save_manifest(str(tmp_path), {'a.xlsx': {'normalized': 'да'}})
    assert not (tmp_path / pf.MANIFEST).exists()


def test_broken_manifest_is_reported_and_not_overwritten(tmp_path):
    touch(tmp_path, 'a.xlsx')
    (tmp_path / pf.MANIFEST).write_text('{не json', encoding='utf-8')
    r = pf.scan(str(tmp_path))
    assert 'не читается' in r['warning']
    with pytest.raises(ParamError, match='не читается'):
        pf.save_manifest(str(tmp_path), {'a.xlsx': {'role': 'water'}})
    assert (tmp_path / pf.MANIFEST).read_text(encoding='utf-8') == '{не json'


def test_qc_report_next_to_result_is_summarised(tmp_path):
    touch(tmp_path, 'БД_расходы.xlsx')
    report = {'title': 'Расходы', 'summary': 'Ошибок: 1', 'counts': {'ошибка': 1, 'предупреждение': 0}, 'issues': []}
    (tmp_path / 'БД_расходы.qc.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    qc = pf.scan(str(tmp_path))['files'][0]['qc']
    assert qc['summary'] == 'Ошибок: 1' and qc['file'] == 'БД_расходы.qc.json' and qc['counts']['ошибка'] == 1


def test_missing_folder_is_a_clear_error(tmp_path):
    with pytest.raises(ParamError, match='Папка не найдена'):
        pf.scan(str(tmp_path / 'нет'))
    with pytest.raises(ParamError, match='Папка не найдена'):
        pf.scan('')


def test_api_scan_and_manifest(client, tmp_path):
    touch(tmp_path, 'БД_расходы.xlsx')
    r = client.post('/api/folder/scan', json={'folder': f'"{tmp_path}"'})
    assert r.status_code == 200, r.text
    assert r.json()['files'][0]['role'] == 'production'
    r = client.post('/api/folder/manifest', json={'folder': str(tmp_path), 'files': {'БД_расходы.xlsx': {'role': 'water'}}})
    assert r.status_code == 200 and r.json()['files'][0]['role_source'] == 'manifest'
    assert client.post('/api/folder/scan', json={'folder': str(tmp_path / 'нет')}).status_code == 400
    assert client.post('/api/folder/scan', data='не json').status_code == 400


def test_bad_inputs_do_not_crash(tmp_path):
    touch(tmp_path, 'Подвод.xlsx', 'a.xlsx')
    (tmp_path / 'a.qc.json').write_text('[1, 2]', encoding='utf-8')
    (tmp_path / pf.MANIFEST).write_text(json.dumps({'files': {'a.xlsx': {'role': ['gdi']}}}), encoding='utf-8')
    r = pf.scan(str(tmp_path))
    assert roles(r)['a.xlsx'][:2] == (None, '')
    assert r['files'][0]['qc']['error']
    assert roles(r)['Подвод.xlsx'] == (None, '', False)
    with pytest.raises(ParamError, match='неизвестная роль'):
        pf.save_manifest(str(tmp_path), {'a.xlsx': {'role': {'x': 1}}})
    with pytest.raises(ParamError, match='Файла'):
        pf.save_manifest(str(tmp_path), {pf.MANIFEST: {'role': 'water'}})


def test_empty_folder_gives_a_note(tmp_path):
    r = pf.scan(str(tmp_path))
    assert r['files'] == [] and 'нет таблиц' in r['warning']


def make_csv(path, rows):
    path.write_bytes(('Скважина;Дата;Расход\r\n' + ''.join(f'{w};{d};{q}\r\n' for w, d, q in rows)).encode('cp1251'))


def test_load_from_folder_marks_loaded_then_changed(client, tmp_path):
    folder = tmp_path / 'папка'
    folder.mkdir()
    make_csv(folder / 'добыча.csv', [('73', '01.11.2025', '2000'), ('73', '02.11.2025', '2100')])
    pid = client.post('/api/projects', json={'name': 'П'}).json()['id']
    before = client.post('/api/folder/scan', json={'folder': str(folder), 'project': pid}).json()
    assert before['files'][0]['load'] == 'not_loaded'
    r = client.post(f'/api/projects/{pid}/folder/load', json={'folder': str(folder), 'files': ['добыча.csv']})
    assert r.status_code == 200, r.text
    assert r.json()['results'][0]['status'] == 'loaded'
    assert r.json()['folder']['files'][0]['load'] == 'loaded'
    # файл изменился: отпечаток не совпадает
    make_csv(folder / 'добыча.csv', [('73', '01.11.2025', '2000')] * 3)
    after = client.post('/api/folder/scan', json={'folder': str(folder), 'project': pid}).json()
    assert after['files'][0]['load'] == 'changed'


def test_rejected_rows_go_to_attention_not_loaded(client, tmp_path):
    folder = tmp_path / 'папка'
    folder.mkdir()
    make_csv(folder / 'плохой.csv', [('73', 'не дата', '2000')])
    pid = client.post('/api/projects', json={'name': 'П'}).json()['id']
    r = client.post(f'/api/projects/{pid}/folder/load', json={'folder': str(folder), 'files': ['плохой.csv']}).json()
    assert r['results'][0]['status'] in ('attention', 'error')
    assert r['folder']['files'][0]['load'] == 'not_loaded'


def test_load_rejects_names_outside_folder_and_unknown_project(client, tmp_path):
    folder = tmp_path / 'папка'
    folder.mkdir()
    (tmp_path / 'secret.csv').write_text('x', encoding='utf-8')
    pid = client.post('/api/projects', json={'name': 'П'}).json()['id']
    r = client.post(f'/api/projects/{pid}/folder/load', json={'folder': str(folder), 'files': ['../secret.csv']}).json()
    assert r['results'][0]['status'] == 'error'
    assert client.post(f'/api/projects/{"0" * 32}/folder/load', json={'folder': str(folder), 'files': ['x.csv']}).status_code == 404


def test_one_bad_file_does_not_stop_the_others(client, tmp_path):
    folder = tmp_path / 'папка'
    folder.mkdir()
    make_csv(folder / 'добыча.csv', [('73', '01.11.2025', '2000')])
    pid = client.post('/api/projects', json={'name': 'П'}).json()['id']
    r = client.post(f'/api/projects/{pid}/folder/load',
                    json={'folder': str(folder), 'files': ['../нет.csv', 'добыча.csv']}).json()
    assert [x['status'] for x in r['results']] == ['error', 'loaded']
    assert r['folder']['files'][0]['load'] == 'loaded'


def test_folder_load_can_be_undone(client, tmp_path):
    folder = tmp_path / 'папка'
    folder.mkdir()
    make_csv(folder / 'добыча.csv', [('73', '01.11.2025', '2000'), ('73', '02.11.2025', '2100')])
    pid = client.post('/api/projects', json={'name': 'П'}).json()['id']
    r = client.post(f'/api/projects/{pid}/folder/load', json={'folder': str(folder), 'files': ['добыча.csv']})
    assert r.status_code == 200, r.text
    snapshot = r.json()['undo']
    assert snapshot, 'после загрузки должен быть снимок для отката'
    current = client.get(f'/api/projects/{pid}').json()['revision']
    back = client.post(f'/api/projects/{pid}/folder/undo', json={'snapshot': snapshot, 'revision': current})
    assert back.status_code == 200, back.text
    after = client.post('/api/folder/scan', json={'folder': str(folder), 'project': pid}).json()
    assert after['files'][0]['load'] == 'not_loaded'


def test_base_outputs_are_known_results():
    """Файлы «Базы ПХГ», которые читает Атлас, узнаются по имени; неясные — без роли, роль назначает пользователь."""
    from atlas import project_folder as pf

    assert pf._known('Учёт_газа_отбор_вынос_воды.xlsx')['role'] == 'water'
    assert pf._known('БД_ГДИ_объединенная.xlsx')['role'] == 'gdi'
    assert pf._known('БД_ЭЛПРО.xlsx')['role'] == 'elpro'
    assert pf._known('daily_well_data_2019_01_2024_04.xlsx') is not None
    assert pf._known('Пересчёт_давлений.xlsx') is None
