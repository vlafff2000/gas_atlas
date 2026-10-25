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
        return projects.assign_well_funds(request.path_params['pid'], body.get('changes') or {}, body.get('revision'))

    return [Route('/api/projects/{pid}/well-fund', _endpoint(get)),
            Route('/api/projects/{pid}/well-fund', _endpoint(post), methods=['POST'])]
