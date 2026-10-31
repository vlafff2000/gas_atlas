"""Окно приложения без pywebview: браузер на Chromium (Яндекс, Chromium, Chrome, Edge) с ``--app``.

Нужно на РЕД ОС, где pywebview нет: страница открывается отдельным окном без адресной строки и вкладок,
со своим профилем (обычный браузер пользователя не затрагивается). Нет подходящего браузера — вызывающий
открывает обычный.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from typing import Optional

_CHROMIUM = ('yandex-browser', 'yandex-browser-stable', 'chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable',
             'chrome', 'brave-browser', 'microsoft-edge', 'microsoft-edge-stable')


def chromium_path() -> str:
    for name in _CHROMIUM:
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')):
        for rel in (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe'):
            path = os.path.join(base, rel) if base else ''
            if path and os.path.isfile(path):
                return path
    return ''


def profile_dir(title: str) -> str:
    slug = re.sub(r'[^0-9A-Za-zА-Яа-я]+', '_', title).strip('_') or 'app'
    return os.path.join(os.path.expanduser('~'), '.pxg', 'app_window', slug)


def open_app_window(url: str, title: str) -> Optional[subprocess.Popen]:
    exe = chromium_path()
    if not exe:
        return None
    try:
        return subprocess.Popen([exe, '--app=' + url, '--user-data-dir=' + profile_dir(title), '--no-first-run',
                                 '--no-default-browser-check', '--class=PxgApp'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def wait_closed(proc: subprocess.Popen) -> bool:
    """Ждёт закрытия окна. True — окно закрыл пользователь; False — браузер передал страницу уже запущенному
    экземпляру и сразу вышел (окно живёт дальше, сервер останавливать нельзя)."""
    started = time.monotonic()
    try:
        proc.wait()
    except KeyboardInterrupt:
        return True
    return time.monotonic() - started > 5
