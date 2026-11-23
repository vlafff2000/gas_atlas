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

import pandas as pd
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

SEARCH_JOBS: dict[str, dict[str, Any]] = {}      # автоперебор критериев: одно задание на проект, в памяти процесса


def _horizon(body: dict[str, Any]) -> int:
    try:
        h = int(body.get('horizon', 1))
    except (TypeError, ValueError):
        raise ParamError('Горизонт ремонта: целое число лет от 1 до 5.') from None
    if not 1 <= h <= 5:
        raise ParamError('Горизонт ремонта: целое число лет от 1 до 5.')
    return h


def _search_job(pid: str, passport: 'Passport', years: list[int], job: dict[str, Any], horizon: int = 1, line: str | None = None, system: bool = True) -> None:
    """Фоновый поток автоперебора: сначала история (улики на каждую дату), затем сетка вариантов; прерывается флагом ``cancel``."""
    from atlas import passport_assess, passport_blocks, well_search
    try:
        job.update(stage='Собираю улики на историю по всем скважинам')
        keep: dict[str, Any] = {}
        passport.backtest(years, keep, horizon, line if system else None)
        if job['cancel']:
            job.update(state='canceled')
            return
        prep = well_search.prepare(keep['feats'], keep['evidence'], keep['fact'])
        job.update(stage='Прогоняю варианты критериев')

        def progress(done: int, total: int) -> None:
            job.update(done=done, total=total)

        res = well_search.search(prep, passport_assess.thresholds_of(passport.settings), progress, lambda: job['cancel'], system=system, line_label=passport.line_label(line))
        res['tables'] = [_table_json(t) for t in passport_blocks.search_tables(res)]
        job.update(state='canceled' if res['canceled'] else 'done', result=res)
    except Exception as e:                                   # фоновый поток: ошибка должна дойти до экрана, а не пропасть
        log.exception('автоперебор критериев')
        job.update(state='error', error=internal_error_text(e))
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

    def object_pressure(self) -> pd.DataFrame | None:
        """Среднее пластовое объекта по замерной сетке (для депрессии); нет БД давлений — None."""
        from atlas.modules.an_report import object_pressure_of
        try:
            return object_pressure_of(self.projects.data(self.pid))[0]
        except Exception:         # нет БД давлений или нет ГСП в замерах: депрессия просто не считается
            return None

    def card(self, well: str, seasons: list[str] | None = None) -> dict[str, Any]:
        from atlas import passport_card
        names = self.manifest.get('tables', {})
        krs = tuple(self.raw[n] if n in names else None for n in ('krs_works', 'krs_priority'))
        gis = tuple(self.raw[n] if n in names else None for n in ('gis_intervals', 'gis_filling', 'gis_annotations'))
        program = self.raw['gdi_program'] if 'gdi_program' in names else None
        return passport_card.build(self.frames, self.settings, self.mapping(), well, krs, seasons, gis=gis, program=program,
                                   elpro=self.raw['elpro'] if 'elpro' in names else None, pressure=self.object_pressure())

    def candidates(self) -> list[dict[str, Any]]:
        """Сводка по фонду: скважины проекта по убыванию суммы улик (карточки паспорта целиком, считается по запросу)."""
        from atlas import well_backtest
        from atlas import passport_assess
        return well_backtest.candidates({w: self.card(w) for w in self.wells()}, passport_assess.weights_of(self.settings))

    def line_options(self) -> list[tuple[str, str]]:
        """Ряды давления магистрали, которые есть в загруженной «БД по учету газа»."""
        from atlas import line_pressure
        return line_pressure.options(self.raw['gas_db'] if 'gas_db' in self.manifest.get('tables', {}) else None)

    def line_label(self, key: str | None) -> str:
        from atlas import line_pressure
        got = dict(self.line_options())
        return got.get(key or line_pressure.DEFAULT, '') or ''

    def backtest(self, years: list[int], keep: dict[str, Any] | None = None, horizon: int = 1, line: str | None = None) -> dict[str, Any]:
        """Проверка критериев на истории по всем скважинам проекта: карточки (все сезоны), КР, замеры забоя и низ фильтра/перфорации."""
        from atlas import passport_card, well_backtest
        names = self.manifest.get('tables', {})
        works: dict[str, list[dict[str, Any]]] = {}
        if 'krs_works' in names:
            for w, g in self.raw['krs_works'].groupby(self.raw['krs_works'].well.astype(str)):
                works[w] = [{'year': None if pd.isna(r.year) else int(r.year), 'type': str(r.work_type or '')} for _, r in g.iterrows()]
        cards = {w: self.card(w) for w in self.wells()}
        bottoms = {w: passport_card._well_rows(self.frames, 'bottom', w) for w in cards}
        filters: dict[str, float | None] = {}
        for w in cards:
            cons = passport_card._well_rows(self.frames, 'construction', w)
            hist = []                                 # низ фильтра по каждой конструкции: на дату проверки берётся последняя из бывших до неё
            for d, g in (cons.groupby('date') if not cons.empty else []):
                low = [float(v) for e, v in zip(g.element, g.bottom_m) if passport_card.classify(str(e)) in ('filter', 'perf') and pd.notna(v)]
                if low:
                    hist.append((pd.Timestamp(d), max(low)))
            filters[w] = sorted(hist) or None
        from atlas import line_pressure, passport_assess
        return well_backtest.run(cards, works, bottoms, filters, self.object_pressure(), years, passport_assess.thresholds_of(self.settings),
                                 passport_assess.weights_of(self.settings), keep, horizon,
                                 line_pressure.daily(self.raw['gas_db'] if 'gas_db' in names else None, line))

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

    def assess(request, body):
        """Ручное решение инженера по механизму (уровень и примечание) или его снятие (level = null); хранится в проекте, пересчёт не затирает."""
        from atlas import passport_assess, well_assess
        pid = request.path_params['pid']
        passport = Passport(projects, pid)
        well = passport.well(body.get('well'))
        mech, level = str(body.get('mechanism') or ''), body.get('level')
        if mech not in passport_assess.MECHANISMS or (level is not None and level not in well_assess.LEVELS):
            raise ParamError('Оценка: неизвестный механизм или уровень.')
        cfg = copy.deepcopy(passport.manifest.get('settings', {}))
        mine = cfg.setdefault('well_assess', {}).setdefault(well, {})
        if level is None:
            mine.pop(mech, None)
        else:
            mine[mech] = {'level': level, 'note': str(body.get('note') or '')[:COMMENT_LIMIT]}
        saved = projects._commit(pid, cfg, body.get('revision'), 'Решение инженера по оценке скважины')
        return projects.summary(saved)

    def backtest(request, body):
        """Проверка критериев на истории: улики на 1 января каждого года против фактических КР этого года."""
        from atlas import passport_blocks
        years = sorted({int(y) for y in body.get('years') or [2022, 2023, 2024, 2025]})
        if not years or len(years) > 10 or any(y < 2000 or y > 2100 for y in years):
            raise ParamError('Проверка на истории: годы от 2000 до 2100, не больше десяти.')
        result = Passport(projects, request.path_params['pid']).backtest(years, None, _horizon(body))
        return {**result, 'tables': [_table_json(t) for t in passport_blocks.backtest_tables(result) + passport_blocks.sweep_tables(result.get('sweep') or {})]}

    def search(request, body):
        """Автоперебор критериев вывода в КРС: ``start`` (годы) запускает фоновое задание, ``status`` отдаёт прогресс и итог, ``cancel`` прерывает."""
        import threading
        pid = request.path_params['pid']
        action = body.get('action', 'status')
        job = SEARCH_JOBS.get(pid)
        if action == 'start':
            if job and job['state'] == 'running':
                return {k: v for k, v in job.items() if k != 'cancel'}
            years = [int(y) for y in body.get('years') or [2022, 2023, 2024, 2025]]
            if not 1 <= len(years) <= 10 or any(not 2000 <= y <= 2100 for y in years):
                raise ParamError('Автоперебор: годы от 2000 до 2100, не больше десяти.')
            job = SEARCH_JOBS[pid] = {'state': 'running', 'stage': 'Запуск', 'done': 0, 'total': 0, 'cancel': False}
            threading.Thread(target=_search_job, args=(pid, Passport(projects, pid), years, job, _horizon(body), body.get('line_series') or None, body.get('system', True) is not False), daemon=True).start()
        elif action == 'cancel' and job:
            job['cancel'] = True
        elif not job:
            return {'state': 'idle'}
        return {k: v for k, v in job.items() if k != 'cancel'}

    def operations(request, body):
        """Таблица «механизм → операция»: правки инженера по уровням (strong/weak); пустой текст возвращает умолчание, ``reset`` сбрасывает всё."""
        from atlas import passport_assess
        pid = request.path_params['pid']
        passport = Passport(projects, pid)
        cfg = copy.deepcopy(passport.manifest.get('settings', {}))
        if body.get('reset'):
            cfg.pop('well_operations', None)
        else:
            given = body.get('operations')
            if not isinstance(given, dict) or any(m not in passport_assess.MECHANISMS or not isinstance(v, dict) or set(v) - {'strong', 'weak'} for m, v in given.items()):
                raise ParamError('Таблица операций: ожидается {механизм: {strong, weak}}.')
            mine = {m: {lvl: str(t)[:COMMENT_LIMIT] for lvl, t in v.items() if str(t).strip() and str(t).strip() != passport_assess.DEFAULT_OPERATIONS.get(m, {}).get(lvl)}
                    for m, v in given.items()}
            cfg['well_operations'] = {m: v for m, v in mine.items() if v}
            if not cfg['well_operations']:
                cfg.pop('well_operations')
        saved = projects._commit(pid, cfg, body.get('revision'), 'Таблица «механизм → операция»')
        return projects.summary(saved)

    def summary_export(request, body):
        """Выгрузка сводных таблиц (кандидаты по фонду, проверка на истории) в CSV/XLSX из тех данных, что показаны на экране."""
        from atlas import passport_blocks
        data, kind, fmt = body.get('data') or {}, body.get('kind'), str(body.get('format', 'xlsx'))
        try:
            if kind == 'fund':
                tables = passport_blocks.fund_tables([r for r in data.get('rows') or [] if isinstance(r, dict)])
            elif kind == 'backtest':
                tables = passport_blocks.backtest_tables({k: data.get(k) or [] for k in ('years', 'mechanisms', 'notes')}) + passport_blocks.sweep_tables(data.get('sweep') or {})
            elif kind == 'search':
                tables = passport_blocks.search_tables(data)
            else:
                raise ParamError('Выгрузка: неизвестная сводка.')
            found = next((t for t in tables if t.id == body.get('id')), None)
            if found is None:
                raise ParamError('Таблица не найдена. Составьте сводку заново.')
            content, name, mime = render.table_csv(found) if fmt == 'csv' else render.tables_file([found], found.title)
        except (ValueError, KeyError, TypeError) as e:
            raise ParamError(f'Выгрузка: данные сводки не подходят ({e}).') from None
        return Response(content, media_type=mime, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})

    def thresholds(request, body):
        """Применить пороги из перебора на истории (только по кнопке инженера): число дат выше предела и коэффициент пределов депрессии, пороги ЭЛПРО; ``reset`` — умолчания."""
        from atlas import passport_assess, passport_depression
        pid = request.path_params['pid']
        passport = Passport(projects, pid)
        cfg = copy.deepcopy(passport.manifest.get('settings', {}))
        mine = cfg.setdefault('passport_thresholds', {})

        def number(src: Any, key: str, low: float, high: float) -> float:
            try:
                v = float(src[key])
            except (KeyError, TypeError, ValueError):
                raise ParamError(f'Пороги: нужно число «{key}».') from None
            if not low <= v <= high:
                raise ParamError(f'Пороги: «{key}» должно быть от {low:g} до {high:g}.')
            return v

        if body.get('reset'):
            cfg.pop('passport_thresholds', None)
            cfg.pop('passport_weights', None)
        elif isinstance(body.get('depression'), dict):
            dep = body['depression']
            mine['dep_min_dates'] = number(dep, 'min_dates', 1, 30)
            factor = number(dep, 'factor', 0.3, 3)
            if factor != 1.0:           # коэффициент меняет сами пределы депрессии: они остаются видны и правятся в паспорте
                cfg['depression_limits'] = [{**t, 'limit': round(t['limit'] * factor, 2)} for t in passport_depression.types_of(cfg)]
        elif isinstance(body.get('variant'), dict):          # целиком вариант из автоперебора: пороги депрессии и ЭЛПРО, веса механизмов
            v = body['variant']
            if v.get('dep_on'):
                mine['dep_min_dates'] = number(v, 'dep_min_dates', 1, 30)
                factor = number(v, 'dep_factor', 0.3, 3)
                if factor != 1.0:
                    cfg['depression_limits'] = [{**t, 'limit': round(t['limit'] * factor, 2)} for t in passport_depression.types_of(cfg)]
            if v.get('el_on'):
                mine['elpro_high_share'] = number(v, 'elpro_high_share', 5, 100)
                mine['elpro_drop'] = number(v, 'elpro_drop', -90, -1)
            weights = {'weak': number(v, 'weak', 0, 3)}
            mults = v.get('mults') if isinstance(v.get('mults'), dict) else {}
            weights.update({m: number(mults, m, 0, 5) for m in mults if m in passport_assess.MECHANISMS})
            if not v.get('dep_on'):
                weights['depression'] = 0.0
            if not v.get('el_on'):
                weights['throttle'] = 0.0
            cfg['passport_weights'] = weights
        elif isinstance(body.get('elpro'), dict):
            mine['elpro_high_share'] = number(body['elpro'], 'high_share', 5, 100)
            mine['elpro_drop'] = number(body['elpro'], 'drop', -90, -1)
        else:
            raise ParamError('Пороги: ожидаются depression, elpro или reset.')
        saved = projects._commit(pid, cfg, body.get('revision'), 'Пороги улик паспорта (перебор на истории)')
        return projects.summary(saved)

    def line_series(request, body):
        """Какие ряды давления магистрали есть в «БД по учету газа» проекта (для выбора ряда в автопереборе) и какой по умолчанию."""
        from atlas import line_pressure
        rows = Passport(projects, request.path_params['pid']).line_options()
        return {'options': [{'key': k, 'label': label} for k, label in rows], 'default': line_pressure.DEFAULT}

    def fund(request, body):
        """Сводка по фонду «кандидаты в КРС»: скважины по убыванию суммы улик с причинами и подсказкой операции."""
        from atlas import passport_blocks
        rows = Passport(projects, request.path_params['pid']).candidates()
        return {'rows': rows, 'tables': [_table_json(t) for t in passport_blocks.fund_tables(rows)]}

    def depression(request, body):
        """Пределы депрессии по типам забоя (``types``) для проекта или тип забоя скважины (``well`` + ``type``; null — вернуть авто-тип)."""
        from atlas import passport_depression
        pid = request.path_params['pid']
        passport = Passport(projects, pid)
        cfg = copy.deepcopy(passport.manifest.get('settings', {}))
        if body.get('types') is not None:
            types = passport_depression.types_of({'depression_limits': body['types']})
            if len(types) != len(body['types']) or any(t['limit'] <= 0 for t in types) or len({t['key'] for t in types}) != len(types):
                raise ParamError('Пределы депрессии: нужны уникальные ключи и положительные числа.')
            cfg['depression_limits'] = types
        else:
            well = passport.well(body.get('well'))
            kind = body.get('type')
            if kind is not None and kind not in {t['key'] for t in passport_depression.types_of(cfg)}:
                raise ParamError('Неизвестный тип забоя.')
            mine = cfg.setdefault('well_depression_type', {})
            if kind is None:
                mine.pop(well, None)
            else:
                mine[well] = kind
        saved = projects._commit(pid, cfg, body.get('revision'), 'Пределы депрессии паспорта')
        return projects.summary(saved)

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
        Route('/api/projects/{pid}/passport/assess', E(assess), methods=['POST']),
        Route('/api/projects/{pid}/passport/backtest', E(backtest), methods=['POST']),
        Route('/api/projects/{pid}/passport/search', E(search), methods=['POST']),
        Route('/api/projects/{pid}/passport/line_series', E(line_series), methods=['POST']),
        Route('/api/projects/{pid}/passport/operations', E(operations), methods=['POST']),
        Route('/api/projects/{pid}/passport/summary_export', E(summary_export), methods=['POST']),
        Route('/api/projects/{pid}/passport/thresholds', E(thresholds), methods=['POST']),
        Route('/api/projects/{pid}/passport/fund', E(fund), methods=['POST']),
        Route('/api/projects/{pid}/passport/depression', E(depression), methods=['POST']),
        Route('/api/projects/{pid}/passport/pdf', E(pdf), methods=['POST']),
    ]
