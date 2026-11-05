"""Маленький патч запускалок единого Linux-архива: пересоздаёт все .sh/.desktop в корне и кладёт их в tar.gz (~десятки КБ).

    python tools/make_launcher_patch.py --scripts ../all_scripts --out dist/PXG_linux_launchers_patch.tar.gz

Распаковать поверх папки PXG_Unified (в файловом менеджере «Извлечь сюда» или `tar xzf ... --strip-components=1 -C PXG_Unified`):
заменяются только запускалки (LF вместо CRLF, права 755, лог в logs/). Python, модели и данные не затрагиваются.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--scripts', default=str(HERE.parent.parent / 'all_scripts'))
    ap.add_argument('--out', default=str(HERE.parent / 'dist' / 'PXG_linux_launchers_patch.tar.gz'))
    a = ap.parse_args(argv)
    bu = _load(HERE / 'build_unified.py', 'patch_build_unified')
    sp = bu.load(Path(a.scripts) / 'tools' / 'build_portable.py', 'patch_scripts_portable')
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / bu.NAME
        folder.mkdir()
        bu.write_launchers('linux', folder, sp)
        for name in ('ПРОЧТИТЕ.txt',):  # текст инструкции патч не меняет
            (folder / name).unlink(missing_ok=True)
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(str(out), 'w:gz') as t:
            bu.bp.add_tree(t, folder, bu.NAME)
    print('Готово: %s (%d КБ)' % (out, out.stat().st_size // 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
