"""Build a portable Gas Atlas folder: its own CPython 3.8 + all packages + the application.

    python tools/build_portable.py windows   ->  dist/Gas_Atlas_portable_windows_x64.zip
    python tools/build_portable.py linux     ->  dist/Gas_Atlas_portable_linux_x64.tar.gz

The target computer needs neither Python, nor pip, nor the internet: unpack and start the launcher.
The build machine needs the internet and pip (any OS, Python 3.8+); packages are taken from
requirements-lock-py38.txt as binary wheels for the target platform, nothing is compiled.

Runtimes (pinned by sha256):
- Windows: the official python.org CPython 3.8.10 x64 from nuget.org (PSF-signed, runs on Windows 7 SP1+).
- Linux: python-build-standalone CPython 3.8.20 x86_64 (needs glibc 2.17+, e.g. РЕД ОС 7.3+);
  wheels are limited to manylinux2014 (glibc 2.17) for the same reason.
"""
import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'requirements-lock-py38.txt'
NAME = 'Gas_Atlas'

RUNTIMES = {
    'windows': dict(
        url='https://api.nuget.org/v3-flatcontainer/python/3.8.10/python.3.8.10.nupkg',
        sha256='c63a2fc8fc62612b5abd391fda99ae1d90bad42ed8a9e99b1bd81c7ffdb4fefa',
        site='Lib/site-packages', platforms=['win_amd64'],
        marker_env={'sys_platform': 'win32', 'platform_system': 'Windows', 'os_name': 'nt'}),
    'linux': dict(
        url='https://github.com/astral-sh/python-build-standalone/releases/download/20241002/'
            'cpython-3.8.20%2B20241002-x86_64-unknown-linux-gnu-install_only.tar.gz',
        sha256='285e141c36f88b2e9357654c5f77d1f8fb29cc25132698fe35bb30d787f38e87',
        site='lib/python3.8/site-packages',
        platforms=['manylinux2014_x86_64', 'manylinux2010_x86_64', 'manylinux1_x86_64'],
        marker_env={'sys_platform': 'linux', 'platform_system': 'Linux', 'os_name': 'posix'}),
}

# Tracked application files that go into the folder (tests, interface sources and dev scripts stay out).
INCLUDE = ['app', 'atlas', 'tools', 'examples', 'docs', 'README.md', 'CHANGES_v5.md', 'CHANGES_UI_update.md',
           'requirements-lock-py38.txt']
SDIST_ONLY = {'proxy-tools'}  # pywebview dependency, pure Python
SKIP_TOOLS = {'tools/build_portable.py', 'tools/install.py', 'tools/make_pressure_samples.py'}

WINDOWS_LAUNCHERS = {
    'Gas_Atlas_6.bat': 'rem Газовый атлас 6: окно приложения (или браузер, если окно недоступно).\r\n'
                       '"%~dp0python\\python.exe" -s -X utf8 -m atlas %*',
    'Gas_Atlas_5.8.bat': 'rem Газовый атлас 5.8 (Streamlit) в браузере.\r\n'
                         '"%~dp0python\\python.exe" -s -X utf8 tools\\launch.py %*',
}
WINDOWS_PREFIX = ('@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n'
                  'set PYTHONHOME=\r\nset PYTHONPATH=\r\nset PYTHONNOUSERSITE=1\r\nset PYTHONUTF8=1\r\n')
WINDOWS_SUFFIX = '\r\nif errorlevel 1 pause\r\n'

LINUX_LAUNCHERS = {
    'gas_atlas_6.sh': '# Газовый атлас 6 в браузере.\nexec "$PY" -s -X utf8 -m atlas --browser "$@"',
    'gas_atlas_5.8.sh': '# Газовый атлас 5.8 (Streamlit) в браузере.\nexec "$PY" -s -X utf8 tools/launch.py "$@"',
}
LINUX_PREFIX = ('#!/usr/bin/env bash\nset -eu\ncd -- "$(dirname -- "$(readlink -f -- "$0")")"\n'
                'unset PYTHONHOME PYTHONPATH\nexport PYTHONNOUSERSITE=1 PYTHONUTF8=1\nPY=python/bin/python3.8\n')

README = '''Газовый атлас — переносная версия ({target})
=============================================

Ничего устанавливать не нужно: Python 3.8 и все библиотеки уже лежат в папке python.
Интернет не нужен.

1. Распакуйте архив в любую папку, куда у вас есть права на запись
   (например, {example}).
2. Запустите {six} — Газовый атлас 6.
   {five} — прежняя версия 5.8.

Проекты, исключённые точки и настройки хранятся в папке storage рядом с программой.
При переходе на новую версию скопируйте папку storage в новую распакованную папку.
Другая папка данных: переменная окружения GAS_ATLAS_STORAGE.
{note}'''

WINDOWS_NOTE = '''
Если окно приложения не открылось (нет компонента Microsoft Edge WebView2),
атлас откроется в браузере по умолчанию — это нормально.
Если запуск заблокирован политикой безопасности, попросите ИТ разрешить
python\\python.exe в этой папке (файл подписан Python Software Foundation).
'''
LINUX_NOTE = '''
Атлас открывается в браузере по умолчанию. Если браузер не открылся,
откройте адрес, который программа напечатала в терминале.
Если файл не запускается двойным щелчком: chmod +x *.sh, затем ./gas_atlas_6.sh
'''


def log(message):
    print(message, flush=True)


def fetch(url, sha256, cache):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / url.rsplit('/', 1)[-1].replace('%2B', '+')
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        log('Скачиваю ' + url)
        with urllib.request.urlopen(url) as response, open(str(path) + '.part', 'wb') as out:
            shutil.copyfileobj(response, out)
        os.replace(str(path) + '.part', str(path))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha256:
        raise SystemExit('Контрольная сумма не совпала: {} ({})'.format(path.name, digest))
    return path


def unpack_runtime(target, archive, python_dir):
    if target == 'windows':  # nupkg = zip; the interpreter is in tools/
        with zipfile.ZipFile(str(archive)) as z:
            for item in z.infolist():
                if item.filename.startswith('tools/') and not item.is_dir():
                    dest = python_dir / item.filename[len('tools/'):]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(item) as src, open(str(dest), 'wb') as out:
                        shutil.copyfileobj(src, out)
    else:  # install_only tarball: python/...
        with tarfile.open(str(archive)) as t:
            t.extractall(str(python_dir.parent))


def requirements_for(target):
    try:
        from packaging.requirements import Requirement
    except ImportError:
        from pip._vendor.packaging.requirements import Requirement
    env = dict(RUNTIMES[target]['marker_env'], python_version='3.8', python_full_version='3.8.10',
               implementation_name='cpython', platform_python_implementation='CPython', platform_machine='')
    chosen = []
    for line in LOCK.read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        if req.marker is None or req.marker.evaluate(env):
            chosen.append('{}{}'.format(req.name, req.specifier))
    return chosen


def install_packages(target, site, workdir):
    spec = RUNTIMES[target]
    reqs = workdir / 'requirements.txt'
    chosen = requirements_for(target)
    reqs.write_text('\n'.join(chosen) + '\n', encoding='utf-8')
    wheels = workdir / 'wheels'  # pure-Python packages published only as source: build a universal wheel here
    for line in chosen:
        if line.split('=')[0] in SDIST_ONLY:
            subprocess.check_call([sys.executable, '-m', 'pip', 'wheel', '--disable-pip-version-check', '--no-deps', '--use-pep517',
                                   '-w', str(wheels), line])
    command = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile',
               '--target', str(site), '--upgrade', '--no-deps', '--only-binary=:all:',
               '--python-version', '3.8', '--implementation', 'cp', '--abi', 'cp38', '--find-links', str(wheels),
               '-r', str(reqs)]
    for platform in spec['platforms']:
        command += ['--platform', platform]
    log('Ставлю пакеты для {} ({} шт.)'.format(target, len(reqs.read_text().split())))
    subprocess.check_call(command)
    shutil.rmtree(str(site / 'bin'), ignore_errors=True)  # host-style console scripts; the app runs with -m


def copy_application(folder):
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--'] + INCLUDE, cwd=str(ROOT)).decode('utf-8')
    count = 0
    for name in filter(None, tracked.split('\0')):
        if name in SKIP_TOOLS:
            continue
        dest = folder / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(ROOT / name), str(dest))
        count += 1
    log('Файлов приложения: {}'.format(count))


def write_launchers(target, folder):
    if target == 'windows':
        for name, body in WINDOWS_LAUNCHERS.items():
            (folder / name).write_bytes((WINDOWS_PREFIX + body + WINDOWS_SUFFIX).encode('utf-8'))
        text = README.format(target='Windows', example='C:\\GasAtlas', six='Gas_Atlas_6.bat',
                             five='Gas_Atlas_5.8.bat', note=WINDOWS_NOTE)
        (folder / 'ПРОЧТИТЕ.txt').write_bytes(text.replace('\n', '\r\n').encode('utf-8-sig'))
    else:
        for name, body in LINUX_LAUNCHERS.items():
            path = folder / name
            path.write_text(LINUX_PREFIX + body + '\n', encoding='utf-8')
            path.chmod(0o755)
        text = README.format(target='Linux x86_64, glibc 2.17+ (РЕД ОС 7.3 и новее)', example='~/GasAtlas',
                             six='gas_atlas_6.sh', five='gas_atlas_5.8.sh', note=LINUX_NOTE)
        (folder / 'ПРОЧТИТЕ.txt').write_text(text, encoding='utf-8')


def archive(target, folder, out):
    out.mkdir(parents=True, exist_ok=True)
    if target == 'windows':
        path = out / 'Gas_Atlas_portable_windows_x64.zip'
        with zipfile.ZipFile(str(path), 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for item in sorted(folder.rglob('*')):
                if item.is_file():
                    z.write(str(item), str(Path(NAME) / item.relative_to(folder)))
    else:
        path = out / 'Gas_Atlas_portable_linux_x64.tar.gz'
        with tarfile.open(str(path), 'w:gz') as t:
            t.add(str(folder), arcname=NAME)
    log('Готово: {} ({:.0f} МБ)'.format(path, path.stat().st_size / 2**20))
    return path


def smoke_test(folder):
    """Import both apps with the bundled interpreter, isolated from the host (only when building on the target OS)."""
    python = folder / 'python' / ('python.exe' if os.name == 'nt' else 'bin/python3.8')
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    env.update(PYTHONNOUSERSITE='1', MPLBACKEND='Agg')
    env['GAS_ATLAS_STORAGE'] = tempfile.mkdtemp()
    code = ('import sys, atlas.api, app.modules.gdi, streamlit, pandas, scipy, pyarrow, matplotlib, python_calamine;'
            + ('import webview, win32api;' if os.name == 'nt' else '') +
            'atlas.api.create_app();'
            'assert sys.prefix.startswith({!r}), sys.prefix;print("ok", sys.version.split()[0])').format(str(folder))
    try:
        subprocess.check_call([str(python), '-s', '-c', code], cwd=str(folder), env=env)
    finally:
        shutil.rmtree(env['GAS_ATLAS_STORAGE'], ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('target', choices=sorted(RUNTIMES))
    parser.add_argument('--out', default=str(ROOT / 'dist'), help='куда положить архив (dist/)')
    parser.add_argument('--cache', default=str(ROOT / 'build' / 'cache'), help='кэш скачанного Python')
    parser.add_argument('--keep', action='store_true', help='оставить распакованную папку в build/')
    args = parser.parse_args(argv)

    spec = RUNTIMES[args.target]
    runtime = fetch(spec['url'], spec['sha256'], Path(args.cache))
    build = ROOT / 'build' / ('portable_' + args.target)
    shutil.rmtree(str(build), ignore_errors=True)
    folder = build / NAME
    python_dir = folder / 'python'
    python_dir.mkdir(parents=True)
    unpack_runtime(args.target, runtime, python_dir)
    with tempfile.TemporaryDirectory() as tmp:
        install_packages(args.target, python_dir / spec['site'], Path(tmp))
    copy_application(folder)
    write_launchers(args.target, folder)
    if (args.target == 'windows') == (os.name == 'nt'):
        smoke_test(folder)
        shutil.rmtree(str(folder / 'logs'), ignore_errors=True)
    for cache in folder.rglob('__pycache__'):
        shutil.rmtree(str(cache), ignore_errors=True)
    archive(args.target, folder, Path(args.out))
    if not args.keep:
        shutil.rmtree(str(build), ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
