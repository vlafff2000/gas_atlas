import time

from starlette.testclient import TestClient

from atlas import resources
from atlas.api import create_app
from atlas.projects import Projects


def test_resources_endpoint_and_cache(tmp_path):
    client = TestClient(create_app(Projects(tmp_path)))
    pid = client.post('/api/projects/demo').json()['id']
    resources._sizes.clear()
    first = client.get('/api/resources', params={'project': pid}).json()
    assert set(first) == {'ram', 'project', 'all', 'cpu'} and first['project'] is None     # первый запрос не ждёт обхода диска
    for _ in range(100):
        data = client.get('/api/resources', params={'project': pid}).json()
        if data['project'] and data['all']:
            break
        time.sleep(0.05)
    assert 0 < data['project']['bytes'] <= data['all']['bytes'] and data['project']['full']
    assert data['cpu']['threads'] >= 1 and data['cpu']['workers'] >= 1
    assert client.get('/api/resources', params={'project': 'bad'}).json()['project'] is None   # чужой id не ломает плашку


def test_budget_gives_partial(tmp_path):
    (tmp_path / 'x').write_bytes(b'1')
    assert resources.folder_size(str(tmp_path), budget=-1) == (0, False)
