"""Память экспорта: последние настройки вкладок хранятся в папке проекта и сбрасываются."""
import pytest
from starlette.testclient import TestClient

import atlas.api_projects as api_projects
from atlas.api import create_app
from atlas.projects import Projects


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(api_projects, 'LOG_DIR', tmp_path / 'logs')
    client = TestClient(create_app(Projects(tmp_path / 'storage')))
    return client, client.post('/api/projects/demo').json()['id']


def test_form_and_tab_survive_and_reset(env):
    client, pid = env
    url = f'/api/projects/{pid}/export/memory'
    assert client.get(url).json() == {'form': {}, 'tab': None}
    form = {'font': 'calibri', 'width': 170, 'fmt_legend': 'bottom', 'production_wells': ['1'], 'modules': ['production']}
    saved = client.post(url, json={'form': form, 'tab': 'gdi'}).json()
    assert saved['tab'] == 'gdi' and 'production_wells' not in saved['form']      # фильтры скважин живут в настройках проекта
    again = client.get(url).json()
    assert again['form']['font'] == 'calibri' and again['form']['fmt_legend'] == 'bottom' and again['tab'] == 'gdi'
    assert client.post(url + '/reset').json() == {'form': {}, 'tab': None}
    assert client.get(url).json() == {'form': {}, 'tab': None}
    assert client.post(url + '/reset').status_code == 200            # повторный сброс безвреден


def test_too_big_rejected(env):
    client, pid = env
    r = client.post(f'/api/projects/{pid}/export/memory', json={'form': {'x': 'я' * 300_000}})
    assert r.status_code == 400
