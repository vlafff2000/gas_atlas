"""Большой демо-объект из интерфейса 6: POST /api/projects/demo {large, rows}. Объёмы в тесте малые."""
from starlette.testclient import TestClient

from atlas.api import create_app
from atlas.projects import Projects

ROWS = {'production': 6000, 'gdi': 700, 'response': 800, 'pressure_match': 900}


def test_large_demo_from_api_and_sections_open(tmp_path):
    client = TestClient(create_app(Projects(tmp_path / 'storage')))
    created = client.post('/api/projects/demo', json={'large': True, 'rows': ROWS})
    assert created.status_code == 201
    pid = created.json()['id']
    project = client.get(f'/api/projects/{pid}').json()
    assert project['demo'] and project['tables'] == ROWS
    for module in ('production', 'histograms', 'gdi', 'response', 'pressure', 'fund', 'groups', 'wells'):
        r = client.post(f'/api/modules/{module}/run', json={'project': pid, 'params': {}})
        assert r.status_code == 200, (module, r.text)


def test_large_demo_rejects_bad_sizes(tmp_path):
    client = TestClient(create_app(Projects(tmp_path / 'storage')))
    for rows in ({'gdi': -1}, {'gdi': 'много'}, {'production': 0}, {'gdi': 10_000_000}):
        assert client.post('/api/projects/demo', json={'large': True, 'rows': rows}).status_code == 400
    assert client.post('/api/projects/demo').status_code == 201      # обычное демо — как раньше
