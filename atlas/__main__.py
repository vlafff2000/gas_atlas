"""Запуск: ``python -m atlas``.

Поднимает ядро на 127.0.0.1 и открывает окно приложения (pywebview). Если pywebview не
установлен или указан ``--browser`` — открывает обычный браузер. Ядро и интерфейс об оболочке
не знают.
"""
from __future__ import annotations

import argparse
import logging
import socket
import threading
import time
import webbrowser

import uvicorn

from . import VERSION
from .api import create_app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_ready(port: int, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog='atlas', description=f'Газовый атлас {VERSION}')
    parser.add_argument('--port', type=int, default=0, help='порт (по умолчанию свободный)')
    parser.add_argument('--browser', action='store_true', help='открыть в браузере, а не в окне')
    parser.add_argument('--server', action='store_true', help='только сервер, ничего не открывать')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    port = args.port or (8765 if args.server else free_port())
    url = f'http://127.0.0.1:{port}/'
    server = uvicorn.Server(uvicorn.Config(create_app(), host='127.0.0.1', port=port, log_level='warning'))

    if args.server:
        print(f'Газовый атлас {VERSION}: {url}')
        server.run()
        return

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if not wait_ready(port):
        raise SystemExit('Сервер не запустился, см. журнал выше')

    webview = None
    if not args.browser:
        try:
            import webview  # pywebview
        except ImportError:
            print('pywebview не установлен — открываю в браузере (pip install pywebview)')
    if webview is not None:
        try:  # выгрузка графиков и таблиц из окна приложения (pywebview 5+)
            webview.settings['ALLOW_DOWNLOADS'] = True
        except (AttributeError, TypeError):
            pass
        webview.create_window('Газовый атлас', url, width=1440, height=900, min_size=(1024, 680))
        webview.start()
        server.should_exit = True
    else:
        webbrowser.open(url)
        print(f'Газовый атлас {VERSION}: {url}  (остановка — Ctrl+C)')
        try:
            thread.join()
        except KeyboardInterrupt:
            server.should_exit = True


if __name__ == '__main__':
    main()
