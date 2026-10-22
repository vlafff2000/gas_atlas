"""Адрес Карт ГСП берётся из PXG_MAPS_URL (меню pxg_hub передаёт его при запуске)."""
import socket

import pytest
from starlette.testclient import TestClient

from atlas.api import create_app
from atlas.projects import Projects


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Projects(tmp_path / 'storage')))


def test_maps_url_from_env(client, monkeypatch):
    monkeypatch.setenv('PXG_MAPS_URL', ' http://127.0.0.1:8767 ')
    assert client.get('/api/app/links').json() == {'maps_url': 'http://127.0.0.1:8767'}


def test_maps_url_empty_when_not_set(client, monkeypatch):
    monkeypatch.delenv('PXG_MAPS_URL', raising=False)
    assert client.get('/api/app/links').json() == {'maps_url': ''}


def test_maps_open_redirects_to_well_when_maps_running(client, monkeypatch):
    with socket.socket() as srv:
        srv.bind(('127.0.0.1', 0))
        srv.listen()
        port = srv.getsockname()[1]
        monkeypatch.setenv('PXG_MAPS_URL', f'http://127.0.0.1:{port}/')
        r = client.get('/api/app/maps?well=123', follow_redirects=False)
    assert r.status_code == 302
    assert r.headers['location'] == f'http://127.0.0.1:{port}/#/map?well=123'


def test_maps_open_explains_when_maps_not_running(client, monkeypatch):
    with socket.socket() as srv:
        srv.bind(('127.0.0.1', 0))
        port = srv.getsockname()[1]   # порт свободен: слушателя нет
    monkeypatch.setenv('PXG_MAPS_URL', f'http://127.0.0.1:{port}')
    r = client.get('/api/app/maps?well=123')
    assert r.status_code == 200 and 'Карты ГСП не запущены' in r.text


def test_maps_open_rejects_bad_well(client, monkeypatch):
    monkeypatch.setenv('PXG_MAPS_URL', 'http://127.0.0.1:1')
    assert client.get('/api/app/maps?well=12a').status_code == 400
    assert client.get('/api/app/maps').status_code == 400
