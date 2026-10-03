"""HTTP/JSON API ядра. Интерфейс (atlas/web/dist) раздаётся этим же сервером."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import VERSION, api_exclusions, registry, render
from . import api_export, api_projects
from .contract import MissingData, ParamError, Result
from .domain import DatasetKind
from .projects import Conflict, Projects

log = logging.getLogger(__name__)
DIST = Path(__file__).parent / 'web' / 'dist'


class Failure(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status)


class Results:
    """Последние результаты: экспорт графика или таблицы не пересчитывает модуль."""

    def __init__(self, size=24):
        self.size, self.items, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]

    def put(self, key, value):
        with self.lock:
            self.items[key] = value
            while len(self.items) > self.size:
                self.items.popitem(last=False)


def create_app(projects: Projects | None = None) -> Starlette:
    projects = projects or Projects()
    results = Results()

    def endpoint(work):
        """Обёртка: тяжёлая работа в потоке, ошибки — в понятный JSON."""
        async def handler(request: Request):
            try:
                raw = await request.body() if request.method in ('POST', 'PATCH') else b''
                body = json.loads(raw) if raw.strip() else {}
            except ValueError:
                return error(400, 'Тело запроса должно быть JSON')
            if not isinstance(body, dict):
                return error(400, 'Тело запроса должно быть объектом JSON')
            try:
                out = await run_in_threadpool(work, request, body)
            except Failure as e:
                return error(e.status, str(e))
            except ParamError as e:
                return error(400, str(e))
            except MissingData as e:
                return error(409, str(e))
            except Conflict as e:
                return error(409, str(e))
            except KeyError as e:
                return error(404, str(e.args[0]) if e.args else 'Не найдено')
            except Exception:
                log.exception('Сбой запроса %s', request.url.path)
                return error(500, 'Внутренняя ошибка. Подробности в журнале.')
            return out if isinstance(out, Response) else JSONResponse(out)
        return handler

    def module_of(request):
        return registry.get(request.path_params['mid'])

    def compute(module, pid, raw_params):
        params = module.spec.coerce(raw_params)
        data = projects.select(pid, module.spec.needs, module.spec.optional)
        key = (module.spec.id, pid, data.revision, json.dumps(params, sort_keys=True, ensure_ascii=False, default=str))
        cached = results.get(key)
        if cached is None:
            started = time.perf_counter()
            result: Result = module.run(data, params)
            cached = (result, round((time.perf_counter() - started) * 1000, 1))
            results.put(key, cached)
        return cached, params, data

    # --- справочные ---
    def health(request, body):
        return {'version': VERSION, 'modules': len(registry.modules())}

    def list_modules(request, body):
        return [m.spec.to_json() for m in registry.modules().values()]

    # --- проекты ---
    def list_projects(request, body):
        return projects.list()

    def create_demo(request, body):
        return JSONResponse({'id': projects.create_demo()}, status_code=201)

    def project(request, body):
        return projects.summary(projects.manifest(request.path_params['pid']))

    def settings(request, body):
        return projects.update_settings(request.path_params['pid'], body.get('values') or {}, body.get('revision'))

    def options(request, body):
        try:
            dataset = DatasetKind(request.query_params.get('dataset', ''))
        except ValueError:
            raise Failure(400, 'Неизвестный вид данных') from None
        return projects.options(request.path_params['pid'], dataset, request.query_params.get('column', ''))

    def exclusions(request, body):
        try:
            dataset = DatasetKind(body.get('dataset', ''))
        except ValueError:
            raise Failure(400, 'Неизвестный вид данных') from None
        return projects.change_exclusions(request.path_params['pid'], dataset, body.get('add') or [],
                                          body.get('remove') or [], body.get('reason') or 'Исключено вручную',
                                          body.get('metric'))

    def undo(request, body):
        return projects.undo_exclusion(request.path_params['pid'])

    def panel_of(request, body):
        try:
            return int(request.query_params.get('panel', body.get('panel', 0)))
        except (TypeError, ValueError):
            raise Failure(400, 'Номер панели должен быть числом') from None

    def state(request, body):
        module, pid, panel = module_of(request), request.path_params['pid'], panel_of(request, body)
        if request.method == 'GET':
            return projects.saved_state(pid, module, panel)
        params = module.spec.coerce(body.get('params'))
        data = projects.select(pid, module.spec.needs, module.spec.optional)
        return projects.save_state(pid, module, params, data, panel)

    def param_options(request, body):
        """Варианты зависимого списка при текущих значениях остальных параметров."""
        module = module_of(request)
        name = body.get('param')
        param = next((p for p in module.spec.params if p.name == name and p.dynamic), None)
        if param is None:
            raise Failure(404, 'Нет такого списка')
        data = projects.select(body.get('project'), module.spec.needs, module.spec.optional)
        current = {p.name: p.coerce(body.get('params', {}).get(p.name)) for p in module.spec.params
                   if p.name in param.depends}
        return module.options(name, data, current)

    # --- расчёт и экспорт ---
    def run(request, body):
        module = module_of(request)
        (result, elapsed), _, data = compute(module, body.get('project'), body.get('params'))
        return {**result.to_json(), 'elapsed_ms': elapsed, 'revision': data.revision}

    def export(request, body):
        module = module_of(request)
        (result, _), _, _ = compute(module, body.get('project'), body.get('params'))
        target = body.get('target')
        if target == 'chart':
            chart = next((c for c in result.charts if c.id == body.get('id')), None)
            if chart is None:
                raise Failure(404, 'График не найден. Обновите расчет.')
            try:
                dpi = int(body.get('dpi', 300))
            except (TypeError, ValueError):
                raise Failure(400, 'DPI должен быть числом') from None
            try:
                content, name, mime = render.chart_file(chart, str(body.get('format', 'png')), dpi)
            except ValueError as e:
                raise Failure(400, str(e)) from None
        elif target == 'tables':
            wanted = body.get('id')
            tables = [t for t in result.tables if wanted in (None, t.id)]
            if not tables:
                raise Failure(404, 'Таблица не найдена. Обновите расчет.')
            if body.get('format') == 'csv':
                if len(tables) != 1:
                    raise Failure(400, 'CSV выгружается по одной таблице')
                content, name, mime = render.table_csv(tables[0])
            else:
                content, name, mime = render.tables_file(tables, tables[0].title if wanted else module.spec.title)
        else:
            raise Failure(400, 'Что выгрузить: chart или tables')
        return Response(content, media_type=mime,
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})

    async def index(request: Request):
        page = DIST / 'index.html'
        if page.exists():
            return FileResponse(page)
        return PlainTextResponse('Интерфейс не собран: выполните "npm run build" в папке web/.', status_code=503)

    async def api_not_found(request: Request):
        return error(404, 'Нет такого адреса API')

    E = endpoint
    routes = [
        Route('/api/health', E(health)),
        Route('/api/modules', E(list_modules)),
        Route('/api/modules/{mid}/run', E(run), methods=['POST']),
        Route('/api/modules/{mid}/export', E(export), methods=['POST']),
        Route('/api/modules/{mid}/options', E(param_options), methods=['POST']),
        Route('/api/projects', E(list_projects)),
        Route('/api/projects/demo', E(create_demo), methods=['POST']),
        Route('/api/projects/{pid}', E(project)),
        Route('/api/projects/{pid}/settings', E(settings), methods=['PATCH']),
        Route('/api/projects/{pid}/options', E(options)),
        Route('/api/projects/{pid}/exclusions', E(exclusions), methods=['POST']),
        Route('/api/projects/{pid}/exclusions/undo', E(undo), methods=['POST']),
        Route('/api/projects/{pid}/state/{mid}', E(state), methods=['GET', 'POST']),
        *api_exclusions.routes(projects),
        *api_projects.routes(projects), *api_export.routes(projects),   # «Проекты», «Настройки», «Экспорт»
        *__import__('atlas.api_passport', fromlist=['routes']).routes(projects),   # «Паспорт скважины»
        Route('/api/{rest:path}', api_not_found, methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE']),
        Route('/', index),
    ]
    if (DIST / 'assets').exists():
        routes.append(Mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets'))
    return Starlette(routes=routes)
