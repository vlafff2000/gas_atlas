"""Адрес Карт ГСП берётся из PXG_MAPS_URL (меню pxg_hub передаёт его при запуске)."""
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
