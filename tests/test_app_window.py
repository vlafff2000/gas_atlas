"""Окно приложения без pywebview (РЕД ОС): Chromium-браузер с --app и отдельным профилем."""
from __future__ import annotations

from atlas import app_window


def test_open_app_window_command(monkeypatch):
    calls = []
    monkeypatch.setattr(app_window, 'chromium_path', lambda: '/usr/bin/yandex-browser')
    monkeypatch.setattr('subprocess.Popen', lambda cmd, **kw: calls.append(cmd) or object())
    assert app_window.open_app_window('http://127.0.0.1:1/', 'Газовый атлас') is not None
    cmd = calls[0]
    assert cmd[0] == '/usr/bin/yandex-browser' and '--app=http://127.0.0.1:1/' in cmd
    assert any(a.startswith('--user-data-dir=') and '.pxg' in a for a in cmd)


def test_no_browser(monkeypatch):
    monkeypatch.setattr(app_window, 'chromium_path', lambda: '')
    assert app_window.open_app_window('http://x/', 'a') is None


def test_finds_yandex(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda n: '/opt/yb' if n == 'yandex-browser' else None)
    assert app_window.chromium_path() == '/opt/yb'
