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
    # роль снимается, файл обратно определяется по имени
    r = pf.save_manifest(str(tmp_path), {'Отчёт.xlsx': {'role': None}})
    assert roles(r)['Отчёт.xlsx'] == (None, '', False)


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
