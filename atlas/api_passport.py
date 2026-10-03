"""«Паспорт скважины»: выбор скважины, разделов и периодов, комментарий инженера и PDF.

Паспорт строит тот же код 5.8: ``app.core.reporting.build`` (графики и таблицы разделов) и
``app.core.documents.passport_pdf``; файл сохраняется в выгрузки проекта (``store.save_export``), комментарий —
в ``settings.well_comments`` действием «Комментарий инженера». Здесь только выбор данных и HTTP.
Перечень функций раздела — docs/parity/passport.md.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.core.config import DEFAULT_SETTINGS, MODULES, ordered

from .contract import MissingData, ParamError
from .projects import Conflict, Projects

log = logging.getLogger(__name__)
KINDS = (('withdrawal', 'Отбор'), ('injection', 'Закачка'))
COMMENT_LIMIT = 20000


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status)


def _endpoint(work):
    """Как ``endpoint`` в atlas/api.py: работа в потоке, ошибки — понятный JSON."""
    async def handler(request: Request):
        try:
            raw = await request.body() if request.method == 'POST' else b''
            body = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return _error(400, 'Тело запроса должно быть JSON')
        if not isinstance(body, dict):
            return _error(400, 'Тело запроса должно быть объектом JSON')
        try:
            out = await run_in_threadpool(work, request, body)
        except ParamError as e:
            return _error(400, str(e))
        except (MissingData, Conflict) as e:
            return _error(409, str(e))
        except KeyError as e:
            return _error(404, str(e.args[0]) if e.args else 'Не найдено')
        except Exception:
            log.exception('Сбой запроса %s', request.url.path)
            return _error(500, 'Внутренняя ошибка. Подробности в журнале.')
        return out if isinstance(out, Response) else JSONResponse(out)
    return handler


class Passport:
    """Данные страницы 5.8 «Паспорт скважины» для одного проекта."""

    def __init__(self, projects: Projects, pid: str):
        from app.core.performance import Frames
        self.projects, self.pid = projects, pid
        self.manifest = projects.manifest(pid)
        self.settings = {**DEFAULT_SETTINGS, **self.manifest.get('settings', {})}
        cache = projects._cache(pid, self.manifest)          # тот же performance.Project, что у 5.8
        self.raw = Frames(cache)                              # как raw_frames в app/main.py
        self.frames = Frames(cache, self.settings)            # как frames: с исключёнными точками

    def wells(self) -> list[str]:
        return ordered({w for d in self.raw.values() if 'well' in d for w in d.well.unique()})

    def sections(self) -> list[str]:
        return [x for x in self.frames if x != 'object_pressure']

    def periods(self) -> dict[str, list[str]]:
        if 'production' not in self.frames:
            return {}
        from app.modules import production
        d = production.periods(self.frames['production'], self.settings['season_start'], self.settings['season_end'])
        return {kind: [str(p) for p in ordered(d.loc[d.kind.eq(kind), 'period'])] for kind, _ in KINDS}

    def well(self, value: Any) -> str:
        wells = self.wells()
        if not wells:
            raise ParamError('Сначала загрузите данные скважин.')
        well = str(value) if value not in (None, '') else wells[0]
        if well not in wells:
            raise ParamError(f'Нет скважины {well} в данных проекта')
        return well

    def options(self, well: str, sections: list[str], periods: dict[str, list[str]]) -> dict[str, Any]:
        """Словарь ``options`` для ``reporting.build`` — как собирает страница 5.8."""
        settings = self.settings
        options: dict[str, Any] = {
            'modules': sections, 'wells': [well], 'apply_exclusions': True, 'style': settings.get('chart_style', {}),
            'gdi': {'wells': [well], 'n': 3, 'show_excluded': True},
            'response': {'wells': [well], 'view': 'combined', 'split': 'well'}}
        if 'production' in sections:
            options['production'] = {'wells': [well], 'periods': periods, 'view': 'mixed', 'split': 'well'}
        return options

    def mapping(self) -> dict[str, dict[str, str]]:
        return self.projects.data(self.pid).mapping

    def build(self, well: str, sections: list[str], periods: dict[str, list[str]], comment: str):
        from app.core import reporting
        from app.core.documents import passport_pdf
        from app.core.export import safe_name
        options = self.options(well, sections, periods)
        figures, tables = reporting.build(self.frames, self.mapping(), self.settings, options, self.raw)
        content = passport_pdf(self.manifest['name'], well, figures, tables, self.settings, comment)
        path = self.projects.store.save_export(self.pid, 'Паспорт_скважины_' + safe_name(well) + '.pdf', content,
                                               options)
        return content, path


def _periods(body_value: Any, available: dict[str, list[str]]) -> dict[str, list[str]]:
    """Периоды паспорта; не заданы — последние два, как по умолчанию в 5.8."""
    out = {}
    for kind, _ in KINDS:
        if kind not in available:
            continue
        chosen = (body_value or {}).get(kind) if isinstance(body_value, dict) else None
        if chosen is None:
            out[kind] = available[kind][-2:]
            continue
        if not isinstance(chosen, list):
            raise ParamError('Периоды паспорта: ожидается список')
        bad = [str(p) for p in chosen if str(p) not in available[kind]]
        if bad:
            raise ParamError('Нет таких периодов: ' + ', '.join(bad[:5]))
        out[kind] = [str(p) for p in chosen]
    return out


def routes(projects: Projects) -> list[Route]:
    def info(request, body):
        passport = Passport(projects, request.path_params['pid'])
        wells = passport.wells()
        if not wells:
            return {'wells': [], 'well': None, 'sections': [], 'periods': {}, 'comment': '',
                    'revision': passport.manifest.get('revision'), 'note': 'Сначала загрузите данные скважин.'}
        well = passport.well(request.query_params.get('well'))
        periods = passport.periods()
        sections = passport.sections()
        return {
            'wells': wells, 'well': well,
            'sections': [{'value': s, 'label': MODULES.get(s, s)} for s in sections],
            'periods': {kind: {'label': label, 'options': periods[kind], 'default': periods[kind][-2:]}
                        for kind, label in KINDS if kind in periods},
            'comment': passport.settings.get('well_comments', {}).get(well, ''),
            'revision': passport.manifest.get('revision'),
        }

    def comment(request, body):
        pid = request.path_params['pid']
        passport = Passport(projects, pid)
        well = passport.well(body.get('well'))
        text = str(body.get('comment') or '')[:COMMENT_LIMIT]
        cfg = copy.deepcopy(passport.manifest.get('settings', {}))
        cfg.setdefault('well_comments', {})[well] = text
        saved = projects._commit(pid, cfg, body.get('revision'), 'Комментарий инженера')
        return {**projects.summary(saved), 'comment': text}

    def pdf(request, body):
        passport = Passport(projects, request.path_params['pid'])
        well = passport.well(body.get('well'))
        available = passport.sections()
        sections = body.get('sections', available)
        if not isinstance(sections, list) or not sections:
            raise ParamError('Выберите хотя бы один раздел паспорта.')
        bad = [str(s) for s in sections if s not in available]
        if bad:
            raise ParamError('Нет таких разделов в проекте: ' + ', '.join(bad))
        periods = _periods(body.get('periods'), passport.periods())
        text = body.get('comment')
        if text is None:
            text = passport.settings.get('well_comments', {}).get(well, '')
        content, path = passport.build(well, [str(s) for s in sections], periods, str(text)[:COMMENT_LIMIT])
        return Response(content, media_type='application/pdf',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(path.name)}"})

    E = _endpoint
    return [
        Route('/api/projects/{pid}/passport', E(info)),
        Route('/api/projects/{pid}/passport/comment', E(comment), methods=['POST']),
        Route('/api/projects/{pid}/passport/pdf', E(pdf), methods=['POST']),
    ]
