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
