"""Раздел «Экспорт» 5.8 в API ядра 6: массовая выгрузка графиков и таблиц (архив ZIP по модулю), отчёт Word,
предпросмотр, шаблоны параметров и «Взять параметры из вкладок просмотра».

Форма экспорта хранит поля под теми же именами, что виджеты 5.8 (``app/ui/export_panel.py``: ``gdi_n``,
``production_periods_withdrawal``, ``caption_template_gdi`` …), поэтому шаблоны экспорта общие у 5.8 и 6.
Перечень графиков, их построение, архивы и Word — код 5.8 без изменений: ``app.core.reporting.plan``,
``app.core.bulk_export.export_plan`` / ``export_word`` / ``bundle_exports``.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import quote

import pandas as pd
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.core import reporting
from app.core.bulk_export import bundle_exports, export_plan, export_word, migrate_preset
from app.core.config import MODULES, VERSION as VERSION_58, ordered
from app.core.documents import DEFAULT_CAPTIONS, grid_pdf, report_docx
from app.core.export import figure_bytes

from . import VERSION
from .contract import Data, ParamError
from .projects import Conflict, Projects

log = logging.getLogger(__name__)

ORDER = ('production', 'histograms', 'gdi', 'response', 'object_pressure', 'well_dashboard',
         'operations', 'water', 'bottom', 'construction', 'pressure_match')
DEFAULT_MODULES = ('production', 'gdi', 'response', 'object_pressure')
STYLE_FIELDS = (('points', 'Экспорт: точки'), ('legend', 'Экспорт: легенда'), ('grid', 'Экспорт: сетка'))
GDI_DASHBOARD = (('n', 'n'), ('orientation', 'orientation'), ('curves', 'curves'), ('db', 'db_curves'),
                 ('crosshair', 'crosshair'), ('excluded', 'show_excluded'), ('seasons', 'seasons'))
# Поля, которые 5.8 кладёт в шаблон экспорта (``export_panel``: «Сохранить шаблон экспорта»).
PRESET_FIELDS = ('modules', 'formats', 'dpi', 'width', 'height', 'font', 'font_size', 'exclusions', 'raw', 'auto')
PRESET_PREFIXES = ('production_', 'histograms_', 'gdi_', 'response_', 'dashboard_', 'pressure_', 'periods_', 'caption_', 'style_', 'pack_')


# Пакет графиков по фонду («Приложение»): режим → (раздел, слово в подписи).
PACK_KINDS = {'withdrawal': ('П4', 'отборе', 'Отбор'), 'injection': ('П5', 'закачке', 'Закачка')}
PACK_TEMPLATE = 'Рисунок {раздел}.{номер} - Производительность скважины №{скважина} при {режим} газа за {годы} гг.'
PACK_FIELDS = ('раздел', 'номер', 'скважина', 'режим', 'годы')
PACK_PER_PAGE = 6
# графиков на листе → (колонок, размер графика в мм): график занимает всю ячейку листа A4 под подписью
PACK_LAYOUTS = {2: (1, (170, 108)), 4: (2, (84, 100)), 6: (2, (84, 68))}
PACK_DPI = 200


class Failure(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status)


# ---------- данные проекта в виде, который ждёт код 5.8 ----------

def frames_of(data: Data, apply_exclusions: bool = True) -> tuple[dict, dict]:
    """(``frames``, ``raw_frames``) как в 5.8: ключи — имена таблиц; без исключений — исходные таблицы
    (эксплуатация — подготовленная, но без исключённых точек, как ``Frames(..., excluded_points={})``)."""
    raw = {k.value: d for k, d in data.raw.items()}
    shown = {k.value: d for k, d in data.items()} if apply_exclusions else dict(raw)
    return shown, raw


def available(raw: Mapping[str, pd.DataFrame]) -> list[str]:
    """Вкладки модулей экспорта — тот же отбор, что в 5.8."""
    return [m for m in ORDER if (m == 'histograms' and 'production' in raw)
            or (m == 'well_dashboard' and any(k != 'object_pressure' for k in raw)) or m in raw]


def group_of(mapping, well) -> str:
    return mapping.get(well, {}).get('group', 'Без группы')


def well_choices(module: str, raw: Mapping[str, pd.DataFrame]) -> list[str]:
    real = 'production' if module == 'histograms' else module
    if real == 'well_dashboard':
        return ordered(w for d in raw.values() if 'well' in d for w in d.well.dropna().unique())
    d = raw.get(real)
    return ordered(d.well.dropna()) if d is not None and 'well' in d else []


def wells_key(module: str) -> str:
    return ('dashboard' if module == 'well_dashboard' else module) + '_wells'


def latest_date(raw: Mapping[str, pd.DataFrame]):
    ends = [pd.to_datetime(d.date).max() for d in raw.values() if 'date' in d and not d.empty]
    ends = [e for e in ends if pd.notna(e)]
    return max(ends) if ends else pd.Timestamp.today().normalize()


def dashboard_periods(source, settings, mapping) -> dict[str, list[str]]:
    from app.modules import well_analysis
    try:
        daily = well_analysis.dataset(source, settings, mapping)['daily']
    except Exception:      # нет эксплуатации — нет периодов
        log.debug('Нет данных для периодов анализа', exc_info=True)
        return {'withdrawal': [], 'injection': []}
    if daily.empty:
        return {'withdrawal': [], 'injection': []}
    return {kind: ordered(daily.loc[daily.kind.eq(kind), 'period']) for kind in ('withdrawal', 'injection')}


def choices(data: Data, apply_exclusions: bool = True) -> dict[str, Any]:
    """Списки для формы: скважины и группы модулей, периоды, сезоны ГДИ, горизонты, даты, подписи Word."""
    from app.modules import well_charts
    source, raw = frames_of(data, apply_exclusions)
    settings, mapping = data.settings, data.mapping
    mods = available(raw)
    out: dict[str, Any] = {'modules': [{'id': m, 'label': MODULES[m]} for m in mods],
                           'default_modules': [m for m in DEFAULT_MODULES if m in raw],
                           'wells': {}, 'groups': {}, 'mapping': {w: group_of(mapping, w) for w in well_choices('well_dashboard', raw)}}
    for m in mods:
        if m in ('object_pressure', 'pressure_match'):
            continue
        wells = well_choices(m, raw)
        out['wells'][m] = wells
        out['groups'][m] = ordered(group_of(mapping, w) for w in wells)
    if 'production' in source:
        d = source['production']
        out['periods'] = {k: ordered(d.loc[d.kind.eq(k), 'period']) for k in ('withdrawal', 'injection')}
    if 'gdi' in source:
        g = source['gdi']
        out['gdi_seasons'] = ordered(g.season[g.season.ne('')]) if 'season' in g else []
        out['gdi_methods'] = ordered(g.method) if 'method' in g else []
    if 'response' in source:
        r = source['response']
        out['horizons'] = ordered(r.horizon)
        out['working'] = [h for h in settings.get('working_horizons', []) if h in out['horizons']]
        out['response_dates'] = [str(r.date.min().date()), str(r.date.max().date())] if not r.empty else []
    if 'well_dashboard' in mods:
        out['dashboard_periods'] = dashboard_periods(source, settings, mapping)
        out['asof'] = str(pd.Timestamp(latest_date(raw)).date())
        out['dashboard_charts'] = [{'id': k, 'label': v} for k, v in well_charts.LABELS.items()]
    panels = settings.get('panels', {})
    out['two_panels'] = {'production': bool(panels.get('prod_1')), 'histograms': bool(panels.get('hist_1'))}
    out['captions'] = {m: DEFAULT_CAPTIONS.get(m, DEFAULT_CAPTIONS['well_dashboard']) for m in mods}
    out['presets'] = {name: migrate_preset(v) for name, v in (settings.get('export_presets') or {}).items()}
    out['style'] = {f: settings.get('chart_style', {}).get(f, True) for f, _ in STYLE_FIELDS}
    return out


# ---------- форма (поля 5.8) → options для reporting.plan ----------

def _date(value) -> str:
    return str(pd.Timestamp(value).date())


def options_from(form: Mapping[str, Any], data: Data) -> tuple[dict, dict, dict]:
    """Повторяет сборку ``options`` в ``export_panel.render`` 5.8. Не заданное поле — значение виджета 5.8
    по умолчанию (списки — «все»). Возвращает (options, frames, raw_frames)."""
    from app.modules import well_charts
    apply_exclusions = bool(form.get('exclusions', True))
    source, raw = frames_of(data, apply_exclusions)
    settings, mapping = data.settings, data.mapping
    current = settings.get('panels', {})
    mods_available = available(raw)
    wanted = form.get('modules')
    wanted = [m for m in DEFAULT_MODULES if m in raw] if wanted is None else list(wanted)
    style = {f: bool(form.get('style_' + f, settings.get('chart_style', {}).get(f, True))) for f, _ in STYLE_FIELDS}
    options: dict[str, Any] = {'modules': [], 'wells': [], 'raw': bool(form.get('raw', False)),
                               'apply_exclusions': apply_exclusions, 'style': style}
    mods, selected = [], set()

    def pick(field, values, default=None):
        value = form.get(field)
        return list(values if default is None else default) if value is None else [v for v in map(str, value) if v in values]

    for module in [m for m in mods_available if m in wanted]:
        mods.append(module)
        if module == 'object_pressure':
            options[module] = {}
            continue
        if module == 'pressure_match':
            options[module] = cfg = pressure_cfg(form, data)
            selected.update(cfg['wells'] or ordered(raw['pressure_match'].well))
            continue
        wells = well_choices(module, raw)
        groups = ordered(group_of(mapping, w) for w in wells)
        gs = pick(module + '_groups', groups)
        wells = [w for w in wells if group_of(mapping, w) in gs]
        ws = pick(wells_key(module), wells)
        selected.update(ws)
        cfg: dict[str, Any] = {'wells': ws, 'groups': gs}
        if module in ('production', 'histograms'):
            d = source['production']
            periods = {}
            for kind in ('withdrawal', 'injection'):
                values = ordered(d.loc[d.kind.eq(kind), 'period'])
                periods[kind] = pick(f'{module}_periods_{kind}', values)
            view = 'hist' if module == 'histograms' else form.get('production_view', 'curve')
            split = form.get(module + '_split', 'well')
            direction = form.get(module + '_direction', 'number')
            cfg.update(periods=periods, view=view, split=split, direction=direction)
            prefix = 'hist' if module == 'histograms' else 'prod'
            if form.get(module + '_panels') and current.get(prefix + '_1'):
                cfg['panels'] = [{**cfg, 'panels': None, 'wells': v.get('wells', ws), 'periods': {v['kind']: v['periods']},
                                  'view': v.get('view', view), 'direction': v.get('direction', direction),
                                  'histaxis': v.get('histaxis', 'well'), 'hist_size': v.get('hist_size', 'Авто'), 'split': 'all'}
                                 for v in [current.get(prefix + '_0'), current.get(prefix + '_1')] if v]
            if split == 'group_total':
                cfg['metric'] = form.get('production_metric', 'daily')
                cfg['overlay'] = pick('production_overlay', ws, [])
            if split == 'subgroup':
                cfg['group_mode'] = form.get(module + '_groupmode', 'manual')
                cfg['size'] = int(form.get(module + '_size', 8))
            if module == 'histograms':
                cfg['histaxis'] = form.get('histograms_histaxis', 'well')
                cfg['hist_size'] = str(form.get('histograms_hist_size', 'Авто'))
        elif module == 'gdi':
            cfg['n'] = int(form.get('gdi_n', 3))
            cfg['orientation'] = form.get('gdi_orientation', 'standard')
            for field in ('curves', 'db_curves', 'crosshair', 'show_excluded'):
                cfg[field] = bool(form.get('gdi_' + field, True))
            g = source['gdi']
            seasons = ordered(g.season[g.season.ne('')]) if 'season' in g else []
            cfg['seasons'] = pick('gdi_seasons', seasons, []) if seasons else []
        elif module == 'response':
            r = source['response']
            hs = ordered(r.horizon)
            cfg['horizons'] = pick('response_horizons', hs)
            cfg['working'] = pick('response_working', hs, [h for h in settings.get('working_horizons', []) if h in hs])
            dates = form.get('response_dates') or ([r.date.min(), r.date.max()] if not r.empty else [])
            cfg['dates'] = [_date(v) for v in dates]
            cfg['view'] = form.get('response_view', 'separate')
            cfg['split'] = form.get('response_split', 'horizon')
            if form.get('response_mode', 'all') != 'all':      # выгрузка контрольных и/или рабочих горизонтов (нового в 5.8 нет)
                cfg['mode'] = form['response_mode']
                cfg['working_view'] = form.get('response_working_view', 'combined')
        elif module == 'well_dashboard':
            kind = form.get('dashboard_kind', 'withdrawal')
            periods = dashboard_periods(source, settings, mapping)[kind]
            cfg.update(kind=kind, periods=pick('dashboard_periods', periods, []) or None)
            cfg['method'] = form.get('dashboard_method')
            cfg['delta'] = float(form.get('dashboard_delta', 500.)) if form.get('dashboard_fixed') else None
            cfg['asof'] = _date(form.get('dashboard_asof') or latest_date(raw))
            cfg['threshold'] = float(form.get('dashboard_threshold', 10.))
            cfg['alignment'] = form.get('dashboard_alignment', 'well')
            gdi_saved = current.get('well_dashboard', {}).get('gdi', {})
            g = source.get('gdi')
            seasons = ordered(g.season[g.season.ne('')]) if g is not None and 'season' in g else []
            gcfg = {'n': 0, 'orientation': 'standard', 'curves': True, 'db_curves': True, 'crosshair': True,
                    'show_excluded': True, 'seasons': []}
            for name, field in GDI_DASHBOARD:
                value = form.get('dashboard_gdi_' + name, gdi_saved.get(field, gcfg[field]))
                gcfg[field] = [s for s in map(str, value or []) if s in seasons] if field == 'seasons' else value
            cfg['gdi'] = gcfg
            cfg['charts'] = pick('dashboard_charts', list(well_charts.LABELS))
        options[module] = cfg
    options['modules'] = mods
    options['wells'] = ordered(selected)
    return options, source, raw


def pressure_cfg(form: Mapping[str, Any], data: Data) -> dict[str, Any]:
    """Кроссплот давлений: параметры сохранённого вида раздела (формат 5.8) и «Построение при экспорте»."""
    from .domain import DatasetKind
    from .modules import pressure
    saved = pressure.saved_panel(data.settings)
    raw = data.raw[DatasetKind.PRESSURE_MATCH]
    cfg = copy.deepcopy(dict(saved)) if saved else pressure.config(pressure.PressureModule.spec.coerce({}), raw, data.settings)
    cfg['split'] = form.get('pressure_pm_export_split', 'all')
    return cfg


def pack_options(form: Mapping[str, Any], data: Data) -> dict[str, Any]:
    """Форма «Пакет по фонду»: все скважины фонда, все периоды, график «Производительность» по каждой скважине."""
    kinds = [k for k in form.get('pack_kinds', list(PACK_KINDS)) if k in PACK_KINDS]
    if not kinds:
        raise Failure(400, 'Выберите отбор или закачку')
    base = {'modules': ['production'], 'production_view': 'curve', 'production_split': 'well',
            'exclusions': form.get('exclusions', True)}
    base.update({k: v for k, v in form.items() if k.startswith('style_')})
    for kind in PACK_KINDS:
        if kind not in kinds:
            base['production_periods_' + kind] = []
        elif form.get('pack_periods_' + kind) is not None:
            if not form['pack_periods_' + kind]:
                raise Failure(400, 'Выберите сезоны, по которым строить кривые (%s)' % PACK_KINDS[kind][2].lower())
            base['production_periods_' + kind] = list(form['pack_periods_' + kind])
    return base


def optimized_png(png: bytes, colors: int = 48) -> bytes:
    """Палитровый PNG без дизеринга: линии и текст на белом остаются чёткими, файл в 3–4 раза легче."""
    import io

    from PIL import Image
    with Image.open(io.BytesIO(png)) as image:
        out = io.BytesIO()
        image.convert('RGB').quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.NONE).save(out, 'PNG', optimize=True)
        return out.getvalue()


def pack_label(template: str, section: str, number: int, well: str, kind: str, years: str) -> str:
    return template.format_map({'раздел': section, 'номер': number, 'скважина': well, 'режим': PACK_KINDS[kind][1], 'годы': years})


def years_of(d: pd.DataFrame, kind: str, periods) -> str:
    """«2020–2025»: годы первой и последней даты режима в выбранных периодах."""
    part = d[d.kind.eq(kind) & d.period.isin(periods)]
    dates = pd.to_datetime(part.date).dropna()
    if dates.empty:
        return ''
    a, b = int(dates.min().year), int(dates.max().year)
    return str(a) if a == b else f'{a}–{b}'


def captions_from(form: Mapping[str, Any], modules) -> dict[str, dict]:
    out = {}
    for m in modules:
        default = DEFAULT_CAPTIONS.get(m, DEFAULT_CAPTIONS['well_dashboard'])
        out[m] = {'section': str(form.get('caption_section_' + m, default['section'])),
                  'start': int(form.get('caption_start_' + m, default['start'])),
                  'template': str(form.get('caption_template_' + m, default['template']))[:500]}
    return out


def font_from(form: Mapping[str, Any]) -> tuple[str, Any]:
    """Шрифт и его размер (пт) из формы выгрузки; без них — стандартный шрифт и размер по умолчанию."""
    from app.core.fonts import check
    try:
        return check(form.get('font'), form.get('font_size'))
    except ValueError as e:
        raise Failure(400, str(e)) from None


def files_from(form: Mapping[str, Any]) -> tuple[list[str], int, int]:
    formats = list(form.get('formats', ['svg', 'pdf']))
    if any(f not in ('svg', 'pdf', 'png') for f in formats):
        raise Failure(400, 'Форматы графиков: svg, pdf, png')
    try:
        dpi, width = int(form.get('dpi', 300)), int(form.get('width', 220))
    except (TypeError, ValueError):
        raise Failure(400, 'Разрешение и ширина должны быть числами') from None
    if dpi not in (300, 600, 1200):
        raise Failure(400, 'Разрешение PNG: 300, 600 или 1200 DPI')
    if not 80 <= width <= 300:
        raise Failure(400, 'Ширина графика: от 80 до 300 мм')
    return formats, dpi, width


def height_from(form: Mapping[str, Any]) -> Optional[int]:
    """Высота графика, мм. Не задана (или 0) — подбирается по ширине и легенде, как в 5.8."""
    raw = form.get('height')
    if raw in (None, '', 0):
        return None
    try:
        height = int(raw)
    except (TypeError, ValueError):
        raise Failure(400, 'Высота должна быть числом') from None
    if not 40 <= height <= 400:
        raise Failure(400, 'Высота графика: от 40 до 400 мм')
    return height


def preset_values(form: Mapping[str, Any]) -> dict[str, Any]:
    """Поля формы, которые 5.8 сохраняет в шаблон (тот же отбор по именам)."""
    out = {}
    for field, value in form.items():
        if (field in PRESET_FIELDS or field.startswith(PRESET_PREFIXES)) and not field.endswith('__checklist'):
            if isinstance(value, (str, int, float, bool, list, tuple, dict)):
                try:
                    out[field] = json.loads(json.dumps(value, default=str))
                except (TypeError, ValueError):
                    pass
    return out


def sync_form(settings: Mapping[str, Any], prod_mode: str = 'curves') -> dict[str, Any]:
    """«Взять параметры из вкладок просмотра»: поля формы из сохранённых видов разделов (как в 5.8).
    Значение ``None`` — сбросить поле к умолчанию (в 5.8 поле удаляется из состояния)."""
    current = settings.get('panels', {})
    out: dict[str, Any] = {}
    for module in ('gdi', 'response', 'well_dashboard', 'pressure_match'):
        cfg = current.get(module, {})
        if module == 'well_dashboard':
            for name, _ in GDI_DASHBOARD:
                out['dashboard_gdi_' + name] = None
        if module == 'pressure_match':
            continue      # кроссплот берёт сохранённый вид раздела сам (см. pressure_cfg)
        target = 'dashboard' if module == 'well_dashboard' else module
        for field, value in cfg.items():
            out[target + '_' + field] = [_date(v) for v in value] if field == 'dates' else value
        if module == 'well_dashboard' and isinstance(cfg.get('gdi'), dict):
            for name, field in GDI_DASHBOARD:     # 5.8 подставляет их из dashboard_gdi при следующем показе
                if field in cfg['gdi']:
                    out['dashboard_gdi_' + name] = cfg['gdi'][field]
    for module, panel in (('production', 'prod_0'), ('histograms', 'hist_0')):
        cfg = current.get('group_totals' if module == 'production' and prod_mode == 'groups' else panel, {})
        for field, value in cfg.items():
            if field == 'periods' and isinstance(value, dict):
                for kind, chosen in value.items():
                    out[f'{module}_periods_{kind}'] = chosen
            elif field == 'periods' and isinstance(value, list):
                out[f"{module}_periods_{cfg.get('kind', 'withdrawal')}"] = value
            else:
                out[module + '_' + field] = value
    for field, value in settings.get('chart_style', {}).items():
        out['style_' + field] = value
    return out


# ---------- маршруты ----------

class Plans:
    """Последние планы выгрузки: предпросмотр и формирование не пересобирают перечень графиков."""

    def __init__(self, size=4):
        self.size, self.items, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key, build):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        value = build()
        with self.lock:
            self.items[key] = value
            while len(self.items) > self.size:
                self.items.popitem(last=False)
        return value


def routes(projects: Projects) -> list[Route]:
    plans = Plans()

    def endpoint(work):
        async def handler(request: Request):
            try:
                raw = await request.body() if request.method == 'POST' else b''
                body = json.loads(raw) if raw.strip() else {}
            except ValueError:
                return error(400, 'Тело запроса должно быть JSON')
            if not isinstance(body, dict):
                return error(400, 'Тело запроса должно быть объектом JSON')
            try:
                out = await run_in_threadpool(work, request, body)
            except Failure as e:
                return error(e.status, str(e))
            except (ParamError, ValueError) as e:
                if 'изменен' in str(e):
                    return error(409, 'Проект изменён в другом окне (например, в версии 5.8). Обновите данные и повторите.')
                return error(400, str(e))
            except Conflict as e:
                return error(409, str(e))
            except KeyError as e:
                return error(404, str(e.args[0]) if e.args else 'Не найдено')
            except Exception:
                log.exception('Сбой экспорта %s', request.url.path)
                return error(500, 'Экспорт не завершен: внутренняя ошибка. Уже сохраненные файлы доступны в разделе «Проекты». '
                                  'Подробности в журнале.')
            return out if isinstance(out, Response) else JSONResponse(out)
        return handler

    def form_of(body) -> dict:
        form = body.get('form') or {}
        if not isinstance(form, dict):
            raise Failure(400, 'Параметры экспорта должны быть объектом')
        return form

    def prepared(pid: str, form: dict):
        data = projects.data(pid)
        key = (pid, data.revision, json.dumps({k: v for k, v in form.items() if k not in ('width', 'height')}, sort_keys=True, ensure_ascii=False, default=str))

        def build():
            options, source, raw = options_from(form, data)
            if not options['modules'] or (not options['wells'] and 'object_pressure' not in options['modules']):
                return options, None, data
            return options, reporting.plan(source, data.mapping, data.settings, options, raw), data
        return plans.get(key, build)

    def need_plan(pid, form):
        options, plan, data = prepared(pid, form)
        if plan is None:
            raise Failure(400, 'Выберите модуль и хотя бы одну скважину для выгрузки.')
        return options, plan, data

    def metadata(pid, data, options, form):
        formats, dpi, width = files_from(form)
        m = projects.manifest(pid)
        return {'project': m['name'], 'version': VERSION_58, 'atlas': VERSION, 'revision': data.revision, 'options': options,
                'settings': data.settings, 'formats': formats, 'dpi': dpi, 'width_mm': width, 'height_mm': height_from(form),
                **dict(zip(('font', 'font_size'), font_from(form))),
                'created_utc': dt.datetime.now(dt.timezone.utc).isoformat()}

    def result_json(result):
        return {'files': [p.name for p in map(_path, result.paths)], 'planned': result.planned, 'completed': result.completed,
                'chart_files': result.files, 'errors': result.errors}

    # --- запросы ---
    def form_choices(request, body):
        pid = request.path_params['pid']
        projects.manifest(pid)
        return choices(projects.data(pid), request.query_params.get('exclusions', '1') != '0')

    def plan_view(request, body):
        options, plan, _ = prepared(request.path_params['pid'], form_of(body))
        if plan is None:
            return {'modules': options['modules'], 'charts': [], 'tables': [],
                    'note': 'Выберите модуль и хотя бы одну скважину для выгрузки.'}
        return {'modules': options['modules'], 'charts': [{'name': j.name, 'module': j.module} for j in plan.jobs],
                'tables': list(plan.tables),
                'note': '' if plan.jobs else 'Нет графиков в этом выборе; расчетные таблицы доступны для экспорта.'}

    def preview(request, body):
        form = form_of(body)
        _, plan, _ = need_plan(request.path_params['pid'], form)
        job = next((j for j in plan.jobs if j.name == body.get('chart')), None)
        if job is None:
            raise Failure(404, 'График не найден. Обновите предпросмотр.')
        _, _, width = files_from(form)
        font, font_size = font_from(form)
        content = figure_bytes(job.render(), 'png', 150, width, height_from(form), font=font, font_size=font_size)   # макет файла при выбранной ширине, 150 DPI
        return Response(content, media_type='image/png')

    def chart(request, body):
        """Тот же график предпросмотра как интерактивный: щелчок по точке исключает её (как в 5.8)."""
        from .contract import _chart_json
        from .export_chart import to_chart
        _, plan, _ = need_plan(request.path_params['pid'], form_of(body))
        job = next((j for j in plan.jobs if j.name == body.get('chart')), None)
        if job is None:
            raise Failure(404, 'График не найден. Обновите предпросмотр.')
        return _chart_json(to_chart(job.render(), 'export-' + str(job.module or 'chart')))

    def archive(request, body):
        pid, form = request.path_params['pid'], form_of(body)
        options, plan, data = need_plan(pid, form)
        meta = metadata(pid, data, options, form)
        result = export_plan(plan, projects.store, pid, meta['formats'], meta['dpi'], meta['width_mm'], meta, height_mm=meta.get('height_mm'))
        projects.store.event(pid, 'Экспорт', meta)
        return result_json(result)

    def word(request, body):
        pid, form = request.path_params['pid'], form_of(body)
        options, plan, data = need_plan(pid, form)
        if not plan.jobs:
            raise Failure(400, 'Нет графиков для Word-отчета')
        captions = captions_from(form, options['modules'])
        for template in (c['template'] for c in captions.values()):
            _check_caption(template)
        meta = metadata(pid, data, options, form)
        result = export_word(plan, projects.store, pid, projects.manifest(pid)['name'], captions, {**meta, 'captions': captions})
        return result_json(result)

    def pack(request, body):
        """Один щелчок: Word и PDF «6 графиков на листе A4» отдельно для отбора и закачки по всем скважинам фонда."""
        from app.core.export import figure_bytes
        from app.modules import production
        pid, form = request.path_params['pid'], form_of(body)
        data = projects.data(pid)
        template = str(form.get('pack_template') or PACK_TEMPLATE)[:500]
        _check_caption(template, PACK_FIELDS)
        formats = [f for f in form.get('pack_formats', ['docx', 'pdf']) if f in ('docx', 'pdf')]
        try:
            per_page = int(form.get('pack_per_page', PACK_PER_PAGE))
            dpi = int(form.get('pack_dpi', PACK_DPI))
        except (TypeError, ValueError):
            raise Failure(400, 'Число графиков на листе и разрешение должны быть числами') from None
        if per_page not in PACK_LAYOUTS:
            raise Failure(400, 'Графиков на листе: 2, 4 или 6')
        if dpi not in (150, 200, 250, 300):
            raise Failure(400, 'Разрешение графиков пакета: 150, 200, 250 или 300 DPI')
        columns, (image_w, image_h) = PACK_LAYOUTS[per_page]
        if not formats:
            raise Failure(400, 'Выберите Word или PDF')
        options, source, raw = options_from(pack_options(form, data), data)
        if not options['wells']:
            raise Failure(400, 'В проекте нет скважин с эксплуатацией для пакета графиков.')
        plan = reporting.plan(source, data.mapping, data.settings, options, raw)
        d = production.periods(source['production'], data.settings['season_start'], data.settings['season_end'])
        meta = metadata(pid, data, options, {})
        pack_font, pack_font_size = font_from(form)
        name = projects.manifest(pid)['name']
        paths, errors, planned, done = [], [], 0, 0
        for kind, (section_default, _, label) in PACK_KINDS.items():
            jobs = [j for j in plan.jobs if j.name.startswith(label + ' · ')]
            if not jobs:
                continue
            planned += len(jobs)
            section = str(form.get('pack_section_' + kind) or section_default)
            years = years_of(d, kind, options['production']['periods'][kind])
            entries = []
            for job in jobs:
                well = job.name.split(' · ', 1)[1]
                try:
                    entries.append((optimized_png(figure_bytes(job.render(), 'png', dpi, image_w, image_h, compact=True, font=pack_font, font_size=pack_font_size)),
                                    pack_label(template, section, len(entries) + 1, well, kind, years)))
                except Exception as e:
                    errors.append({'График': job.name, 'Формат': 'pack', 'Ошибка': str(e)})
            done += len(entries)
            if not entries:
                continue
            stem = 'Приложение_' + {'withdrawal': 'отбор', 'injection': 'закачка'}[kind]
            exports = projects.store.path(pid) / 'exports'
            exports.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='pending_pack_', dir=str(exports)) as tmp:
                info = {**meta, 'module': 'pack', 'kind': kind, 'charts': len(entries), 'per_page': per_page}
                if 'docx' in formats:
                    class Items:
                        def __len__(self):
                            return len(entries)

                        def items(self):
                            return ((text, png) for png, text in entries)
                    target = Path(tmp) / (stem + '.docx')
                    report_docx(Items(), name, per_page=per_page, image_mm=(image_w, image_h), title=False, columns=columns,
                                labeler=lambda png, text: text, render=lambda png: png, target=target)
                    paths.append(projects.store.save_export_file(pid, stem + '.docx', target, info))
                if 'pdf' in formats:
                    target = grid_pdf(entries, Path(tmp) / (stem + '.pdf'), columns, per_page // columns,
                                      {'Title': stem.replace('_', ' '), 'Author': 'Газовый атлас'})
                    paths.append(projects.store.save_export_file(pid, stem + '.pdf', target, info))
        if not paths:
            raise Failure(400, 'Нет графиков для пакета: в выбранном режиме нет данных.')
        projects.store.event(pid, 'Экспорт', {**meta, 'module': 'pack'})
        return {'files': [p.name for p in map(_path, paths)], 'planned': planned, 'completed': done,
                'chart_files': len(paths), 'errors': errors}

    def bundle(request, body):
        pid = request.path_params['pid']
        names = body.get('files') or []
        known = {p.name: p for p in projects.store.exports(pid)}
        missing = [n for n in names if n not in known]
        if not names or missing:
            raise Failure(400, 'Нет созданных файлов для общего скачивания.' if not names else 'Файл не найден: ' + missing[0])
        path = bundle_exports(projects.store, pid, [known[n] for n in names], {'version': VERSION_58})
        return {'file': _path(path).name}

    def save_preset(request, body):
        pid = request.path_params['pid']
        name = str(body.get('name') or '').strip()
        if not name:
            raise Failure(400, 'Введите название шаблона')
        m = projects.manifest(pid)
        cfg = copy.deepcopy(m.get('settings', {}))
        cfg.setdefault('export_presets', {})[name] = preset_values(form_of(body))
        expected = body.get('revision') if isinstance(body.get('revision'), int) else None
        saved = projects.store.commit(pid, settings=cfg, expected=expected, action='Шаблон экспорта')
        return projects.summary(saved)

    def sync(request, body):
        pid = request.path_params['pid']
        return sync_form(projects.data(pid).settings)

    E = endpoint
    base = '/api/projects/{pid}/export'
    return [
        Route(base + '/form', E(form_choices)),
        Route(base + '/plan', E(plan_view), methods=['POST']),
        Route(base + '/preview', E(preview), methods=['POST']),
        Route(base + '/chart', E(chart), methods=['POST']),
        Route(base + '/archive', E(archive), methods=['POST']),
        Route(base + '/word', E(word), methods=['POST']),
        Route(base + '/pack', E(pack), methods=['POST']),
        Route(base + '/bundle', E(bundle), methods=['POST']),
        Route(base + '/presets', E(save_preset), methods=['POST']),
        Route(base + '/sync', E(sync)),
    ]


def _path(p) -> Path:
    return Path(p)


def _check_caption(template: str, allowed=('раздел', 'номер', 'скважина', 'горизонт', 'период', 'модуль')):
    """Неизвестное поле подписи — понятная ошибка до формирования (тот же разбор, что ``caption_for``)."""
    import string
    try:
        fields = [f for _, f, s, c in string.Formatter().parse(template) if f is not None and (f not in allowed or s or c)]
    except ValueError:
        raise Failure(400, 'Шаблон подписи: незакрытая фигурная скобка') from None
    if fields:
        raise Failure(400, 'Неизвестное поле подписи: ' + str(fields[0]) + '. Допустимы: ' + ', '.join('{' + v + '}' for v in allowed))


def attachment(content: bytes, name: str, mime: str) -> Response:
    return Response(content, media_type=mime, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})
