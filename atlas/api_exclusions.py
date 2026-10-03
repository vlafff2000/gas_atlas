"""API «Истории фильтра»: восстановление состояния исключений из записи журнала (как в 5.8).

``POST /api/projects/{pid}/exclusions/state`` ``{at, side, revision}`` — ``at`` — «Дата» записи журнала,
``side`` — ``before`` | ``after``. Пишет действие «Восстановление фильтра» с подробностями ``filter_details``,
ровно как ``render_extra('История фильтра')`` в ``app/ui/extras.py``: 5.8 видит результат и может его отменить так же.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.history import filter_details

from .contract import ParamError
from .modules._journal import filter_records
from .projects import Conflict, Projects

log = logging.getLogger(__name__)
SIDES = {'before': 'before_exclusions', 'after': 'after_exclusions'}


def restore_state(projects: Projects, pid: str, at: str, side: str, expected: int | None = None) -> dict[str, Any]:
    if side not in SIDES:
        raise ParamError('Состояние для восстановления: before или after')
    m = projects.manifest(pid)
    record = next((details for row, details in filter_records(projects.store.history(pid)) if str(row['Дата']) == str(at)),
                  None)
    if record is None:
        raise KeyError('Запись истории фильтра не найдена. Обновите страницу.')
    settings = m.get('settings', {})
    target = record.get(SIDES[side], {})
    cfg = copy.deepcopy(settings)
    cfg['excluded_points'] = copy.deepcopy(target)
    old = settings.get('excluded_points', {})
    added = [v for k, v in target.items() if k not in old]
    removed = [k for k in old if k not in target]
    details = filter_details(projects._raw_frames(pid, m), settings, cfg, added, removed)
    saved = projects._commit(pid, cfg, expected, 'Восстановление фильтра', details)
    return {'added': len(added), 'removed': len(removed), 'excluded': len(target), 'revision': saved['revision']}


def routes(projects: Projects) -> list[Route]:
    def endpoint(work):
        async def handler(request: Request):
            try:
                raw = await request.body()
                body = json.loads(raw) if raw.strip() else {}
            except ValueError:
                return JSONResponse({'error': 'Тело запроса должно быть JSON'}, status_code=400)
            if not isinstance(body, dict):
                return JSONResponse({'error': 'Тело запроса должно быть объектом JSON'}, status_code=400)
            try:
                return JSONResponse(await run_in_threadpool(work, request, body))
            except ParamError as e:
                return JSONResponse({'error': str(e)}, status_code=400)
            except Conflict as e:
                return JSONResponse({'error': str(e)}, status_code=409)
            except KeyError as e:
                return JSONResponse({'error': str(e.args[0]) if e.args else 'Не найдено'}, status_code=404)
            except Exception:
                log.exception('Сбой запроса %s', request.url.path)
                return JSONResponse({'error': 'Внутренняя ошибка. Подробности в журнале.'}, status_code=500)
        return handler

    def state(request, body):
        revision = body.get('revision')
        try:
            revision = None if revision is None else int(revision)
        except (TypeError, ValueError):
            raise ParamError('Ревизия должна быть числом') from None
        return restore_state(projects, request.path_params['pid'], str(body.get('at', '')), str(body.get('side', '')),
                             revision)

    return [Route('/api/projects/{pid}/exclusions/state', endpoint(state), methods=['POST'])]
