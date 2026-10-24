"""Архив обновления: когда лёгкий архив можно собрать, а когда нужен полный (без сети, без pip)."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('build_unified_test', ROOT / 'tools' / 'build_unified.py')
bu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bu)

PY = {'sha256': 'a' * 64}


def write_manifest(path, requirements, installed=None):
    data = {'target': 'linux', 'runtime_sha256': PY['sha256'], 'requirements': requirements, 'installed': installed or {'six': '1.17.0'}}
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def test_load_base_accepts_added_libraries(tmp_path):
    manifest = write_manifest(tmp_path / 'base.json', ['six==1.17.0'])
    base = bu.load_base(manifest, 'linux', PY, ['six==1.17.0', 'python-dateutil'])
    assert base['installed'] == {'six': '1.17.0'}


def test_load_base_refuses_changed_pin(tmp_path):
    manifest = write_manifest(tmp_path / 'base.json', ['six==1.17.0'])
    with pytest.raises(SystemExit, match='изменились библиотеки'):
        bu.load_base(manifest, 'linux', PY, ['six==1.16.0'])


def test_load_base_refuses_other_python(tmp_path):
    manifest = write_manifest(tmp_path / 'base.json', ['six==1.17.0'])
    with pytest.raises(SystemExit, match='изменился Python'):
        bu.load_base(manifest, 'linux', {'sha256': 'b' * 64}, ['six==1.17.0'])


def test_load_base_needs_manifest(tmp_path):
    with pytest.raises(SystemExit, match='нет манифеста'):
        bu.load_base(tmp_path / 'missing.json', 'linux', PY, ['six==1.17.0'])


def test_add_new_libraries_adds_nothing_when_libs_known(tmp_path):
    manifest = write_manifest(tmp_path / 'base.json', ['six==1.17.0'])
    base = bu.load_base(manifest, 'linux', PY, ['six==1.17.0'])
    assert bu.add_new_libraries({'platforms': []}, ['six==1.17.0'], base, tmp_path / 'site', tmp_path) == []


def test_installed_dists_reads_metadata(tmp_path):
    info = tmp_path / 'Some_Pkg-2.0.dist-info'
    info.mkdir()
    (info / 'METADATA').write_text('Metadata-Version: 2.1\nName: Some-Pkg\nVersion: 2.0\n', encoding='utf-8')
    found = bu.installed_dists(tmp_path)
    assert found == {'some-pkg': ('Some-Pkg', '2.0', info)}
