"""«Фонды скважин»: `GET /api/projects/{pid}/well-fund` (таблица с подсказками) и `POST …` `{changes: {скважина: фонд|auto}, revision}`.

Логика — ``atlas/well_funds.py``; хранится в настройках проекта, общая для всех программ.
"""
from __future__ import annotations

from .api_passport import _endpoint
from starlette.routing import Route

from .projects import Projects


def routes(projects: Projects) -> list[Route]:
    def get(request, body):
        return projects.well_funds(request.path_params['pid'])

    def post(request, body):
        pid = request.path_params['pid']
        if body.get('horizons'):
            return projects.assign_well_horizons(pid, body['horizons'], body.get('revision'))
        return projects.assign_well_funds(pid, body.get('changes') or {}, body.get('revision'))

    async def upload(request):
        from starlette.concurrency import run_in_threadpool
        from starlette.responses import JSONResponse
        from .contract import ParamError
        content = await request.body()
        try:
            rev = request.query_params.get('revision')
            out = await run_in_threadpool(projects.import_well_funds, request.path_params['pid'], content,
                                          request.query_params.get('name', 'fonds.xlsx'), int(rev) if rev else None)
        except ParamError as e:
            return JSONResponse({'error': str(e)}, status_code=400)
        return JSONResponse(out)

    return [Route('/api/projects/{pid}/well-fund', _endpoint(get)),
            Route('/api/projects/{pid}/well-fund', _endpoint(post), methods=['POST']),
            Route('/api/projects/{pid}/well-fund/import', upload, methods=['POST'])]
