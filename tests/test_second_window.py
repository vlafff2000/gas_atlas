"""Второе окно: маршрут сервера открывает окно через зарегистрированный обработчик."""
from starlette.applications import Starlette
from starlette.testclient import TestClient

from atlas import second_window


def _client():
    return TestClient(Starlette(routes=[second_window.route()]))


def test_without_opener_reports_not_opened():
    second_window.set_opener(None)
    assert _client().post('/api/second-window', json={'hash': '/map'}).json() == {'opened': False}


def test_opener_gets_hash():
    seen = []
    second_window.set_opener(seen.append)
    try:
        assert _client().post('/api/second-window', json={'hash': '/fund'}).json() == {'opened': True}
    finally:
        second_window.set_opener(None)
    assert seen == ['#/fund']
