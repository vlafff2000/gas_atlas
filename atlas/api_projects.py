"""Разделы «Проекты» и «Настройки» 5.8 в API ядра 6: создание, переименование, копия, резервная копия
и восстановление, сохранённые выгрузки, журнал ошибок, состав меню.

Хранилище — то же ``app/core/storage.Store``: архивы, имена файлов и записи журнала совпадают с 5.8.
"""
from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.core.config import ROOT
from app.core.export import safe_name
from app.ui import navigation

from .projects import Conflict, Projects

log = logging.getLogger(__name__)
LOG_DIR = Path(os.environ.get('GAS_ATLAS_LOGS', ROOT / 'logs'))
MAX_UPLOAD = 3 * 1024 ** 3          # как предел распаковки резервной копии в 5.8


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status)


class Failure(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def attach_log(directory: Path = None) -> Path:
    """Ошибки ядра 6 — в файл рядом с журналом 5.8 (``logs/atlas.log``), чтобы их можно было скачать."""
    directory = Path(directory or LOG_DIR)
    path = (directory / 'atlas.log').resolve()
    logger = logging.getLogger('atlas')
    if not any(getattr(h, 'baseFilename', None) == str(path) for h in logger.handlers):
        for stale in [h for h in logger.handlers if getattr(h, '_atlas_log', False)]:
            logger.removeHandler(stale)
            stale.close()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(str(path), maxBytes=2 * 1024 ** 2, backupCount=3, encoding='utf8', delay=True)
        except OSError:
            return path
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        handler.setLevel(logging.WARNING)
        handler._atlas_log = True
        logger.addHandler(handler)
    return path


def log_bytes(directory: Path = None) -> bytes | None:
    """Журнал ошибок: 5.8 (``gas_atlas.log``) и 6 (``atlas.log``) одним текстом."""
    directory = Path(directory or LOG_DIR)
    parts = []
    for name, title in (('gas_atlas.log', 'Газовый атлас 5.8'), ('atlas.log', 'Газовый атлас 6')):
        path = directory / name
        if path.exists():
            parts.append(f'===== {title}: {name} =====\n'.encode('utf8') + path.read_bytes())
    return b'\n'.join(parts) if parts else None


def attachment(content: bytes, name: str, mime: str) -> Response:
    return Response(content, media_type=mime,
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})


def preview(content: bytes, name: str) -> dict:
    """Как ``preview_project`` 5.8: что внутри архива или старого проекта, до восстановления."""
    if name.lower().endswith('.json'):
        obj = json.loads(content)
        if not isinstance(obj, dict):
            raise ValueError('Ожидается проект версии 1 в формате .gas.json.')
        records = obj.get('records') if isinstance(obj.get('records'), list) else []
        head = pd.DataFrame(records[:30]).astype(str) if records else pd.DataFrame()
        return {'kind': 'legacy', 'info': {k: obj.get(k) for k in ('name', 'version', 'settings')}, 'count': len(records),
                'columns': list(head.columns), 'rows': head.values.tolist()}
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        info = z.getinfo('manifest.json')
        if info.file_size > 10 * 1024 ** 2:
            raise ValueError('Слишком большой manifest.json.')
        obj = json.loads(z.read(info))
        files = [{'name': i.filename, 'bytes': i.file_size} for i in z.infolist() if not i.is_dir()]
    return {'kind': 'backup', 'info': {k: obj.get(k) for k in ('name', 'version', 'tables')}, 'count': len(files),
            'files': files[:100]}


def saved_exports(projects: Projects, pid: str) -> list[dict]:
    projects.manifest(pid)
    out = []
    for p in projects.store.exports(pid):
        stat = p.stat()
        out.append({'name': p.name, 'bytes': stat.st_size,
                    'modified': pd.Timestamp(stat.st_mtime, unit='s', tz='UTC').isoformat()})
    return out


def export_path(projects: Projects, pid: str, name: str) -> Path:
    """Только файл из списка сохранённых выгрузок проекта (никаких путей извне)."""
    projects.manifest(pid)
    for p in projects.store.exports(pid):
        if p.name == name:
            return p
    raise Failure(404, 'Файл не найден. Обновите список сохраненных выгрузок.')


def details(projects: Projects, pid: str) -> dict:
    """Всё, что показывают «Проекты» и «Настройки» 5.8 для текущего проекта."""
    m = projects.manifest(pid)
    settings = m.get('settings', {})
    return {
        **projects.summary(m),
        'version': m.get('version'),
        'panels': settings.get('panels', {}),
        'pages': list(navigation.PAGES),
        'default_pages': list(navigation.DEFAULT),
        'visible_pages': [navigation.ALIASES.get(p, p) for p in settings.get('visible_pages', navigation.DEFAULT)],
        'exports': saved_exports(projects, pid),
        'log': any((LOG_DIR / n).exists() for n in ('gas_atlas.log', 'atlas.log')),
    }


def routes(projects: Projects) -> list[Route]:
    attach_log()

    def endpoint(work, raw_body=False):
        async def handler(request: Request):
            try:
                if raw_body:
                    body = await request.body()
                    if len(body) > MAX_UPLOAD:
                        return error(400, 'Файл больше 3 ГБ')
                else:
                    raw = await request.body() if request.method in ('POST', 'PATCH') else b''
                    body = json.loads(raw) if raw.strip() else {}
                    if not isinstance(body, dict):
                        return error(400, 'Тело запроса должно быть объектом JSON')
            except ValueError:
                return error(400, 'Тело запроса должно быть JSON')
            try:
                out = await run_in_threadpool(work, request, body)
            except Failure as e:
                return error(e.status, str(e))
            except Conflict as e:
                return error(409, str(e))
            except KeyError as e:
                return error(404, str(e.args[0]) if e.args else 'Не найдено')
            except (ValueError, zipfile.BadZipFile, json.JSONDecodeError) as e:
                # Ошибки Store (пустое имя, неверный архив, ревизия) уже сформулированы для пользователя.
                if 'изменен' in str(e):
                    return error(409, 'Проект изменён в другом окне (например, в версии 5.8). Обновите данные и повторите.')
                log.warning('Отклонён запрос %s: %s', request.url.path, e)
                return error(400, str(e) if not isinstance(e, zipfile.BadZipFile) else 'Файл не является ZIP-архивом')
            except Exception:
                log.exception('Сбой запроса %s', request.url.path)
                return error(500, 'Внутренняя ошибка. Подробности в журнале.')
            return out if isinstance(out, Response) else JSONResponse(out)
        return handler

    def revision(body):
        value = body.get('revision')
        return int(value) if isinstance(value, (int, float)) else None

    def create(request, body):
        """«Новый проект» из боковой панели 5.8."""
        pid = projects.store.create(str(body.get('name') or ''))
        return JSONResponse(projects.summary(projects.manifest(pid)), status_code=201)

    def info(request, body):
        return details(projects, request.path_params['pid'])

    def rename(request, body):
        pid = request.path_params['pid']
        projects.manifest(pid)
        projects.store.rename(pid, str(body.get('name') or ''), revision(body))
        return projects.summary(projects.manifest(pid))

    def copy(request, body):
        """«Создать копию проекта с данными и настройками» — как в 5.8: восстановление из полной копии."""
        pid = request.path_params['pid']
        projects.manifest(pid)
        new = projects.store.restore(projects.store.backup(pid, True))
        return JSONResponse(projects.summary(projects.manifest(new)), status_code=201)

    def backup(request, body):
        pid = request.path_params['pid']
        m = projects.manifest(pid)
        originals = request.query_params.get('originals', '1') not in ('0', 'false', 'no')
        content = projects.store.backup(pid, originals)
        return attachment(content, safe_name(m['name']) + '.gasatlas.zip', 'application/zip')

    def upload_name(request) -> str:
        name = request.query_params.get('name', '')
        if not name.lower().endswith(('.zip', '.json')):
            raise Failure(400, 'Выберите резервную копию .zip или старый проект .gas.json')
        return name

    def restore_preview(request, content):
        name = upload_name(request)
        return preview(content, name)

    def restore(request, content):
        """Резервная копия → новый проект «… (копия)»; старый .gas.json → перенос (как в 5.8)."""
        name = upload_name(request)
        if not content:
            raise Failure(400, 'Файл пуст')
        pid = projects.store.import_legacy(content) if name.lower().endswith('.json') else projects.store.restore(content)
        return JSONResponse(projects.summary(projects.manifest(pid)), status_code=201)

    def exports(request, body):
        return saved_exports(projects, request.path_params['pid'])

    def export_file(request, body):
        path = export_path(projects, request.path_params['pid'], request.path_params['name'])
        mime = {'.zip': 'application/zip', '.pdf': 'application/pdf',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}.get(
            path.suffix.lower(), 'application/octet-stream')
        return attachment(path.read_bytes(), path.name, mime)

    def journal(request, body):
        content = log_bytes()
        if content is None:
            raise Failure(404, 'Журнал ошибок пока пуст.')
        return attachment(content, 'gas_atlas.log', 'text/plain; charset=utf-8')

    E = endpoint
    return [
        Route('/api/projects', E(create), methods=['POST']),
        Route('/api/projects/restore', E(restore, raw_body=True), methods=['POST']),
        Route('/api/projects/restore/preview', E(restore_preview, raw_body=True), methods=['POST']),
        Route('/api/log', E(journal)),
        Route('/api/projects/{pid}/details', E(info)),
        Route('/api/projects/{pid}/rename', E(rename), methods=['POST']),
        Route('/api/projects/{pid}/copy', E(copy), methods=['POST']),
        Route('/api/projects/{pid}/backup', E(backup)),
        Route('/api/projects/{pid}/exports', E(exports)),
        Route('/api/projects/{pid}/exports/{name}', E(export_file)),
    ]
