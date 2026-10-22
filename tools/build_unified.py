"""Build ONE portable folder with all PXG apps: Gas Atlas + База ПХГ + Карты ГСП + Скедул ПХГ, one Python 3.13, one launcher menu.

    python tools/build_unified.py windows --scripts ../all_scripts  ->  dist/PXG_Unified_portable_windows_x64.zip
    python tools/build_unified.py linux   --scripts ../all_scripts  ->  dist/PXG_Unified_portable_linux_x64.tar.gz

Runtime, wheels and the application files of Gas Atlas come from tools/build_portable.py (same pins, glibc 2.17 / Windows 10+);
the files and launchers of the other apps come from a checkout of the repository all_scripts. The separate archives of both
repositories are not touched.
"""
import importlib.util
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bp = load(HERE / 'build_portable.py', 'atlas_build_portable')
NAME = 'PXG_Unified'
SCRIPTS_INCLUDE = ['pxg_base', 'gsp_maps', 'pxg_core', 'schedule_pxg', 'tnav_results', 'apps']
HUB_WINDOWS = {'PXG_Hub.bat': 'rem Все приложения ПХГ: меню (окно или браузер).\r\n"%~dp0python\\python.exe" -s -X utf8 -m pxg_hub %*'}
HUB_LINUX = {'pxg_hub.sh': '# Все приложения ПХГ: меню в браузере. На РЕД ОС: bash pxg_hub.sh в этой папке.\nexec "$PY" -s -X utf8 -m pxg_hub --browser "$@"'}
SHORTCUTS_WINDOWS = ('rem Ярлыки всех приложений на рабочем столе (убрать: --remove).\r\n'
                     '"%~dp0python\\python.exe" -s -X utf8 tools\\desktop_shortcuts.py %*\r\n'
                     '"%~dp0python\\python.exe" -s -X utf8 -m pxg_core.desktop_shortcuts %*\r\n'
                     'echo.\r\necho Нажмите любую клавишу, чтобы закрыть окно.\r\npause >nul\r\nexit /b 0')
SHORTCUTS_LINUX = ('# Ярлыки всех приложений на рабочем столе: bash sozdat_yarlyki.sh (убрать: bash sozdat_yarlyki.sh --remove).\n'
                   '"$PY" -s -X utf8 tools/desktop_shortcuts.py "$@"\n"$PY" -s -X utf8 -m pxg_core.desktop_shortcuts "$@"\n'
                   'echo; read -r -p "Нажмите Enter, чтобы закрыть окно..." _ || true')
README = '''ПХГ — все приложения в одной папке ({target})
=============================================

Python 3.13 и все библиотеки лежат в папке python. Устанавливать и подключаться к интернету не нужно.

1. Распакуйте архив в любую папку, куда у вас есть права на запись ({example}).
2. Запустите {hub} — откроется меню: «Газовый атлас», «База ПХГ», «Карты ГСП», «Скедул ПХГ».
   Кнопка «Открыть» запускает приложение и открывает его; «Закрыть все» останавливает всё.
3. Все приложения кладут данные в одну папку «Проект» рядом с программой (другое место: переменная PXG_PROJECT):
   Атлас — Проект/Атлас, База ПХГ — Проект/pxg_runs, Карты ГСП — Проект/Карты_ГСП, Скедул — Проект/Скедул, журналы — Проект/logs.
   Если рядом с программой уже есть папка storage (проекты Атласа), Атлас продолжает работать с ней.
4. Приложения знают адреса друг друга (переменные PXG_APP_URLS, PXG_MAPS_URL).
5. {shortcuts} — один раз создаёт ярлыки на рабочем столе. Папку после этого не переносите.
6. Отдельные запускалки приложений ({atlas} и др.) тоже работают.
{note}'''


def scripts_requirements(scripts, lock_names):
    extra = []
    for line in (scripts / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if line and ';' not in line and line.lower() not in lock_names:
            extra.append(line)
    return extra + ['defusedxml']  # odfpy тянет defusedxml, а пакеты ставятся без зависимостей


def copy_scripts(scripts, folder):
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--'] + SCRIPTS_INCLUDE, cwd=str(scripts)).decode('utf-8')
    count = 0
    for name in filter(None, tracked.split('\0')):
        dest = folder / name
        if dest.exists():
            raise SystemExit('Файл есть в обоих репозиториях: ' + name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(scripts / name), str(dest))
        count += 1
    icons = folder / 'icons'  # значки all_scripts лежат в icons/, значки Атласа в tools/icons
    icons.mkdir(exist_ok=True)
    for item in (scripts / 'tools' / 'icons').iterdir():
        shutil.copy2(str(item), str(icons / item.name))
    print('Файлов остальных приложений: %d' % count, flush=True)


def write_launchers(target, folder, sp):
    windows = target == 'windows'
    bp.write_launchers(target, folder)  # Атлас
    launchers = dict(sp.WINDOWS_LAUNCHERS if windows else sp.LINUX_LAUNCHERS)
    launchers.update(HUB_WINDOWS if windows else HUB_LINUX)
    launchers['Sozdat_yarlyki.bat' if windows else 'sozdat_yarlyki.sh'] = SHORTCUTS_WINDOWS if windows else SHORTCUTS_LINUX
    for name, body in launchers.items():
        if windows:
            (folder / name).write_bytes((bp.WINDOWS_PREFIX + body + bp.WINDOWS_SUFFIX).encode('utf-8'))
        else:
            path = folder / name
            path.write_text(bp.LINUX_PREFIX + body + '\n', encoding='utf-8')
            path.chmod(0o755)
    text = README.format(
        target='Windows' if windows else 'Linux x86_64, glibc 2.17+ (РЕД ОС 7.3 и новее)', example='C:\\PXG' if windows else '~/PXG',
        hub='PXG_Hub.bat' if windows else 'pxg_hub.sh', shortcuts='Sozdat_yarlyki.bat' if windows else 'sozdat_yarlyki.sh',
        atlas='Gas_Atlas_6.bat' if windows else 'gas_atlas_6.sh', note=bp.WINDOWS_NOTE if windows else bp.LINUX_NOTE)
    if windows:
        (folder / 'ПРОЧТИТЕ.txt').write_bytes(text.replace('\n', '\r\n').encode('utf-8-sig'))
    else:
        (folder / 'ПРОЧТИТЕ.txt').write_text(text, encoding='utf-8')


# Стандартная библиотека, без которой меню и приложения не запускаются (проверяется до упаковки архива).
STDLIB_CHECK = ['urllib/parse.py', 'urllib/request.py', 'http/server.py', 'email/utils.py', 'json/__init__.py',
                'logging/__init__.py', 'xml/etree/ElementTree.py', 'zipfile/__init__.py', 'encodings/utf_8.py']


def check_runtime(folder, target):
    lib = folder / 'python' / ('Lib' if target == 'windows' else 'lib/python3.13')
    missing = [name for name in STDLIB_CHECK if not (lib / name).is_file()]
    if target == 'windows':  # pywin32.pth: каждая строка-путь должна существовать, иначе Python пишет ошибку при каждом запуске
        site = lib / 'site-packages'
        for line in (site / 'pywin32.pth').read_text(encoding='utf-8').splitlines():
            line = line.strip().replace('\\', '/')
            if line and not line.startswith(('#', 'import ')) and not (site / line).is_dir():
                missing.append('pywin32.pth: ' + line)
        if not (site / 'win32' / 'lib' / 'pywin32_bootstrap.py').is_file():
            missing.append('win32/lib/pywin32_bootstrap.py')
    if missing:
        raise SystemExit('В сборке не хватает файлов Python: ' + ', '.join(missing))
    print('Стандартная библиотека и pywin32 на месте', flush=True)


def archive(target, folder, out):
    out.mkdir(parents=True, exist_ok=True)
    if target == 'windows':
        path = out / 'PXG_Unified_portable_windows_x64.zip'
        with zipfile.ZipFile(str(path), 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for item in sorted(folder.rglob('*')):
                if item.is_file():
                    z.write(str(item), str(Path(NAME) / item.relative_to(folder)))
    else:
        path = out / 'PXG_Unified_portable_linux_x64.tar.gz'
        with tarfile.open(str(path), 'w:gz') as t:
            t.add(str(folder), arcname=NAME)
    print('Готово: %s (%.0f МБ)' % (path, path.stat().st_size / 2**20), flush=True)


def smoke_test(folder):
    import os
    python = folder / 'python' / ('python.exe' if os.name == 'nt' else 'bin/python3.13')
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    env.update(PYTHONNOUSERSITE='1', MPLBACKEND='Agg', GAS_ATLAS_STORAGE=tempfile.mkdtemp())
    code = ('import sys, atlas.api, pxg_hub, pandas, scipy, pyarrow, matplotlib, python_calamine, xlsxwriter, odf, pxg_core.расходы_файлы;'
            + ('import webview, win32api, win32com.shell.shell;' if os.name == 'nt' else '') +
            'atlas.api.create_app();import pxg_base.api as a;a.build_app();import gsp_maps.api as m;m.build_app();'
            'import schedule_pxg.api as s;s.build_app();assert sys.prefix.startswith({!r}), sys.prefix;print("ok", sys.version.split()[0])').format(str(folder))
    try:
        subprocess.check_call([str(python), '-s', '-c', code], cwd=str(folder), env=env)
    finally:
        shutil.rmtree(env['GAS_ATLAS_STORAGE'], ignore_errors=True)


def main(argv=None):
    import argparse
    import os
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('target', choices=sorted(bp.RUNTIMES))
    parser.add_argument('--scripts', default=str(ROOT.parent / 'all_scripts'), help='папка с репозиторием all_scripts')
    parser.add_argument('--out', default=str(ROOT / 'dist'))
    parser.add_argument('--cache', default=str(ROOT / 'build' / 'cache'))
    args = parser.parse_args(argv)
    scripts = Path(args.scripts).resolve()
    sp = load(scripts / 'tools' / 'build_portable.py', 'scripts_build_portable')

    spec = bp.RUNTIMES[args.target]
    runtime = bp.fetch(spec['url'], spec['sha256'], Path(args.cache))
    build = ROOT / 'build' / ('unified_' + args.target)
    shutil.rmtree(str(build), ignore_errors=True)
    folder = build / NAME
    python_dir = folder / 'python'
    python_dir.mkdir(parents=True)
    bp.unpack_runtime(args.target, runtime, python_dir)

    lock_requirements = bp.requirements_for
    lock_names = {r.split('=')[0].lower() for r in lock_requirements(args.target)}
    extra = scripts_requirements(scripts, lock_names)
    bp.SDIST_ONLY.add('odfpy')
    bp.requirements_for = lambda target: lock_requirements(target) + extra
    with tempfile.TemporaryDirectory() as tmp:
        bp.install_packages(args.target, python_dir / spec['site'], Path(tmp))
    for stray in (python_dir / spec['site']).glob('*.whl'):  # копии колёс в site-packages ничего не импортируют
        stray.unlink()
    bp.SKIP_TOOLS.add('tools/build_unified.py')
    bp.INCLUDE.append('pxg_hub')
    bp.copy_application(folder)
    copy_scripts(scripts, folder)
    write_launchers(args.target, folder, sp)
    check_runtime(folder, args.target)
    if (args.target == 'windows') == (os.name == 'nt'):
        smoke_test(folder)
        shutil.rmtree(str(folder / 'logs'), ignore_errors=True)
    for cache in folder.rglob('__pycache__'):
        shutil.rmtree(str(cache), ignore_errors=True)
    archive(args.target, folder, Path(args.out))
    shutil.rmtree(str(build), ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
