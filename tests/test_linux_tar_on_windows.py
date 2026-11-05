"""Сборка Linux-архива на Windows (без прав на симлинки): симлинки python/ запоминаются и возвращаются в tar, у запускалок есть бит исполнения."""
import importlib.util
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('build_portable_test', ROOT / 'tools' / 'build_portable.py')
bp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bp)


def _runtime_tar(path):
    with tarfile.open(str(path), 'w:gz') as t:
        for name, data in (('python/bin/python3.13', b'\x7fELF....'), ('python/lib/readme.txt', b'text')):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            t.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo('python/bin/python3')
        link.type, link.linkname = tarfile.SYMTYPE, 'python3.13'
        t.addfile(link)


def test_symlinks_and_modes_survive_windows_build(tmp_path, monkeypatch):
    monkeypatch.setattr(bp, 'IS_WINDOWS', True)  # как на ПК без прав администратора
    archive = tmp_path / 'rt.tar.gz'
    _runtime_tar(archive)
    folder = tmp_path / 'PXG'
    (folder / 'python').mkdir(parents=True)
    bp.unpack_runtime('linux', archive, folder / 'python')
    assert not (folder / 'python' / 'bin' / 'python3').exists()  # симлинк на диск не кладётся
    (folder / 'run.sh').write_text('#!/bin/sh\n', encoding='utf-8')
    out = tmp_path / 'out.tar.gz'
    with tarfile.open(str(out), 'w:gz') as t:
        bp.add_tree(t, folder, 'PXG')
    with tarfile.open(str(out)) as t:
        names = {m.name: m for m in t}
    assert names['PXG/python/bin/python3'].issym() and names['PXG/python/bin/python3'].linkname == 'python3.13'
    assert names['PXG/python/bin/python3.13'].mode == 0o755
    assert names['PXG/run.sh'].mode == 0o755
    assert names['PXG/python/lib/readme.txt'].mode == 0o644
    assert 'PXG/python/.pxg_symlinks.json' not in names


def test_ocr_linux_requirements_are_pinned_without_windows_packages():
    lines = (ROOT / 'tools' / 'ocr_linux_requirements.txt').read_text(encoding='utf-8').splitlines()
    assert all('==' in ln and ln == ln.strip() for ln in lines)  # ни пустых строк, ни «==1.3.1» от CRLF
    names = {ln.split('==')[0].lower() for ln in lines}
    assert 'mineru' in names and 'onnxruntime' in names
    assert 'onnxruntime-directml' not in names and 'pip' not in names
