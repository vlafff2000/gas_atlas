from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from atlas import fs_browse


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path.parent / (tmp_path.name + "_cfg")))
    return tmp_path


def _tree(root):
    (root / "b_dir").mkdir()
    (root / "a_dir").mkdir()
    (root / ".hidden").write_text("x")
    (root / "t.xlsx").write_bytes(b"12345")
    (root / "n.txt").write_text("x")
    (root / "~$t.xlsx").write_text("x")


def test_list_sorted_filtered(home):
    _tree(home)
    r = fs_browse.list_dir(str(home), filt=".xlsx .xls")
    assert [i["name"] for i in r["items"]] == ["a_dir", "b_dir", "t.xlsx"]
    assert r["items"][2]["size"] == 5 and r["parent"]
    assert ".hidden" in [i["name"] for i in fs_browse.list_dir(str(home), hidden=True)["items"]]
    assert [i["name"] for i in fs_browse.list_dir(str(home), query="T.X")["items"]] == ["t.xlsx"]
    assert [i["name"] for i in fs_browse.list_dir(str(home), only_dirs=True)["items"]] == ["a_dir", "b_dir"]
    page = fs_browse.list_dir(str(home), limit=2, offset=1)
    assert page["total"] == 4 and len(page["items"]) == 2


def test_missing_and_inaccessible(home):
    assert "не найдена" in fs_browse.list_dir(str(home / "no"))["error"]
    d = home / "closed"
    d.mkdir()
    d.chmod(0)
    try:
        r = fs_browse.list_dir(str(d))
        if os.geteuid() != 0:
            assert r["error"] and r["items"] == []
        assert any(i["name"] == "closed" for i in fs_browse.list_dir(str(home))["items"])
    finally:
        d.chmod(0o700)


def test_time_budget(home):
    _tree(home)
    r = fs_browse.list_dir(str(home), budget=-1)
    assert r["truncated"] is True


def test_last_dir_shared(home):
    (home / "x").mkdir()
    assert fs_browse.get_last() == {"dir": "", "recent": []}
    fs_browse.set_last(str(home / "x"))
    f = home / "x" / "a.xlsx"
    f.write_text("1")
    r = fs_browse.set_last(file=str(f))
    assert r["dir"] == str(home / "x") and r["recent"] == [str(f)]
    for i in range(15):
        g = home / "x" / ("f%d.xlsx" % i)
        g.write_text("1")
        fs_browse.set_last(file=str(g))
    r = fs_browse.get_last()
    assert len(r["recent"]) == fs_browse.MAX_RECENT and r["recent"][0].endswith("f14.xlsx")
    f.unlink()
    (home / "x" / "f14.xlsx").unlink()
    assert len(fs_browse.get_last()["recent"]) == fs_browse.MAX_RECENT - 1
    # удалённая папка не возвращается
    fs_browse.set_last(str(home))
    (home / "gone").mkdir()
    fs_browse.set_last(str(home / "gone"))
    (home / "gone").rmdir()
    assert fs_browse.get_last()["dir"] == ""


def test_broken_settings_file(home):
    os.makedirs(os.path.dirname(fs_browse.settings_path()))
    with open(fs_browse.settings_path(), "w") as f:
        f.write("{oops")
    assert fs_browse.get_last()["dir"] == ""
    fs_browse.set_last(str(home))
    assert fs_browse.get_last()["dir"] == str(home)


def test_places_linux_and_windows(home, monkeypatch):
    names = [p["name"] for p in fs_browse.places()]
    assert "Домашняя" in names
    monkeypatch.setattr(fs_browse.os, "name", "nt")
    real_exists, real_isdir = os.path.exists, os.path.isdir
    monkeypatch.setattr(fs_browse.os.path, "exists", lambda p: p in ("C:\\", "D:\\") or real_exists(p))
    monkeypatch.setattr(fs_browse.os.path, "isdir", lambda p: p in ("C:\\", "D:\\") or real_isdir(p))
    drives = [p["name"] for p in fs_browse.places() if p["kind"] == "drive"]
    assert drives == ["C:", "D:"]


def test_routes(home):
    from starlette.applications import Starlette
    _tree(home)
    c = TestClient(Starlette(routes=fs_browse.routes()))
    assert c.post("/api/fs/last", json={"dir": str(home)}).json()["dir"] == str(home)
    r = c.get("/api/fs/list", params={"filter": "xlsx"}).json()  # без path — последняя папка
    assert r["path"] == str(home) and [i["name"] for i in r["items"]] == ["a_dir", "b_dir", "t.xlsx"]
    assert c.get("/api/fs/list", params={"path": str(home / "t.xlsx")}).json()["path"] == str(home)
    assert c.get("/api/fs/places").json()["places"]
    assert c.get("/api/fs/last").json()["dir"] == str(home)
    assert c.post("/api/fs/last", data="junk").json()["dir"] == str(home)


def test_file_route(home):
    from starlette.applications import Starlette
    f = home / "a.txt"
    f.write_bytes(b"abc")
    c = TestClient(Starlette(routes=fs_browse.routes()))
    assert c.get("/api/fs/file", params={"path": str(f)}).content == b"abc"
    assert c.get("/api/fs/file", params={"path": str(home / "no")}).status_code == 404
    assert c.get("/api/fs/file").status_code == 404


def test_mounted_in_atlas(home):
    from atlas.api import create_app
    assert TestClient(create_app()).get("/api/fs/places").status_code == 200
