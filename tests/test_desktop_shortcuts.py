from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / 'tools'
spec = importlib.util.spec_from_file_location('desktop_shortcuts', str(TOOLS / 'desktop_shortcuts.py'))
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)


def test_every_launcher_has_png_and_ico():
    for icon, _title, _bat, _sh in ds.APPS:
        for ext in ('.png', '.ico'):
            assert (TOOLS / 'icons' / (icon + ext)).stat().st_size > 1000


@pytest.mark.skipif(os.name == 'nt', reason='.desktop-файлы создаются только на Linux')
def test_creates_and_removes_desktop_files(tmp_path):
    root = tmp_path / 'Gas_Atlas'
    for _, _, _, sh in ds.APPS:
        root.mkdir(exist_ok=True)
        (root / sh).write_text('#!/bin/bash\n')
    made = ds.create(tmp_path / 'desk', root)
    assert len(made) == len(ds.APPS)
    text = (tmp_path / 'desk' / 'Газовый атлас 6.desktop').read_text(encoding='utf-8')
    assert 'Terminal=true' in text and 'gas_atlas_6.sh' in text and 'gas_atlas_6.png' in text
    assert ds.remove(tmp_path / 'desk') == len(ds.APPS)
