import base64
import sys
import types

import pytest

from atlas.desktop_save import SaveApi, clean_name, unique_path


def test_clean_name():
    assert clean_name("..\\a/b:c?.xlsx") == "b_c_.xlsx"
    assert clean_name("") == "atlas"


def test_unique_path(tmp_path):
    (tmp_path / "a.png").write_bytes(b"1")
    assert unique_path(str(tmp_path), "a.png").endswith("a (1).png")


class FakeWindow:
    def __init__(self, answer):
        self.answer, self.asked = answer, None

    def create_file_dialog(self, kind, **kw):
        self.asked = kw
        return self.answer


@pytest.fixture
def fake_webview(monkeypatch):
    mod = types.SimpleNamespace(SAVE_DIALOG=10, FileDialog=None)
    monkeypatch.setitem(sys.modules, "webview", mod)


def test_saves_to_chosen_path(tmp_path, fake_webview):
    api = SaveApi()
    target = tmp_path / "g.xlsx"
    api.bind(FakeWindow((str(target),)))
    r = api.save_file("g.xlsx", base64.b64encode(b"data").decode())
    assert r["ok"] and target.read_bytes() == b"data"


def test_cancel_writes_nothing(tmp_path, fake_webview):
    api = SaveApi()
    api.bind(FakeWindow(None))
    assert api.save_file("g.xlsx", "AA==") == {"ok": False}


def test_dialog_failure_falls_back_to_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "Downloads").mkdir()
    monkeypatch.delitem(sys.modules, "webview", raising=False)
    api = SaveApi()
    api.bind(FakeWindow(None))  # import webview не удастся -> «Загрузки»
    monkeypatch.setitem(sys.modules, "webview", None)
    r = api.save_file("g.csv", base64.b64encode(b"x").decode())
    assert r["ok"] and (tmp_path / "Downloads" / "g.csv").read_bytes() == b"x"
