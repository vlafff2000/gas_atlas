"""Пресеты скважин: `GET /api/projects/{pid}/well-presets` (группы, фонды, опорная сетка и пользовательские),
`POST /api/well-presets` {name, wells}, `DELETE /api/well-presets/{id}` и `GET /api/projects/{pid}/well-filter`
(фильтр скважин проекта: сколько скважин остаётся; сам фильтр сохраняется настройкой ``well_filter``).

Логика — ``atlas/well_sets.py``; пресеты проекта считаются из данных проекта, пользовательские лежат в ~/.pxg.
"""
from __future__ import annotations

from starlette.routing import Route

from . import well_funds
from .api_passport import _endpoint
from .contract import ParamError
from .engine.core.config import natural_key
from .modules.an_report import reference_pressure
from .projects import Projects
from . import well_filter, well_sets


def project_presets(projects: Projects, pid: str) -> list[dict]:
    """Пресеты проекта: по группам, по фондам и опорная замерная сетка. Пустые пресеты не показываются."""
    data = projects.data(pid)
    mapping = data.mapping
    groups: dict[str, list[str]] = {}
    for well, value in mapping.items():
        group = value.get('group', '') if isinstance(value, dict) else ''
        if group and group != 'Без группы':
            groups.setdefault(group, []).append(str(well))
    out = [{'id': f'group:{name}', 'kind': 'group', 'label': name, 'wells': sorted(wells, key=natural_key)}
           for name, wells in sorted(groups.items(), key=lambda item: natural_key(item[0]))]
    by_fund: dict[str, list[str]] = {}
    for row in projects.well_funds(pid)['wells']:
        if row.get('fund'):
            by_fund.setdefault(row['fund'], []).append(str(row['well']))
    labels = dict(well_funds.FUNDS)
    out += [{'id': f'fund:{fund}', 'kind': 'fund', 'label': labels.get(fund, fund), 'wells': sorted(wells, key=natural_key)}
            for fund, wells in by_fund.items()]
    grid, _label = reference_pressure(data, 'auto')
    if grid is not None and not grid.empty:
        out.append({'id': 'grid', 'kind': 'grid', 'label': 'Замерная сетка (опорная)',
                    'wells': sorted(grid.well.astype(str).unique(), key=natural_key)})
    return [p for p in out if p['wells']]


def routes(projects: Projects) -> list[Route]:
    def get(request, body):
        pid = request.path_params['pid']
        return {'presets': project_presets(projects, pid) + well_sets.user_presets()}

    def create(request, body):
        try:
            well_sets.add_user_preset(body.get('name', ''), body.get('wells') or [])
        except ValueError as e:
            raise ParamError(str(e))
        return {'presets': project_presets_all(projects, body.get('project'))}

    def remove(request, body):
        well_sets.remove_user_preset(request.path_params['preset'])
        return {'presets': well_sets.user_presets()}

    def filter_status(request, body):
        return well_filter.status(projects.data(request.path_params['pid']))

    return [Route('/api/projects/{pid}/well-presets', _endpoint(get)),
            Route('/api/projects/{pid}/well-filter', _endpoint(filter_status)),
            Route('/api/well-presets', _endpoint(create), methods=['POST']),
            Route('/api/well-presets/{preset}', _endpoint(remove), methods=['DELETE'])]


def project_presets_all(projects: Projects, pid: str | None) -> list[dict]:
    return (project_presets(projects, pid) if pid else []) + well_sets.user_presets()
