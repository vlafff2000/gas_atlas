"""HTTP раздела «Импорт данных». Логика — ``atlas/imports.py``.

| Запрос | Что делает |
|---|---|
| `POST /api/import/files?name=файл.xlsx` (тело — байты файла) | принять файл, ответ: `token`, листы |
| `GET /api/import/options` | типы таблиц, поля сопоставления, роли листов давлений |
| `POST /api/import/inspect` `{view, mode, files}` | простой режим: таблица всех листов; подробный — листы файлов |
| `POST /api/import/sheet` `{token, sheet, encoding, delimiter, mode, header, module, pressure, fonds}` | редактор листа |
| `POST /api/import/profile` `{…, spec, remember}` | «Запомнить для файлов с такой же шапкой» |
| `GET /api/import/templates`, `GET /api/import/templates/{name}` | шаблоны и примеры |
| `POST /api/projects/{pid}/import/check` | «Проверить файлы» |
| `POST /api/projects/{pid}/import/apply` `{pending, policy, accept}` | «Применить загрузку» |
| `POST /api/projects/{pid}/import/table` `{pending, table, format}` | журнал проверки / таблица CSV, XLSX |
| `POST /api/projects/{pid}/import/pressure` `{files, choices, overrides, duplicate}` | данные давлений: роли листов и сопоставление |
| `POST /api/projects/{pid}/import/pressure/apply` `{pending, mode}` | сохранить данные давлений |
"""
from __future__ import annotations

import json
import logging
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import render
from .api import Failure, error
from .contract import MissingData, ParamError
from .imports import Imports
from .projects import Conflict

log = logging.getLogger(__name__)
MAX_UPLOAD = 512 * 1024 ** 2


def _wrap(work, raw_body=False):
    async def handler(request: Request):
        try:
            raw = await request.body() if request.method == 'POST' else b''
            if raw_body:
                body = raw
            else:
                body = json.loads(raw) if raw.strip() else {}
                if not isinstance(body, dict):
                    return error(400, 'Тело запроса должно быть объектом JSON')
        except ValueError:
            return error(400, 'Тело запроса должно быть JSON')
        try:
            out = await run_in_threadpool(work, request, body)
        except Failure as e:
            return error(e.status, str(e))
        except ParamError as e:
            return error(400, str(e))
        except (MissingData, Conflict) as e:
            return error(409, str(e))
        except KeyError as e:
            return error(404, str(e.args[0]) if e.args else 'Не найдено')
        except Exception:
            log.exception('Сбой запроса %s', request.url.path)
            return error(500, 'Внутренняя ошибка. Подробности в журнале.')
        return out if isinstance(out, Response) else JSONResponse(out)
    return handler


def attachment(content: bytes, name: str, mime: str) -> Response:
    return Response(content, media_type=mime, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})


def routes(projects) -> list[Route]:
    imports = Imports(projects)

    def upload(request, body: bytes):
        if len(body) > MAX_UPLOAD:
            raise Failure(413, 'Размер файла превышает 512 МБ.')
        return imports.upload(request.query_params.get('name', 'Файл'), body)

    def template(request, body):
        name = request.path_params['name']
        content = imports.template(name)
        mime = 'text/csv' if name.endswith('.csv') else 'text/plain' if name.endswith('.txt') else \
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        return attachment(content, name, mime)

    def table(request, body):
        t = imports.pending_table(request.path_params['pid'], body.get('pending'), body.get('table'))
        if body.get('format') == 'csv':
            content, name, mime = render.table_csv(t)
        else:
            content, name, mime = render.tables_file([t], t.title)
        return attachment(content, name, mime)

    pid = lambda request: request.path_params['pid']   # noqa: E731
    return [
        Route('/api/import/files', _wrap(upload, raw_body=True), methods=['POST']),
        Route('/api/import/options', _wrap(lambda r, b: imports.options())),
        Route('/api/import/inspect', _wrap(lambda r, b: imports.inspect(b)), methods=['POST']),
        Route('/api/import/sheet', _wrap(lambda r, b: imports.sheet(b)), methods=['POST']),
        Route('/api/import/profile', _wrap(lambda r, b: imports.profile(b)), methods=['POST']),
        Route('/api/import/templates', _wrap(lambda r, b: imports.templates())),
        Route('/api/import/templates/{name}', _wrap(template)),
        Route('/api/projects/{pid}/import/check', _wrap(lambda r, b: imports.check(pid(r), b)), methods=['POST']),
        Route('/api/projects/{pid}/import/apply', _wrap(lambda r, b: imports.apply(pid(r), b)), methods=['POST']),
        Route('/api/projects/{pid}/import/table', _wrap(table), methods=['POST']),
        Route('/api/projects/{pid}/import/pressure', _wrap(lambda r, b: imports.pressure_inspect(pid(r), b)), methods=['POST']),
        Route('/api/projects/{pid}/import/pressure/apply', _wrap(lambda r, b: imports.pressure_apply(pid(r), b)),
              methods=['POST']),
    ]
