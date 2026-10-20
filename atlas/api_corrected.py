"""«Исправленная БД» вкладки: ``GET /api/projects/{pid}/corrected-db?module=<id>`` — книга XLSX с данными вкладки
после исключений (см. ``atlas.corrected_db``). Один запрос — одна вкладка; наборы берутся из её обязательных и
необязательных данных."""
from __future__ import annotations

import logging
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from atlas.engine.core.export import safe_name

from . import corrected_db, registry
from .contract import ParamError
from .projects import Projects

log = logging.getLogger(__name__)
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def build(projects: Projects, pid: str, module_id: str) -> tuple[bytes, str]:
    spec = registry.get(module_id).spec
    data = projects.data(pid)
    kinds = [*spec.needs, *spec.optional]
    if not any(k in data.raw for k in kinds):
        raise ParamError(f'На вкладке «{spec.title}» нет данных проекта для выгрузки.')
    content = corrected_db.build(data.raw, data.excluded, kinds)
    name = f'{safe_name(data.project.name)}_{safe_name(spec.title)}_исправленная_БД.xlsx'
    return content, name


def routes(projects: Projects) -> list[Route]:
    async def corrected(request: Request):
        pid = request.path_params['pid']
        module_id = request.query_params.get('module', '')
        if not module_id:
            return JSONResponse({'error': 'Укажите вкладку (module)'}, status_code=400)
        try:
            content, name = await run_in_threadpool(build, projects, pid, module_id)
        except ParamError as e:
            return JSONResponse({'error': str(e)}, status_code=400)
        except KeyError as e:
            return JSONResponse({'error': str(e.args[0]) if e.args else 'Не найдено'}, status_code=404)
        return Response(content, media_type=XLSX,
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})

    return [Route('/api/projects/{pid}/corrected-db', corrected, methods=['GET'])]
