"""Пресеты скважин проекта: `GET /api/projects/{pid}/well-presets` (группы, фонды, опорная сетка и пользовательские),
`POST /api/projects/{pid}/well-presets` {name, wells}, `DELETE /api/projects/{pid}/well-presets/{id}` и
`POST /api/projects/{pid}/well-presets/import-legacy` (перенос пресетов из прежней общей папки ~/.pxg).

Логика — ``atlas/well_sets.py``; пресеты проекта считаются из данных проекта, пользовательские лежат в папке проекта.
"""
from __future__ import annotations

from starlette.routing import Route

from . import well_funds
from .api_passport import _endpoint
from .contract import ParamError
from .engine.core.config import natural_key
from .modules.an_report import reference_pressure
from .projects import Projects
from . import well_sets


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
    def folder(pid: str):
        projects.manifest(pid)                      # несуществующий проект — 404, а не новая папка
        return projects.store.path(pid)

    def get(request, body):
        pid = request.path_params['pid']
        return {'presets': project_presets(projects, pid) + well_sets.user_presets(folder(pid)),
                'legacy': well_sets.legacy_count()}

    def create(request, body):
        pid = request.path_params['pid']
        try:
            well_sets.add_user_preset(folder(pid), body.get('name', ''), body.get('wells') or [])
        except ValueError as e:
            raise ParamError(str(e))
        return {'presets': project_presets(projects, pid) + well_sets.user_presets(folder(pid))}

    def remove(request, body):
        pid = request.path_params['pid']
        well_sets.remove_user_preset(folder(pid), request.path_params['preset'])
        return {'presets': project_presets(projects, pid) + well_sets.user_presets(folder(pid))}

    def import_legacy(request, body):
        pid = request.path_params['pid']
        well_sets.import_legacy(folder(pid))
        return {'presets': project_presets(projects, pid) + well_sets.user_presets(folder(pid)),
                'legacy': well_sets.legacy_count()}

    return [Route('/api/projects/{pid}/well-presets', _endpoint(get), methods=['GET']),
            Route('/api/projects/{pid}/well-presets', _endpoint(create), methods=['POST']),
            Route('/api/projects/{pid}/well-presets/{preset}', _endpoint(remove), methods=['DELETE']),
            Route('/api/projects/{pid}/well-presets/import-legacy', _endpoint(import_legacy), methods=['POST'])]
