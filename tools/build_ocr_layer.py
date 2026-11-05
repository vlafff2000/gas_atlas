"""Собирает автономную папку «ocr» (движок распознавания MinerU для Windows) для единого архива PXG_Unified.

    python tools/build_ocr_layer.py --models C:\\OCR\\mineru-home --out build\\ocr

Внутри: ``python`` (встроенный Python 3.12 без установщика, python.org embeddable) с MinerU 4.1.7 и его библиотеками в Lib\\site-packages
и ``mineru-home`` (модели tier standard, ~2 ГБ, копируются как есть). Установки, .exe-установщиков и интернета при работе не нужно.
Дальше папка кладётся в единый архив: ``python tools/build_unified.py windows --with-ocr build\\ocr``.
Модели берутся с ПК, где MinerU уже скачал их (``C:\\OCR\\mineru-home``): в облаке они недоступны.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PY_VERSION = '3.12.10'
PY_URL = 'https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip' % (PY_VERSION, PY_VERSION)
MINERU = 'mineru==4.1.7'
PTH = 'python312._pth'


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, str(dest))
    return dest


def prepare_python(out: Path, cache: Path) -> Path:
    """Распаковывает embeddable Python и разрешает ему site-packages и pip-установку."""
    zp = fetch(PY_URL, cache / ('python-%s-embed-amd64.zip' % PY_VERSION))
    py = out / 'python'
    shutil.rmtree(str(py), ignore_errors=True)
    py.mkdir(parents=True)
    with zipfile.ZipFile(str(zp)) as z:
        z.extractall(str(py))
    (py / 'Lib' / 'site-packages').mkdir(parents=True)
    pth = py / PTH
    lines = [ln for ln in pth.read_text(encoding='utf-8').splitlines() if ln.strip() and not ln.startswith('#')]
    lines += ['Lib\\site-packages', '..', 'import site']
    pth.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return py


def install_mineru(py: Path, cache: Path) -> None:
    """Ставит MinerU и зависимости колёсами (только бинарные) прямо в site-packages встроенного Python."""
    site = py / 'Lib' / 'site-packages'
    pip = cache / 'get-pip.py'
    fetch('https://bootstrap.pypa.io/get-pip.py', pip)
    subprocess.check_call([str(py / 'python.exe'), '-s', str(pip), '--no-warn-script-location', '--disable-pip-version-check'])
    subprocess.check_call([str(py / 'python.exe'), '-s', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location',
                           '--only-binary=:all:', '--no-binary=jieba', '--no-compile', MINERU])  # у jieba на PyPI нет колёс
    for extra in ('Scripts',):
        shutil.rmtree(str(py / extra), ignore_errors=True)  # запускалки pip с жёсткими путями не нужны: запуск идёт через python.exe
    assert (site / 'mineru').is_dir(), 'MinerU не установился'


def copy_models(models: Path, out: Path) -> None:
    dest = out / 'mineru-home'
    if not models.is_dir():
        sys.exit('Нет папки моделей: %s' % models)
    shutil.copytree(str(models), str(dest), dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.log', 'logs', '*.db-wal', '*.db-shm', 'parsed'))


def check(out: Path) -> None:
    """Проверка: MinerU запускается встроенным Python без сети и без venv."""
    code = 'import mineru, sys; from mineru.kit.main import main; print("ok", mineru.__version__ if hasattr(mineru, "__version__") else "", sys.prefix)'
    r = subprocess.run([str(out / 'python' / 'python.exe'), '-s', '-c', code], capture_output=True, text=True, cwd=str(out))
    if r.returncode != 0 or not r.stdout.startswith('ok'):
        sys.exit('Проверка не пройдена:\n%s\n%s' % (r.stdout, r.stderr))
    print(r.stdout.strip())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--models', required=True, help='папка mineru-home с моделями')
    ap.add_argument('--out', default='build/ocr')
    ap.add_argument('--cache', default='build/cache')
    a = ap.parse_args(argv)
    out, cache = Path(a.out).resolve(), Path(a.cache).resolve()
    out.mkdir(parents=True, exist_ok=True)
    py = prepare_python(out, cache)
    install_mineru(py, cache)
    copy_models(Path(a.models), out)
    check(out)
    print('Готово: %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
