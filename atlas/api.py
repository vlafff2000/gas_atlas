"""HTTP/JSON API ядра. Интерфейс (atlas/web/dist) раздаётся этим же сервером."""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from collections import OrderedDict
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import quote, urlsplit

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import VERSION, api_exclusions, chart_view, legend_order, registry, render, season_format, thinning, well_filter
from . import second_window
from . import api_builder, api_corrected, api_export, api_projects, export_any, export_charts, group_colors, group_paint
from .contract import DataRangeError, MissingData, ParamError, Result, _chart_json, _series_json, _table_json
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


def _port_open(url: str) -> bool:
    parts = urlsplit(url)
    try:
        with socket.create_connection((parts.hostname, parts.port or 80), timeout=0.5):
            return True
    except (OSError, ValueError):
        return False


def _maps_note(text: str) -> HTMLResponse:
    """Страница-пояснение вместо перехода в Карты, когда перейти нельзя."""
    return HTMLResponse(f'<!doctype html><meta charset="utf-8"><title>Карты</title>'
                        f'<p style="font-family:sans-serif;margin:24px">{text}</p>')


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
    projects = projects or Projects(warm=True)
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
            except DataRangeError as e:
                return error(422, str(e))
            except MissingData as e:
                return error(409, str(e))
            except Conflict as e:
                return error(409, str(e))
            except KeyError as e:
                return error(404, str(e.args[0]) if e.args else 'Не найдено')
            except Exception:
                log.exception('Сбой запроса %s', request.url.path)
                return error(500, api_projects.internal_error_text())
            return out if isinstance(out, Response) else JSONResponse(out)
        return handler

    def module_of(request):
        return registry.get(request.path_params['mid'])

    def compute(module, pid, raw_params, full=False):
        """``full`` — результат без прореживания самого модуля (выгрузка графика, окно увеличения); кэшируется отдельно."""
        flt, raw_params = well_filter.split(raw_params)       # фильтр скважин вкладки приходит среди её параметров
        params = module.spec.coerce(raw_params)
        data = projects.select(pid, module.spec.needs, module.spec.optional, flt)
        key = (module.spec.id, pid, data.revision, json.dumps([params, flt], sort_keys=True, ensure_ascii=False, default=str), full)
        cached = results.get(key)
        if cached is None:
            started = time.perf_counter()
            with thinning.full_resolution() if full else nullcontext():
                result: Result = group_paint.paint(season_format.relabel(module.run(data, params), season_format.format_of(data.settings)))
            cached = (result, round((time.perf_counter() - started) * 1000, 1))
            results.put(key, cached)
        return (legend_order.apply(cached[0], legend_order.mode_of(data.settings)), cached[1]), params, data

    # --- справочные ---
    def health(request, body):
        return {'version': VERSION, 'modules': len(registry.modules())}

    def list_modules(request, body):
        return [m.spec.to_json() for m in registry.modules().values()]

    # --- проекты ---
    def list_projects(request, body):
        return projects.list()

    def app_links(request, body):
        """Адрес Карт: переменная PXG_MAPS_URL (её передаёт меню pxg_hub); пусто — кнопки на карту не будет."""
        return {'maps_url': os.environ.get('PXG_MAPS_URL', '').strip()}

    def maps_open(request):
        """«Показать на карте»: переход в Карты на скважине (#/map?well=…); если Карт нет — понятная страница."""
        well = request.query_params.get('well', '').strip()
        if not well.isdigit():
            return error(400, 'Номер скважины — целое число')
        base = os.environ.get('PXG_MAPS_URL', '').strip().rstrip('/')
        if not base:
            return _maps_note('Адрес Карт не задан. Откройте Атлас через меню запуска (pxg_hub), тогда кнопка «Показать на карте» заработает.')
        if not _port_open(base):
            return _maps_note('Карты не запущены. Запустите «Карты» в меню запуска и нажмите «Показать на карте» ещё раз.')
        return RedirectResponse(f'{base}/#/map?well={well}', status_code=302)

    def project_wells(request, body):
        return {'wells': projects.wells(request.path_params['pid'])}

    def project_groups(request, body):
        mapping = projects.data(request.path_params['pid']).mapping
        return {'groups': group_colors.sort_groups(v['group'] for v in mapping.values() if v.get('group'))}

    def create_demo(request, body):
        rows = body.get('rows') or {}
        if not isinstance(rows, dict) or not all(isinstance(v, int) and 0 <= v <= 5_000_000 for v in rows.values()):
            raise ParamError('Объёмы демо — целые числа строк от 0 до 5 000 000')
        if rows.get('production') == 0:
            raise ParamError('Нужна хотя бы одна строка отбора и закачки')
        return JSONResponse({'id': projects.create_demo(large=bool(body.get('large')), rows=rows)}, status_code=201)

    def project(request, body):
        return projects.summary(projects.manifest(request.path_params['pid']))

    def settings(request, body):
        return projects.update_settings(request.path_params['pid'], body.get('values') or {}, body.get('revision'))

    def options(request, body):
        try:
            dataset = DatasetKind(request.query_params.get('dataset', ''))
        except ValueError:
            raise Failure(400, 'Неизвестный вид данных') from None
        try:
            flt = well_filter.clean(json.loads(request.query_params.get('filter') or 'null'))
        except (ValueError, AttributeError):
            raise Failure(400, 'Фильтр скважин: ожидаются списки групп и скважин') from None
        return projects.options(request.path_params['pid'], dataset, request.query_params.get('column', ''), flt)

    def exclusions(request, body):
        try:
            dataset = DatasetKind(body.get('dataset', ''))
        except ValueError:
            raise Failure(400, 'Неизвестный вид данных') from None
        return projects.change_exclusions(request.path_params['pid'], dataset, body.get('add') or [],
                                          body.get('remove') or [], body.get('reason') or 'Исключено вручную',
                                          body.get('metric'))

    def groups(request, body):
        return projects.assign_groups(request.path_params['pid'], body.get('changes') or {},
                                      body.get('action') or 'Назначение групп', body.get('revision'))

    def object_categories(request, body):
        return projects.assign_object_categories(request.path_params['pid'], body.get('changes') or {},
                                                 body.get('revision'))

    def well_categories(request, body):
        return projects.assign_well_categories(request.path_params['pid'], body.get('changes') or {}, body.get('revision'))

    def gis_comments(request, body):
        return projects.assign_gis_comments(request.path_params['pid'], body.get('changes') or {}, body.get('revision'))

    def wf_status(request, body):
        return projects.assign_wf_status(request.path_params['pid'], body.get('changes') or {}, body.get('revision'))

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
        flt, raw = well_filter.split(body.get('params'))
        params = module.spec.coerce(raw)
        data = projects.select(pid, module.spec.needs, module.spec.optional, flt)
        return projects.save_state(pid, module, params, data, panel)

    def param_options(request, body):
        """Варианты зависимого списка при текущих значениях остальных параметров."""
        module = module_of(request)
        name = body.get('param')
        param = next((p for p in module.spec.params if p.name == name and p.dynamic), None)
        if param is None:
            raise Failure(404, 'Нет такого списка')
        flt, raw = well_filter.split(body.get('params'))
        data = projects.select(body.get('project'), module.spec.needs, module.spec.optional, flt)
        current = {p.name: p.coerce(raw.get(p.name)) for p in module.spec.params
                   if p.name in param.depends}
        return module.options(name, data, current)

    def module_catalog(request, body):
        """Справочник модуля по данным проекта: ``Module.catalog`` (поля конструктора графиков)."""
        module = module_of(request)
        data = projects.select(body.get('project'), module.spec.needs, module.spec.optional)
        return module.catalog(data)

    # --- расчёт и экспорт ---
    def run(request, body):
        module = module_of(request)
        thin = body.get('thin') is not False       # настройка «Прореживать точки» выключена — все точки
        (result, elapsed), _, data = compute(module, body.get('project'), body.get('params'), full=not thin)
        return {**result.to_json(thin=thin, defer=True), 'elapsed_ms': elapsed, 'revision': data.revision}

    def chart_of(module, body, full):
        (result, _), _, data = compute(module, body.get('project'), body.get('params'), full)
        chart = next((c for c in result.charts if c.id == body.get('chart', body.get('id'))), None)
        if chart is None:
            raise Failure(404, 'График не найден. Обновите расчет.')
        return chart, data

    def full_chart(module, body):
        """График со всеми точками: если модуль сам прореживал серии для экрана, расчёт повторяется без прореживания."""
        chart, data = chart_of(module, body, False)
        if any(s.total > len(s.x) for s in chart.series):
            chart, data = chart_of(module, body, True)
        return chart, data

    def window(request, body):
        """Точки линий в видимом окне оси X (увеличение): окно по возможности отдаётся целиком."""
        module = module_of(request)
        try:
            x0, x1 = float(body['x0']), float(body['x1'])
        except (KeyError, TypeError, ValueError):
            raise Failure(400, 'Нужны границы окна x0 и x1') from None
        chart, data = full_chart(module, body)
        if body.get('revision') not in (None, data.revision):
            raise Failure(409, 'Расчёт устарел. Обновите график.')
        picked = thinning.window_indices(chart, min(x0, x1), max(x0, x1), raw=bool(body.get('raw')))
        return {'chart': chart.id, 'revision': data.revision,
                'series': {str(i): {**_series_json(chart.series[i], keep), 'window': inside} for i, (keep, inside) in picked.items()}}

    def table(request, body):
        """Большая свёрнутая таблица целиком (в расчёте она отправляется только по запросу)."""
        module = module_of(request)
        (result, _), _, _ = compute(module, body.get('project'), body.get('params'))
        found = next((t for t in result.tables if t.id == body.get('id')), None)
        if found is None:
            raise Failure(404, 'Таблица не найдена. Обновите расчет.')
        return _table_json(found)

    def export(request, body):
        module = module_of(request)
        target = body.get('target')
        if target == 'tables':
            (result, _), _, _ = compute(module, body.get('project'), body.get('params'))
        if target == 'charts':      # все графики результата: ZIP из PNG или лист-плитка
            (result, _), _, _ = compute(module, body.get('project'), body.get('params'), True)
            if not result.charts:
                raise Failure(404, 'Графиков нет. Обновите расчет.')
            try:
                if body.get('layout') == 'sheet':
                    content, name, mime = export_charts.sheet(result.charts, module.spec.title, body.get('cols', 2))
                else:
                    content, name, mime = export_charts.archive(result.charts, module.spec.title)
            except ValueError as e:
                raise Failure(400, str(e)) from None
        elif target == 'chart':
            chart, _ = full_chart(module, body)
            if body.get('format') != 'csv':
                chart = chart_view.apply_view(chart, body.get('view'))     # вид с экрана: оформление рядов, границы осей, масштаб, легенда
            try:
                dpi = int(body.get('dpi', 300))
            except (TypeError, ValueError):
                raise Failure(400, 'DPI должен быть числом') from None
            try:
                content, name, mime = render.chart_file(chart, str(body.get('format', 'png')), dpi,
                                                          body.get('font'), body.get('font_size'))
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
        second_window.route(),
        Route('/api/health', E(health)),
        Route('/api/modules', E(list_modules)),
        Route('/api/modules/{mid}/run', E(run), methods=['POST']),
        Route('/api/modules/{mid}/export', E(export), methods=['POST']),
        Route('/api/modules/{mid}/window', E(window), methods=['POST']),
        Route('/api/modules/{mid}/table', E(table), methods=['POST']),
        Route('/api/modules/{mid}/options', E(param_options), methods=['POST']),
        Route('/api/modules/{mid}/catalog', E(module_catalog), methods=['POST']),
        Route('/api/projects', E(list_projects)),
        Route('/api/projects/demo', E(create_demo), methods=['POST']),
        Route('/api/projects/{pid}', E(project)),
        Route('/api/projects/{pid}/settings', E(settings), methods=['PATCH']),
        Route('/api/projects/{pid}/options', E(options)),
        Route('/api/projects/{pid}/wells', E(project_wells)),
        Route('/api/projects/{pid}/group-list', E(project_groups)),
        Route('/api/app/links', E(app_links)),
        Route('/api/app/maps', maps_open),
        Route('/api/projects/{pid}/exclusions', E(exclusions), methods=['POST']),
        Route('/api/projects/{pid}/exclusions/undo', E(undo), methods=['POST']),
        Route('/api/projects/{pid}/groups', E(groups), methods=['POST']),
        Route('/api/projects/{pid}/object-categories', E(object_categories), methods=['POST']),
        Route('/api/projects/{pid}/well-categories', E(well_categories), methods=['POST']),
        Route('/api/projects/{pid}/gis-comments', E(gis_comments), methods=['POST']),
        Route('/api/projects/{pid}/wf-status', E(wf_status), methods=['POST']),
        Route('/api/projects/{pid}/state/{mid}', E(state), methods=['GET', 'POST']),
        *group_colors.routes(),     # ручные цвета групп, общие для всех программ
        *__import__('atlas.fs_browse', fromlist=['routes']).routes(),   # проводник: список папок, последняя папка
        *api_builder.routes(projects, E),   # библиотека макетов конструктора, Word одного графика
        *api_exclusions.routes(projects),
        *api_corrected.routes(projects),   # «Исправленная БД» вкладки
        *api_projects.routes(projects), *api_export.routes(projects),   # «Проекты», «Настройки», «Экспорт»
        *export_any.routes(projects, E, compute),   # «Экспорт» → «Любой график»
        *__import__('atlas.api_passport', fromlist=['routes']).routes(projects),   # «Паспорт скважины»
        *__import__('atlas.api_fund', fromlist=['routes']).routes(projects),   # «Фонды скважин»
        *__import__('atlas.api_well_sets', fromlist=['routes']).routes(projects),   # пресеты скважин, список из буфера
        *__import__('atlas.api_import', fromlist=['routes']).routes(projects),   # раздел «Импорт данных»
        *__import__('atlas.project_folder', fromlist=['routes']).routes(projects),   # «Папка проекта»: файлы, роли, загрузка
        *__import__('atlas.runlog', fromlist=['routes']).routes(),   # лог: сведения, пакет для отправки
        Route('/api/{rest:path}', api_not_found, methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE']),
        Route('/', index),
    ]
    if (DIST / 'assets').exists():
        routes.append(Mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets'))
    return Starlette(routes=routes, middleware=[Middleware(__import__('atlas.runlog', fromlist=['RequestLog']).RequestLog), Middleware(GZipMiddleware, minimum_size=1024)])
