from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

import pytest

from pxg_hub import __main__ as menu
from pxg_hub.hub import APPS, App, Hub, project_env


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


FAKE = ['-c', 'import http.server,sys;http.server.HTTPServer(("127.0.0.1",int(sys.argv[1])),http.server.SimpleHTTPRequestHandler).serve_forever()', '{port}']


def test_env_shares_one_project_folder(tmp_path):
    env = project_env(APPS, tmp_path / 'P', root=tmp_path)
    assert env['GAS_ATLAS_STORAGE'] == str(tmp_path / 'P' / 'Атлас')
    assert env['PXG_RUNS_DIR'] == str(tmp_path / 'P' / 'pxg_runs')
    assert env['SCHEDULE_PXG_PROJECT'].startswith(str(tmp_path / 'P'))
    urls = json.loads(env['PXG_APP_URLS'])
    assert set(urls) == {'atlas', 'base', 'maps', 'schedule', 'finder'} and env['PXG_MAPS_URL'] == urls['maps']
    assert len({a.port for a in APPS}) == 5


def test_old_atlas_storage_stays(tmp_path):
    (tmp_path / 'storage' / 'projects' / ('a' * 32)).mkdir(parents=True)
    (tmp_path / 'storage' / 'projects' / ('a' * 32) / 'manifest.json').write_text('{}', encoding='utf-8')
    assert project_env(APPS, tmp_path / 'P', root=tmp_path)['GAS_ATLAS_STORAGE'] == str(tmp_path / 'storage')


def test_start_stop_and_http_menu(tmp_path):
    port, hub_port = free_port(), free_port()
    hub = Hub([App('fake', 'Проба', '', port, FAKE)], project=tmp_path / 'P', root=tmp_path)
    server, quit_event = menu.serve(hub, hub_port)
    base = 'http://127.0.0.1:%d' % hub_port
    try:
        def call(path, header=True):
            req = urllib.request.Request(base + path, method='POST', headers={'X-PXG': '1'} if header else {})
            return json.load(urllib.request.urlopen(req))
        with pytest.raises(urllib.error.HTTPError) as err:  # без заголовка запускать нельзя
            call('/api/start/fake', header=False)
        assert err.value.code == 403
        assert json.load(urllib.request.urlopen(base + '/api/status'))['apps'][0]['running'] is False
        assert call('/api/start/fake')['url'] == 'http://127.0.0.1:%d/' % port
        row = json.load(urllib.request.urlopen(base + '/api/status'))['apps'][0]
        assert row['running'] and row['ours'] and (tmp_path / 'P' / 'logs').is_dir()
        call('/api/stop/fake')
        assert not hub.status()[0]['running']
        assert b'<title>' in urllib.request.urlopen(base + '/').read()
        call('/api/quit')
        assert quit_event.is_set()
    finally:
        hub.stop_all()
        server.shutdown()


def test_open_runs_on_server_and_page_has_no_blank_popup(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(menu, 'open_app', lambda app: opened.append(app.id))
    port, hub_port = free_port(), free_port()
    hub = Hub([App('fake', 'Проба', '', port, FAKE)], project=tmp_path / 'P', root=tmp_path)
    server, quit_event = menu.serve(hub, hub_port)
    base = 'http://127.0.0.1:%d' % hub_port
    try:
        page = urllib.request.urlopen(base + '/').read().decode('utf-8')
        assert 'about:blank' not in page and 'window.open' not in page
        req = urllib.request.Request(base + '/api/start/fake?open=1', method='POST', headers={'X-PXG': '1'})
        urllib.request.urlopen(req).read()
        assert opened == ['fake']
    finally:
        hub.stop_all()
        server.shutdown()
