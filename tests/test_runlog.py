"""Лог Атласа: сведения, пакет для отправки, запись запросов и обезличивание путей."""
import logging
import os
import zipfile

from starlette.testclient import TestClient

from atlas import api_projects, runlog
from atlas.api import create_app


def test_bundle_and_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(api_projects, 'LOG_DIR', tmp_path / 'logs')
    logger = logging.getLogger('atlas')
    old = list(logger.handlers)
    try:
        api_projects.attach_log(tmp_path / 'logs')
        runlog.announce()
        with runlog.timed('этап', файл=os.path.expanduser('~') + '/данные.xlsx') as t:
            t['строк'] = 3
        c = TestClient(create_app(), raise_server_exceptions=False)
        assert c.post('/api/log/bundle').status_code == 200
        c.get('/api/нет-такого')
        for h in logger.handlers:
            h.flush()
        r = c.post('/api/log/bundle').json()
        got = c.get(r['url'])
        assert got.status_code == 200
        z = zipfile.ZipFile(tmp_path / 'logs' / 'send' / r['name'])
        assert {'environment.txt', 'atlas.log'} <= set(z.namelist())
        text = z.read('atlas.log').decode('utf8')
        assert 'запуск «Газовый атлас»' in text and 'этап «этап»' in text and 'строк=3' in text
        assert 'POST /api/log/bundle -> 200' in text and '-> 404' in text
        assert c.get('/api/log/info').json()['files']
        assert c.get('/api/log/bundle/..%2Fx.zip').status_code == 404
    finally:
        for h in list(logger.handlers):
            if h not in old:
                logger.removeHandler(h)
                h.close()


def test_problem_report(tmp_path, monkeypatch):
    import base64
    import json
    monkeypatch.setattr(api_projects, 'LOG_DIR', tmp_path / 'logs')
    c = TestClient(create_app(), raise_server_exceptions=False)
    png = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG-test').decode()
    body = {'description': 'Не строится график', 'page': '#/production', 'viewport': '1200x800',
            'requests': [{'method': 'POST', 'path': '/api/x', 'status': 500, 'ms': 12}],
            'charts': [{'title': 'Закачка', 'option': {'series': [{'type': 'line'}]}, 'png': png}]}
    r = c.post('/api/log/report', json=body).json()
    z = zipfile.ZipFile(tmp_path / 'logs' / 'send' / r['name'])
    assert {'report.txt', 'environment.txt', 'requests.json', 'chart_settings.json', 'chart_1.png'} <= set(z.namelist())
    assert 'Не строится график' in z.read('report.txt').decode('utf8')
    assert z.read('chart_1.png') == b'\x89PNG-test'
    assert json.loads(z.read('chart_settings.json'))[0]['title'] == 'Закачка'
    assert c.get(r['url']).status_code == 200
    assert c.post('/api/log/report', content=b'[1]').status_code == 400
