"""Выбор папки проектов Атласа: запуск из меню ПХГ и напрямую видит одни и те же проекты, обновление ничего не затирает."""
import importlib.util
import json
import os
import time
from pathlib import Path

import pytest

from atlas.engine.core import storage_path as sp
from pxg_hub.hub import APPS, project_env

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('build_portable_test', ROOT / 'tools' / 'build_portable.py')
bp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bp)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv('GAS_ATLAS_STORAGE', raising=False)
    monkeypatch.delenv('PXG_PROJECT', raising=False)


def make_project(storage, pid, mtime=None):
    folder = storage / 'projects' / pid
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text(json.dumps({'id': pid, 'name': pid}), encoding='utf-8')
    (folder / 'snapshots').mkdir()
    (folder / 'snapshots' / 'a.parquet').write_bytes(b'data')
    if mtime:
        os.utime(str(folder / 'manifest.json'), (mtime, mtime))
    return folder


def test_empty_storage_does_not_hide_shared_projects(tmp_path):
    """Сценарий пропажи: проекты в Проект/Атлас, а запуск напрямую создал пустую storage."""
    make_project(tmp_path / 'Проект' / 'Атлас', 'a' * 32)
    (tmp_path / 'storage' / 'projects').mkdir(parents=True)
    assert sp.resolve(tmp_path) == tmp_path / 'Проект' / 'Атлас'
    assert project_env(APPS, tmp_path / 'Проект', root=tmp_path)['GAS_ATLAS_STORAGE'] == str(tmp_path / 'Проект' / 'Атлас')


def test_old_storage_with_projects_stays(tmp_path):
    make_project(tmp_path / 'storage', 'b' * 32)
    assert sp.resolve(tmp_path) == tmp_path / 'storage'
    assert project_env(APPS, tmp_path / 'P', root=tmp_path)['GAS_ATLAS_STORAGE'] == str(tmp_path / 'storage')


def test_fresh_install_choice(tmp_path):
    assert sp.resolve(tmp_path) == tmp_path / 'storage'                       # отдельный Атлас
    assert sp.resolve(tmp_path, tmp_path / 'P', unified=True) == tmp_path / 'P' / 'Атлас'   # меню единого архива
    os.environ['PXG_PROJECT'] = str(tmp_path / 'Q')
    try:
        assert sp.resolve(tmp_path) == tmp_path / 'Q' / 'Атлас'               # переменная меню ПХГ
    finally:
        del os.environ['PXG_PROJECT']


def test_explicit_env_wins(tmp_path, monkeypatch):
    make_project(tmp_path / 'storage', 'c' * 32)
    monkeypatch.setenv('GAS_ATLAS_STORAGE', str(tmp_path / 'mine'))
    assert sp.resolve(tmp_path) == tmp_path / 'mine'


def test_both_have_projects_newest_wins_and_adopt_copies_missing(tmp_path):
    now = time.time()
    shared, legacy = tmp_path / 'Проект' / 'Атлас', tmp_path / 'storage'
    make_project(shared, 'a' * 32, now - 1000)
    make_project(legacy, 'b' * 32, now)
    chosen = sp.resolve(tmp_path)
    assert chosen == legacy
    other = sp.others(chosen, tmp_path)
    assert other == [shared]
    assert sp.adopt(chosen, other) == ['a' * 32]
    assert (legacy / 'projects' / ('a' * 32) / 'snapshots' / 'a.parquet').read_bytes() == b'data'
    assert (shared / 'projects' / ('a' * 32) / 'manifest.json').is_file()      # источник не тронут
    assert sp.adopt(chosen, other) == []
    # проект, удалённый в приложении, обратно не возвращается
    import shutil
    shutil.rmtree(str(legacy / 'projects' / ('a' * 32)))
    assert sp.adopt(chosen, other) == []
    assert not (legacy / 'projects' / ('a' * 32)).exists()


def test_user_data_check_for_archives(tmp_path):
    assert bp.user_data_in(['atlas/api.py', 'pxg_hub/hub.py', 'python/lib/x.py', 'ПРОЧТИТЕ.txt']) == []
    bad = bp.user_data_in(['storage/projects/' + 'a' * 32 + '/manifest.json', 'Проект/Атлас/x', 'logs/atlas.log',
                           'sub/history.sqlite', 'well_presets.json', 'projects/x/manifest.json'])
    assert len(bad) == 6
    (tmp_path / 'atlas').mkdir()
    (tmp_path / 'atlas' / 'api.py').write_text('x', encoding='utf-8')
    bp.check_no_user_data(tmp_path)
    (tmp_path / 'storage').mkdir()
    with pytest.raises(SystemExit, match='данные пользователя'):
        bp.check_no_user_data(tmp_path)
