"""«Паспорт скважины»: выбор скважины, разделов и периодов, комментарий инженера и PDF.

Паспорт строит тот же код 5.8: ``atlas.engine.core.reporting.build`` (графики и таблицы разделов) и
``atlas.engine.core.documents.passport_pdf``; файл сохраняется в выгрузки проекта (``store.save_export``), комментарий —
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
from .modules._production import visible_periods
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from atlas.engine.core.config import DEFAULT_SETTINGS, MODULES, ordered

from . import chart_view, passport_blocks, render
from .contract import MissingData, ParamError, _chart_json, _table_json
from .api_projects import internal_error_text
from .projects import Conflict, Projects

log = logging.getLogger(__name__)
KINDS = (('withdrawal', 'Отбор'), ('injection', 'Закачка'))
COMMENT_LIMIT = 20000
# Разделы, которые 5.8 умеет строить по скважине. Остальные наборы проекта (ГГХ, ЭЛПРО, ГИС, межколонные и т. д.) без колонки «скважина»
# или без отчёта по скважине: в паспорт не входят (раньше они ломали PDF: 'DataFrame' object has no attribute 'well').
PASSPORT_SECTIONS = ('production', 'histograms', 'gdi', 'response', 'operations', 'water', 'bottom', 'construction', 'well_dashboard')


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
            return _error(500, internal_error_text())
        return out if isinstance(out, Response) else JSONResponse(out)
    return handler


class Passport:
    """Данные страницы 5.8 «Паспорт скважины» для одного проекта."""

    def __init__(self, projects: Projects, pid: str):
        from atlas.engine.core.performance import Frames
        self.projects, self.pid = projects, pid
        self.manifest = projects.manifest(pid)
        self.settings = {**DEFAULT_SETTINGS, **self.manifest.get('settings', {})}
        cache = projects._cache(pid, self.manifest)          # тот же performance.Project, что у 5.8
        self.raw = Frames(cache)                              # как raw_frames в app/main.py
        self.frames = Frames(cache, self.settings)            # как frames: с исключёнными точками

    def wells(self) -> list[str]:
        return ordered({w for d in self.raw.values() if 'well' in d for w in d.well.unique()})

    def sections(self) -> list[str]:
        return [x for x in self.frames if x in PASSPORT_SECTIONS and x in MODULES and 'well' in self.frames[x].columns]

    def scope(self, flt: Any) -> list[str]:
        """Скважины проекта после фильтра (группы и скважины пересекаются, как во вкладках); без фильтра — все."""
        from atlas import well_filter
        wells = self.wells()
        keep = well_filter.keep_set(self.projects.data(self.pid), well_filter.clean(flt))
        return wells if keep is None else [w for w in wells if w in keep]

    def periods(self) -> dict[str, list[str]]:
        if 'production' not in self.frames:
            return {}
        from atlas.engine.modules import production
        d = production.periods_for(self.frames['production'], self.settings)
        return {kind: [str(p) for p in visible_periods(ordered(d.loc[d.kind.eq(kind), 'period']), self.settings)] for kind, _ in KINDS}

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

    def card(self, well: str, seasons: list[str] | None = None) -> dict[str, Any]:
        from atlas import passport_card
        names = self.manifest.get('tables', {})
        krs = tuple(self.raw[n] if n in names else None for n in ('krs_works', 'krs_priority'))
        return passport_card.build(self.frames, self.settings, self.mapping(), well, krs, seasons)

    def build(self, well: str, sections: list[str], periods: dict[str, list[str]], comment: str, card: dict[str, Any] | None = None):
        from atlas.engine.core import reporting
        from atlas.engine.core.documents import passport_pdf
        from atlas.engine.core.export import safe_name
        options = self.options(well, sections, periods)
        figures, tables = reporting.build(self.frames, self.mapping(), self.settings, options, self.raw)
        content = passport_pdf(self.manifest['name'], well, figures, tables, self.settings, comment, card=card)
        path = self.projects.store.save_export(self.pid, 'Паспорт_скважины_' + safe_name(well) + '.pdf', content,
                                               options)
        return content, path

    def archive(self, wells: list[str], sections: list[str], periods: dict[str, list[str]], with_card: bool,
                seasons: list[str] | None = None) -> Response:
        """Паспорта нескольких скважин: PDF на каждую в одном ZIP; комментарий у каждой скважины свой, из проекта."""
        import io
        import zipfile
        from atlas.engine.core.export import safe_name
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for well in wells:
                text = str(self.settings.get('well_comments', {}).get(well, ''))[:COMMENT_LIMIT]
                content, _path = self.build(well, sections, periods, text, self.card(well, seasons) if with_card else None)
                zf.writestr('Паспорт_скважины_' + safe_name(well) + '.pdf', content)
        data = buf.getvalue()
        path = self.projects.store.save_export(self.pid, f'Паспорта_скважин_{len(wells)}.zip', data,
                                               {'wells': wells, 'sections': sections, 'periods': periods, 'seasons': seasons})
        return Response(data, media_type='application/zip',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(path.name)}"})


def _seasons(value: Any) -> list[str] | None:
    """Выбранные сезоны паспорта (подписи); пусто — все."""
    if value in (None, '', []):
        return None
    if not isinstance(value, list):
        raise ParamError('Сезоны паспорта: ожидается список подписей.')
    return [str(v) for v in value]


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
        try:
            flt = json.loads(request.query_params.get('filter') or 'null')
        except ValueError:
            raise ParamError('Фильтр скважин: ожидаются списки групп и скважин') from None
        shown = passport.scope(flt)
        well = passport.well(request.query_params.get('well') or (shown[0] if shown else None))
        periods = passport.periods()
        sections = passport.sections()
        mapping = passport.mapping()
        return {
            'wells': wells, 'shown': shown, 'groups': {w: mapping.get(w, {}).get('group', '') for w in wells}, 'well': well,
            'sections': [{'value': s, 'label': MODULES.get(s, s)} for s in sections],
            'periods': {kind: {'label': label, 'options': periods[kind], 'default': periods[kind][-2:]}
                        for kind, label in KINDS if kind in periods},
            'comment': passport.settings.get('well_comments', {}).get(well, ''),
            'revision': passport.manifest.get('revision'),
        }

    def card(request, body):
        passport = Passport(projects, request.path_params['pid'])
        well = passport.well(request.query_params.get('well'))
        try:
            seasons = _seasons(json.loads(request.query_params.get('seasons') or 'null'))
        except ValueError:
            raise ParamError('Сезоны паспорта: ожидается список подписей.') from None
        card = passport.card(well, seasons)
        charts, tables = passport_blocks.blocks(card)       # графики и таблицы — в общем контракте, экран рисует их общим ядром
        return {**card, 'charts': [_chart_json(c, thin=False) for c in charts], 'tables': [_table_json(t) for t in tables]}

    def export(request, body):
        """Выгрузка графика или таблицы паспорта тем же кодом, что у модулей (PNG/SVG/PDF/XLSX/CSV)."""
        passport = Passport(projects, request.path_params['pid'])
        charts, tables = passport_blocks.blocks(passport.card(passport.well(body.get('well')), _seasons(body.get('seasons'))))
        fmt = str(body.get('format', 'png'))
        try:
            if body.get('target') == 'table':
                found = next((t for t in tables if t.id == body.get('id')), None)
                if found is None:
                    raise ParamError('Таблица не найдена. Обновите паспорт.')
                content, name, mime = render.table_csv(found) if fmt == 'csv' else render.tables_file([found], found.title)
            else:
                found = next((c for c in charts if c.id == body.get('id')), None)
                if found is None:
                    raise ParamError('График не найден. Обновите паспорт.')
                if fmt != 'csv':
                    found = chart_view.apply_view(found, body.get('view'))
                content, name, mime = render.chart_file(found, fmt, int(body.get('dpi', 300)), body.get('font'), body.get('font_size'))
        except ValueError as e:
            raise ParamError(str(e)) from None
        return Response(content, media_type=mime, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})

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
        chosen = body.get('wells')
        if chosen is not None:
            if not isinstance(chosen, list) or not chosen:
                raise ParamError('Список скважин для паспорта пуст.')
            known = set(passport.wells())
            bad = [str(w) for w in chosen if str(w) not in known]
            if bad:
                raise ParamError('Нет таких скважин в данных проекта: ' + ', '.join(bad[:5]))
            chosen = list(dict.fromkeys(str(w) for w in chosen))
        available = passport.sections()
        sections = body.get('sections', available)
        with_card = body.get('card') is True              # по умолчанию паспорт как в 5.8; карточку включает страница
        if not isinstance(sections, list) or (not sections and not with_card):
            raise ParamError('Выберите хотя бы один раздел паспорта.')
        bad = [str(s) for s in sections if s not in available]
        if bad:
            raise ParamError('Нет таких разделов в проекте: ' + ', '.join(bad))
        periods = _periods(body.get('periods'), passport.periods())
        text = body.get('comment')
        if text is None:
            text = passport.settings.get('well_comments', {}).get(well, '')
        if chosen and len(chosen) > 1:
            return passport.archive(chosen, [str(s) for s in sections], periods, with_card, _seasons(body.get('seasons')))
        if chosen:
            well = chosen[0]
            if body.get('comment') is None:
                text = passport.settings.get('well_comments', {}).get(well, '')
        card = passport.card(well, _seasons(body.get('seasons'))) if with_card else None
        content, path = passport.build(well, [str(s) for s in sections], periods, str(text)[:COMMENT_LIMIT], card)
        return Response(content, media_type='application/pdf',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(path.name)}"})

    E = _endpoint
    return [
        Route('/api/projects/{pid}/passport', E(info)),
        Route('/api/projects/{pid}/passport/card', E(card)),
        Route('/api/projects/{pid}/passport/export', E(export), methods=['POST']),
        Route('/api/projects/{pid}/passport/comment', E(comment), methods=['POST']),
        Route('/api/projects/{pid}/passport/pdf', E(pdf), methods=['POST']),
    ]
