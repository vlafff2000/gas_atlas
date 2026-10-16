"""Общий выбор проекта в Атласе: читает файл «Базы ПХГ» и показывает подпапки «готовые» и «выгрузки»."""
import json

import pytest
from starlette.testclient import TestClient

from atlas import workspace_folders as wf
from atlas.api import create_app
from atlas.engine.core import config
from atlas.projects import Projects


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path / 'storage')
    monkeypatch.setenv('PXG_HOME', str(tmp_path / 'pxg'))
    return TestClient(create_app(Projects(tmp_path / 'storage')))


def write_choice(tmp_path, content):
    (tmp_path / 'pxg').mkdir(exist_ok=True)
    (tmp_path / 'pxg' / wf.FILE_NAME).write_text(content, encoding='utf-8')


def test_no_choice_means_no_project(client):
    body = client.get('/api/folder/project').json()
    assert body['project'] == ''
    assert [f['found'] for f in body['folders']] == [False, False]


def test_broken_or_foreign_file_is_no_choice(tmp_path, client):
    write_choice(tmp_path, '{не json')
    assert client.get('/api/folder/project').json()['project'] == ''
    write_choice(tmp_path, json.dumps({'project': ['список']}))
    assert client.get('/api/folder/project').json()['project'] == ''


def test_state_lists_subfolders_and_files(tmp_path, client):
    project = tmp_path / 'проект'
    (project / 'готовые').mkdir(parents=True)
    (project / 'готовые' / 'карта ГСП.xlsx').write_bytes(b'x')
    (project / 'готовые' / '~$временный.xlsx').write_bytes(b'x')
    write_choice(tmp_path, json.dumps({'project': str(project)}))
    body = client.get('/api/folder/project').json()
    assert body['project'] == str(project)
    ready, exports = body['folders']
    assert ready['slot'] == 'ready' and ready['found'] is True
    assert ready['files'] == ['карта ГСП.xlsx']
    assert exports['slot'] == 'exports' and exports['found'] is False
    assert exports['files'] == []
