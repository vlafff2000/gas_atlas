"""Ярлыки приложений со значками для рабочего стола (переносная папка): python tools/desktop_shortcuts.py [--dir ПАПКА] [--remove].

Windows: файлы .lnk (через pywin32); Linux: файлы .desktop. Запускалки и значки берутся из папки программы.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent  # tools/ лежит в папке программы
# (имя значка, название ярлыка, запускалка Windows, запускалка Linux, нужен ли терминал)
APPS = [
    ('gas_atlas_6', 'Газовый атлас 6', 'Gas_Atlas_6.bat', 'gas_atlas_6.sh'),
]


def desktop_dir() -> Path:
    home = Path.home()
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0000, None, 0, buf) == 0 and buf.value:  # CSIDL_DESKTOP
                return Path(buf.value)
        except Exception:
            pass
        return home / 'Desktop'
    try:
        found = subprocess.check_output(['xdg-user-dir', 'DESKTOP'], stderr=subprocess.DEVNULL).decode('utf-8').strip()
        if found and Path(found) != home:
            return Path(found)
    except Exception:
        pass
    for name in ('Рабочий стол', 'Desktop'):
        if (home / name).is_dir():
            return home / name
    return home / 'Desktop'


def desktop_entry(title: str, script: Path, icon: Path) -> str:
    """Содержимое файла .desktop: терминал нужен, потому что в нём работает сервер приложения."""
    return ('[Desktop Entry]\nType=Application\nVersion=1.0\nName={name}\nComment={name}\n'
            'Exec=bash "{script}"\nPath={folder}\nIcon={icon}\nTerminal=true\nCategories=Utility;\n').format(
        name=title, script=script, folder=script.parent, icon=icon)


def create(target: Path, root: Path = ROOT) -> List[Tuple[str, Path]]:
    target.mkdir(parents=True, exist_ok=True)
    made = []  # type: List[Tuple[str, Path]]
    for icon, title, bat, sh in APPS:
        if os.name == 'nt':
            script, suffix = root / bat, '.lnk'
        else:
            script, suffix = root / sh, '.desktop'
        if not script.exists():
            continue
        path = target / (title + suffix)
        if os.name == 'nt':
            import pythoncom  # pywin32 лежит в переносной папке
            from win32com.shell import shell  # IShellLink понимает Юникод в именах; WScript.Shell — только символы текущей кодовой страницы
            link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
            link.SetPath(str(script))
            link.SetWorkingDirectory(str(root))
            link.SetIconLocation(str(root / 'tools' / 'icons' / (icon + '.ico')), 0)
            link.SetDescription(title)
            link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path.resolve()), 0)
        else:
            path.write_text(desktop_entry(title, script, root / 'tools' / 'icons' / (icon + '.png')), encoding='utf-8')
            path.chmod(0o755)
            try:  # GNOME без этого не доверяет ярлыку; в других оболочках gio может не быть
                subprocess.call(['gio', 'set', str(path), 'metadata::trusted', 'true'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
        made.append((title, path))
    return made


def remove(target: Path) -> int:
    count = 0
    for _, title, _, _ in APPS:
        for suffix in ('.lnk', '.desktop'):
            path = target / (title + suffix)
            if path.exists():
                path.unlink()
                count += 1
    return count


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    target = desktop_dir()
    if '--dir' in argv:
        target = Path(argv[argv.index('--dir') + 1])
    if '--remove' in argv:
        print('Удалено ярлыков: %d (%s)' % (remove(target), target))
        return 0
    made = create(target)
    for title, path in made:
        print('Создан ярлык «%s»: %s' % (title, path))
    print('Готово: %d ярлыков на рабочем столе (%s). Папку с программой не переносите: ярлыки ссылаются на неё.' % (len(made), target))
    return 0


if __name__ == '__main__':
    sys.exit(main())
