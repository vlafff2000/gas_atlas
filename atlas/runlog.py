"""Лог Атласа для отправки: сводка окружения, запись действий и пакет (zip) с логом.

Файл ``atlas.log`` ведёт ``api_projects.attach_log`` (``logs/`` рядом с программой или ``GAS_ATLAS_LOGS``). Здесь — то, что
добавляет единый подход программ ПХГ (как ``pxg_core/runlog.py`` в all_scripts): версия сборки, ОС и ядра, запросы, время этапов,
пакет для отправки. Содержимое данных в лог не попадает, домашняя папка в путях заменяется на «~». Лог только информирует.
"""
from __future__ import annotations

import contextlib
import logging
import os
import platform
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from . import VERSION
from .engine.core.config import ROOT

log = logging.getLogger('atlas.runlog')
BUNDLE_TAIL = 2 * 1024 ** 2
_HOME = os.path.expanduser('~')
_QUIET = ('/api/log', '/api/fs', '/api/projects')      # чтение и опрос: в лог только медленное и ошибки


def _log_dir() -> Path:
    from .api_projects import LOG_DIR
    return Path(LOG_DIR)


def _clean(text: str) -> str:
    return text.replace(_HOME, '~') if len(_HOME) > 1 else text


class CleanPaths(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _clean(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = _clean(logging.Formatter().formatException(record.exc_info))
        return True


def _version() -> str:
    try:
        out = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True,
                             timeout=3, check=False)
        if out.returncode == 0 and out.stdout.strip():
            return f'{VERSION}, git {out.stdout.strip()}'
    except (OSError, subprocess.SubprocessError):
        pass
    for name in ('VERSION', 'VERSION.txt', 'BUILD_MANIFEST.json'):
        with contextlib.suppress(OSError):
            first = (Path(ROOT) / name).read_text(encoding='utf8').strip().splitlines()
            if first and name != 'BUILD_MANIFEST.json':
                return f'{VERSION}, {name}: {first[0][:80]}'
    return VERSION


def environment_text() -> str:
    from importlib import metadata
    libs = []
    for name in ('numpy', 'pandas', 'scipy', 'starlette', 'uvicorn', 'pywebview', 'matplotlib', 'openpyxl'):
        with contextlib.suppress(Exception):
            libs.append(f'{name} {metadata.version(name)}')
    return '\n'.join([
        'Версия сборки: ' + _version(),
        f'Python: {platform.python_version()}',
        f'ОС: {platform.system()} {platform.release()}',
        f'Ядер: {os.cpu_count() or "?"}; PXG_WORKERS: {os.environ.get("PXG_WORKERS") or "не задано"}',
        'Папка логов: ' + _clean(str(_log_dir())),
        'Библиотеки: ' + ', '.join(libs),
    ])


def announce() -> None:
    log.info('=== запуск «Газовый атлас» ===\n%s', environment_text())


def action(text: str, **info: Any) -> None:
    log.info('действие: %s%s', text, ''.join(f'; {k}={v}' for k, v in info.items()))


@contextlib.contextmanager
def timed(label: str, **info: Any) -> Iterator[dict]:
    """Замер этапа: ``with timed('импорт', файл=name) as t: ...; t['строк'] = n``."""
    extra: dict = {}
    start = time.perf_counter()
    try:
        yield extra
    except Exception:
        log.exception('этап «%s» завершился ошибкой за %.2f с', label, time.perf_counter() - start)
        raise
    log.info('этап «%s»: %.2f с%s', label, time.perf_counter() - start, ''.join(f'; {k}={v}' for k, v in {**info, **extra}.items()))


class RequestLog:
    """ASGI-прослойка: запросы, меняющие данные, медленные (>1 с) и ошибки; без тел запросов."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/api/'):
            return await self.app(scope, receive, send)
        method, path = scope['method'], scope['path']
        status = [0]

        async def wrapped(message):
            if message['type'] == 'http.response.start':
                status[0] = message['status']
            await send(message)

        start = time.perf_counter()
        try:
            await self.app(scope, receive, wrapped)
        except Exception:
            log.exception('%s %s: необработанная ошибка', method, path)
            raise
        took = time.perf_counter() - start
        quiet = method == 'GET' and any(path.startswith(p) for p in _QUIET)
        if status[0] >= 500:
            level = logging.ERROR
        elif status[0] >= 400:
            level = logging.WARNING
        elif took > 1 or (method != 'GET' and not quiet):
            level = logging.INFO
        else:
            return
        log.log(level, '%s %s -> %s, %.2f с', method, path, status[0], took)


def make_bundle() -> Path:
    d = _log_dir()
    out_dir = d / 'send'
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in sorted(out_dir.glob('*.zip'))[:-4]:
        with contextlib.suppress(OSError):
            old.unlink()
    path = out_dir / f'atlas_log_{datetime.now():%Y%m%d_%H%M%S}.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('environment.txt', environment_text() + f'\nСобрано: {datetime.now().isoformat(timespec="seconds")}\n')
        for f in sorted(d.glob('*.log*')):
            if f.is_file():
                size = f.stat().st_size
                with open(f, 'rb') as fh:
                    if size > BUNDLE_TAIL:
                        fh.seek(size - BUNDLE_TAIL)
                    z.writestr(f.name, fh.read())
    log.info('собран пакет для отправки: %s', _clean(str(path)))
    return path


async def info(request: Request):
    d = _log_dir()
    files = [{'name': f.name, 'size': f.stat().st_size} for f in sorted(d.glob('*.log*')) if f.is_file()] if d.is_dir() else []
    return JSONResponse({'dir': str(d), 'files': files, 'current': 'atlas.log'})


async def bundle(request: Request):
    try:
        path = make_bundle()
    except OSError as e:
        return JSONResponse({'error': f'Не удалось собрать пакет: {e}'}, status_code=500)
    return JSONResponse({'name': path.name, 'path': str(path), 'size': path.stat().st_size, 'url': '/api/log/bundle/' + path.name})


async def bundle_file(request: Request):
    path = _log_dir() / 'send' / Path(request.path_params['name']).name
    if not path.is_file() or path.suffix != '.zip':
        return JSONResponse({'error': 'Пакет не найден.'}, status_code=404)
    return FileResponse(path, media_type='application/zip', filename=path.name)


async def open_dir(request: Request):
    d = _log_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith('win'):
            os.startfile(str(d))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(d)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return JSONResponse({'error': f'Не удалось открыть папку: {e}', 'dir': str(d)}, status_code=501)
    return JSONResponse({'ok': True, 'dir': str(d)})


def routes() -> list[Route]:
    return [
        Route('/api/log/info', info),
        Route('/api/log/bundle', bundle, methods=['POST']),
        Route('/api/log/bundle/{name}', bundle_file),
        Route('/api/log/open-folder', open_dir, methods=['POST']),
    ]
