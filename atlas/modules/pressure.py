"""Кроссплот давлений: факт / модель по объектам, сценариям, скважинам, группам и фондам.

Математика не переписана: сопоставление, отбор пар, пороги, сезоны и статистика — ``app.modules.pressure_match``
из 5.8 (``filter_data``, ``statistics``, ``tables``). Здесь выбор данных и представление.
Полный перечень функций раздела — docs/parity/pressure.md.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from app.core.config import ordered
from app.modules import pressure_match as legacy
from app.modules.charts import well_colors

from ..contract import (Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, ParamError, Result, Series,
                        Source, Table, TableAction)
from ..domain import DatasetKind

PM = DatasetKind.PRESSURE_MATCH
SECTION_DATA, SECTION_CALC, SECTION_VIEW, SECTION_AXES = 'Выбор данных', 'Расчет', 'Вид', 'Оси'
SCREEN_POINTS = 30000          # как в 5.8: точек кроссплота на экране; статистика — по всем
POINT_TABLE_LIMIT = 20000      # строк в таблице ручного фильтра
OUTLIER_LIMIT = 300            # выбросов на ящик при больших группах, как в 5.8
SHAPES = ('circle', 'square', 'triangle', 'diamond')
OUTSIDE_OPACITY = 0.25
FACT_COLOR, IDEAL_COLOR, BAND_COLOR, PERCENTILE_COLOR = '#64748B', '#64748B', '#D97706', '#8B5CF6'

COLORS = {'scenario': 'Сценарии', 'group': 'Группы', 'well': 'Скважины', 'object': 'Объекты',
          'object_group': 'Категории объектов'}
VIEWS = {'cross': ('Кроссплот', ['cross']), 'dynamics': ('Динамика', ['time', 'error_time']),
         'distributions': ('Распределения', ['overall_box', 'box', 'fond_box', 'hist', 'cdf']),
         'objects': ('Объекты', ['object_box', 'percentiles']), 'stats': ('Статистика', [])}
PER_WELL = ('time', 'error_time', 'box')
LIMITS = (Option('12', '12'), Option('24', '24'), Option('48', '48'), Option('96', '96'), Option('all', 'Все'))
STAT_ORDER = ('Сводная объектов', 'Общая статистика', 'По скважинам', 'По фондам', 'По сезонам', 'Последние 3 года',
              'По группам')
KEY_LABELS = {'object': 'Объект', 'scenario': 'Сценарий', 'well': 'Скважина', 'fond': 'Фонд', 'period': 'Период',
              'group': 'Группа'}
SUMMARY = (('object', 'Объект'), ('scenario', 'Сценарий'), ('Точек', 'Точек'), ('Среднее отклонение', 'Средн. |ΔP|'),
           ('RMSE', 'RMSE'), ('Смещение модели', 'Смещение'), ('В пределах порога, %', 'В пороге, %'))

METHOD_NOTE = ('Абсолютные ошибки и процентили рассчитаны по |модель − факт|. Стандартное отклонение — ddof=0. '
               'Совпадение по порогу учитывает выбранные < / ≤; IQR-выбросы не исключаются из статистики автоматически.')
FILTER_NOTE = ('Отметьте «Исключить» и примените изменения. Исходные значения сохраняются; снятый флажок восстанавливает '
               'пару. Статистика и графики пересчитываются по действующим парам.')
CATEGORY_NOTE = ('Произвольное название, например ПХГ или месторождение; пустое — «Без категории». Категории общие с 5.8 '
                 '(раздел «Категории» кроссплота) и окрашивают точки при цвете «Категории объектов».')
NO_CATEGORY = 'Без категории'    # как ``pressure_match.filter_data`` и поле «Категория» в 5.8
CATEGORIES_JOURNAL = 'Категории объектов'
EMPTY_NOTE = 'Нет пар после выбранных фильтров. Расширьте объекты, сценарии, период или снимите «Последние 3 года».'

def _fixed(axis: str) -> tuple[Param, ...]:
    show = {f'axis_{axis}': True}
    up = axis.upper()
    return (Param(f'axis_{axis}', f'Задать ось {up}', 'boolean', default=False, section=SECTION_AXES),
            Param(f'{axis}_min', f'{up} min', 'number', default=0.0, section=SECTION_AXES, show_if=show),
            Param(f'{axis}_max', f'{up} max', 'number', default=150.0, section=SECTION_AXES, show_if=show),
            Param(f'{axis}_step', f'{up} шаг', 'number', default=10.0, minimum=0.001, section=SECTION_AXES, show_if=show))


class PressureModule(Module):
    spec = ModuleSpec(
        id='pressure',
        title='Кроссплот давлений',
        group='Моделирование',
        description='Сопоставление факта и моделей по скважинам, датам, группам и объектам.',
        needs=(PM,),
        order=60,
        save_label='Сохранить',
        params=(
            Param('objects', 'Объекты', 'multi', default=[], source=Source(PM, 'object'), section=SECTION_DATA),
            Param('scenarios', 'Сценарии модели', 'multi', default=[], source=Source(PM, 'scenario'), section=SECTION_DATA),
            Param('groups', 'Группы', 'multi', default=[], dynamic=True, section=SECTION_DATA),
            Param('fonds', 'Фонды', 'multi', default=[], source=Source(PM, 'fond'), section=SECTION_DATA),
            Param('wells', 'Скважины', 'multi', default=[], dynamic=True, depends=('groups',), prefix='№ ',
                  section=SECTION_DATA),
            Param('date_from', 'Период с', 'date', default=None, section=SECTION_DATA),
            Param('date_to', 'по', 'date', default=None, section=SECTION_DATA),
            Param('exclude_zeros', 'Без нулевых давлений', 'boolean', default=True, section=SECTION_DATA),
            Param('recent', 'Последние 3 года', 'boolean', default=False, section=SECTION_DATA,
                  help='По правилу исходного скрипта: с 1 апреля (последний год данных − 3).'),
            Param('unit', 'Единицы', 'choice', default='бар', section=SECTION_CALC,
                  options=tuple(Option(u, u) for u in ('бар', 'кгс/см²', 'МПа')),
                  help='Меняет подписи. Числа факта и модели должны быть уже в одинаковых единицах.'),
            Param('threshold_mode', 'Порог совпадения', 'choice', default='absolute', section=SECTION_CALC,
                  options=(Option('absolute', 'Абсолютный'), Option('relative', 'Относительный, %'))),
            Param('threshold', 'Значение порога', 'number', default=10.0, minimum=0, section=SECTION_CALC),
            Param('inclusive', 'Включать границу порога (≤)', 'boolean', default=False, section=SECTION_CALC,
                  help='В исходной HTML-странице используется строгое «<».'),
            Param('threshold_groups', 'Группы с отдельным порогом', 'multi', default=[], dynamic=True, empty='ничего',
                  section=SECTION_CALC),
            Param('group_threshold', 'Порог этих групп', 'number', default=10.0, minimum=0, section=SECTION_CALC),
            Param('percentiles', 'Процентили', 'multi', default=['80', '85', '90'], section=SECTION_CALC,
                  options=tuple(Option(str(p), str(p)) for p in range(1, 100)),
                  help='Пусто — 80, 85, 90, как в 5.8.'),
            Param('view', 'Представление', 'choice', default='cross', section=SECTION_VIEW,
                  options=tuple(Option(k, v[0]) for k, v in VIEWS.items())),
            Param('color', 'Цвет точек', 'choice', default='scenario', section=SECTION_VIEW,
                  options=tuple(Option(k, v) for k, v in COLORS.items())),
            Param('well_limit', 'Скважин на графике', 'choice', default='24', options=LIMITS, section=SECTION_VIEW,
                  help='Для графиков по скважинам: при большом числе скважин они нечитаемы и медленны.'),
            Param('bins', 'Интервалов гистограммы', 'integer', default=20, minimum=5, maximum=100, section=SECTION_VIEW),
            Param('dim_outside', 'Бледные точки вне порога', 'boolean', default=True, section=SECTION_VIEW,
                  help='Точки в пределах порога яркие, вне порога — бледные.'),
            Param('bands', 'Линии порога на кроссплоте', 'boolean', default=True, section=SECTION_VIEW),
            Param('percentile_lines', 'Линии процентилей на кроссплоте', 'boolean', default=False, section=SECTION_VIEW),
            Param('outliers', 'Выбросы на ящиках с усами', 'boolean', default=True, section=SECTION_VIEW),
            *_fixed('x'), *_fixed('y'),
        ),
    )

    # --- варианты зависимых списков ---
    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        raw = data.raw[PM]
        if name in ('groups', 'threshold_groups'):
            return ordered(group_of(data.mapping, w) for w in raw.well.unique())
        if name == 'wells':
            groups = set(params.get('groups') or [])
            return ordered(w for w in raw.well.unique() if not groups or group_of(data.mapping, w) in groups)
        return super().options(name, data, params)

    # --- расчёт ---
    def run(self, data: Data, params: dict[str, Any]) -> Result:
        raw, source = data.raw[PM], data[PM]
        cfg = config(params, raw, data.settings)
        d, info = legacy.filter_data(source, data.settings, data.mapping, cfg)
        result = Result()
        stats = legacy.statistics(d, cfg['percentiles']) if not d.empty else {'Точек': 0}
        result.notes.append(Note('Пропущено неполных пар: {}; нулевых: {}; отрицательных: {}. Последние 3 года: с {}.'.format(
            info.get('missing', 0), info.get('zeros', 0), info.get('negative', 0), info.get('recent_start', '—'))))
        if d.empty:
            result.notes.append(Note(EMPTY_NOTE, 'warning'))
        else:
            result.tables.append(metrics_table(stats))
            view = params['view']
            for name in VIEWS[view][1]:
                result.charts.extend(self.charts(name, d, cfg, params, result))
            if view == 'cross':
                result.tables.append(summary_table(d, cfg))
            for title, frame in stat_tables(d, cfg):
                result.tables.append(Table(f'stats-{STAT_ORDER.index(title)}', title, frame, stat_columns(frame),
                                           collapsed=not (view == 'stats' and title == 'Сводная объектов')))
            result.notes.append(Note(METHOD_NOTE))
        result.tables.append(category_table(raw, cfg, collapsed=params['color'] != 'object_group'))
        points = point_table(raw, cfg, data)
        if points is not None:
            result.tables.append(points)
        return result

    def charts(self, name: str, d: pd.DataFrame, cfg: dict, params: dict, result: Result) -> list[Chart]:
        view = d
        if name in PER_WELL and params['well_limit'] != 'all':
            limit = int(params['well_limit'])
            if d.well.nunique() > limit:
                view = d[d.well.isin(ordered(d.well)[:limit])]
                result.notes.append(Note(f'«{legacy.LABELS[name]}»: показано {limit} из {d.well.nunique()} скважин. '
                                         'Увеличьте «Скважин на графике» или сузьте выбор скважин.'))
        chart = build(name, view, cfg)
        if name == 'cross' and len(d) > SCREEN_POINTS:
            result.notes.append(Note('Показана выборка {:,} из {:,} точек; статистика и таблицы — по всем.'
                                     .format(SCREEN_POINTS, len(d)).replace(',', ' ')))
        return [chart]

    # --- сохранённый вид: формат 5.8 (settings.panels.pressure_match) ---
    def panel_key(self, panel: int = 0) -> str:
        return 'pressure_match'

    def save_state(self, params: dict[str, Any], data: Data) -> dict[str, Any]:
        raw = data.raw[PM]
        cfg = config(params, raw, data.settings)
        everything = lambda column: ordered(raw[column])   # noqa: E731 — в 5.8 пустой список значит «ничего»
        groups = params['groups'] or self.options('groups', data, {})
        state = {
            'objects': params['objects'] or everything('object'), 'scenarios': params['scenarios'] or everything('scenario'),
            'groups': groups, 'fonds': params['fonds'] or everything('fond'),
            'wells': params['wells'] or self.options('wells', data, {'groups': groups}),
            'recent': params['recent'], 'exclude_zeros': params['exclude_zeros'], 'unit': params['unit'],
            'threshold_mode': params['threshold_mode'], 'threshold': params['threshold'],
            'inclusive': params['inclusive'], 'color': params['color'], 'bins': params['bins'],
            'bands': params['bands'], 'percentile_lines': params['percentile_lines'], 'outliers': params['outliers'],
            'group_thresholds': cfg['group_thresholds'], 'percentiles': cfg['percentiles'], 'axes': cfg['axes'],
            'object_groups': cfg['object_groups'], 'recent_starts': cfg['recent_starts'],
        }
        if not raw.empty:
            start, end = pd.to_datetime(raw.date).min().date(), pd.to_datetime(raw.date).max().date()
            state['dates'] = [params['date_from'] or str(start), params['date_to'] or str(end)]
        return state

    def load_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        names = ('objects', 'scenarios', 'groups', 'fonds', 'wells', 'recent', 'exclude_zeros', 'unit', 'threshold_mode',
                 'threshold', 'inclusive', 'color', 'bins', 'bands', 'percentile_lines', 'outliers')
        out = {k: state[k] for k in names if state.get(k) is not None}
        dates = state.get('dates') or []
        if len(dates) == 2:
            out['date_from'], out['date_to'] = str(dates[0])[:10], str(dates[1])[:10]
        if state.get('percentiles'):
            allowed = {str(p) for p in range(1, 100)}
            out['percentiles'] = [str(int(p)) for p in state['percentiles'] if float(p) == int(p) and str(int(p)) in allowed]
        thresholds = state.get('group_thresholds') or {}
        if thresholds:
            first = next(iter(thresholds.values()))
            out['threshold_groups'] = [g for g, v in thresholds.items() if v == first]
            out['group_threshold'] = float(first)
        axes = state.get('axes') or {}
        for axis in ('x', 'y'):
            span = axes.get(f'{axis}_range')
            if span and len(span) == 2:
                out.update({f'axis_{axis}': True, f'{axis}_min': float(span[0]), f'{axis}_max': float(span[1]),
                            f'{axis}_step': float(axes.get(f'{axis}_dtick', 10))})
        return out


# ---------- выбор данных: параметры 6 → cfg 5.8 ----------

def group_of(mapping: Mapping[str, Mapping[str, str]], well: str) -> str:
    return mapping.get(well, {}).get('group', 'Без группы')


def saved_panel(settings: Mapping[str, Any]) -> Mapping[str, Any]:
    return (settings.get('panels') or {}).get('pressure_match') or {}


def config(params: Mapping[str, Any], raw: pd.DataFrame, settings: Mapping[str, Any]) -> dict[str, Any]:
    """Словарь параметров в формате ``pressure_panel.options`` 5.8; пустой выбор — «все» (фильтр не задан)."""
    dates = pd.to_datetime(raw.date) if not raw.empty else pd.Series(dtype='datetime64[ns]')
    starts = {str(o): str(pd.Timestamp(year=v.year - 3, month=4, day=1).date())
              for o, v in dates.groupby(raw.object).max().items()} if not raw.empty else {}
    percentiles = sorted({float(p) for p in params['percentiles']}) or [80.0, 85.0, 90.0]
    cfg: dict[str, Any] = {
        'recent_starts': starts, 'recent': params['recent'], 'exclude_zeros': params['exclude_zeros'],
        'unit': params['unit'], 'threshold_mode': params['threshold_mode'], 'threshold': float(params['threshold']),
        'inclusive': params['inclusive'], 'color': params['color'], 'bins': int(params['bins']),
        'bands': params['bands'], 'percentile_lines': params['percentile_lines'], 'outliers': params['outliers'],
        'percentiles': percentiles, 'dim_outside': params['dim_outside'],
        'group_thresholds': {g: float(params['group_threshold']) for g in params['threshold_groups']},
        # Категории объектов хранятся в сохранённом виде 5.8 (раздел «Категории»); правятся таблицей «Категории объектов».
        'object_groups': dict(saved_panel(settings).get('object_groups') or {}),
        'axes': {},
    }
    for field in ('objects', 'scenarios', 'fonds', 'groups', 'wells'):
        cfg[field] = list(params[field]) if params[field] else None
    if (params['date_from'] or params['date_to']) and not raw.empty:
        cfg['dates'] = [params['date_from'] or str(dates.min().date()), params['date_to'] or str(dates.max().date())]
    for axis in ('x', 'y'):
        if params[f'axis_{axis}']:
            lo, hi = float(params[f'{axis}_min']), float(params[f'{axis}_max'])
            if hi > lo:
                cfg['axes'][f'{axis}_range'] = [lo, hi]
                cfg['axes'][f'{axis}_dtick'] = float(params[f'{axis}_step'])
    return cfg


def category_table(raw: pd.DataFrame, cfg: Mapping[str, Any], collapsed: bool = True) -> Table:
    """Редактор категорий: все объекты данных, как поля «Категория · объект» в 5.8."""
    objects = ordered(raw.object.astype(str)) if not raw.empty else []
    names = cfg.get('object_groups') or {}
    frame = pd.DataFrame({'object': objects, 'category': [str(names.get(o, NO_CATEGORY)) for o in objects]},
                         columns=['object', 'category'])
    return Table('object-categories', CATEGORIES_JOURNAL, frame, [Column('object', 'Объект'), Column('category', 'Категория')],
                 note=CATEGORY_NOTE, collapsed=collapsed,
                 action=TableAction('assign', None, 'object', 'Сохранить категории', fields=('category',),
                                    editable=('category',), journal=CATEGORIES_JOURNAL, target='object-categories'))


def with_categories(settings: Mapping[str, Any], objects: list[str], changes: Mapping[str, Any]) -> dict[str, Any]:
    """Настройки проекта с новыми категориями объектов в сохранённом виде 5.8 (``panels.pressure_match.object_groups``).

    ``changes``: объект -> название (или {'category': название}). Остальные параметры вида и других объектов
    не меняются; если вида ещё нет, 5.8 и 6 берут для остальных параметров значения по умолчанию."""
    if not isinstance(changes, Mapping) or not changes:
        raise ParamError('Нет изменений для сохранения')
    known = set(objects)
    unknown = [str(o) for o in changes if str(o) not in known]
    if unknown:
        raise ParamError('Нет таких объектов в данных кроссплота: ' + ', '.join(unknown[:5]) + '. Обновите страницу.')
    out = dict(settings)
    panels = dict(out.get('panels') or {})
    panel = dict(panels.get('pressure_match') or {})
    names = {str(k): str(v) for k, v in (panel.get('object_groups') or {}).items()}
    for obj, value in changes.items():
        if isinstance(value, Mapping):
            if set(value) != {'category'}:
                raise ParamError('Категория объекта: ожидается поле category')
            value = value['category']
        names[str(obj)] = str(value if value is not None else '').strip()[:200] or NO_CATEGORY
    panel['object_groups'] = names
    panels['pressure_match'] = panel
    out['panels'] = panels
    return out


def selected_raw(raw: pd.DataFrame, cfg: Mapping[str, Any], mapping) -> pd.DataFrame:
    """Исходные пары выборки (без отбора неполных и нулевых) — для ручного фильтра."""
    d = raw
    for column, field in (('object', 'objects'), ('scenario', 'scenarios'), ('fond', 'fonds'), ('well', 'wells')):
        if cfg.get(field) is not None:
            d = d[d[column].astype(str).isin(cfg[field])]
    if cfg.get('groups') is not None:
        d = d[d.well.map(lambda w: group_of(mapping, w)).isin(cfg['groups'])]
    if cfg.get('dates'):
        dates = pd.to_datetime(d.date)
        d = d[dates.between(pd.Timestamp(cfg['dates'][0]), pd.Timestamp(cfg['dates'][1]))]
    return d


# ---------- таблицы ----------

def number(value: Any) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None


def metrics_table(stats: Mapping[str, Any]) -> Table:
    frame = pd.DataFrame([{'points': stats.get('Точек', 0), 'mean': stats.get('Среднее отклонение'),
                           'rmse': stats.get('RMSE'), 'within': stats.get('В пределах порога, %')}])
    return Table('metrics', 'Итоги выборки', frame, [
        Column('points', 'Сопоставленных точек', kind='number'), Column('mean', 'Средняя |ΔP|', decimals=2, kind='number'),
        Column('rmse', 'RMSE', decimals=2, kind='number'), Column('within', 'В пределах порога', '%', 2, 'number')])


def summary_table(d: pd.DataFrame, cfg: Mapping[str, Any]) -> Table:
    """«Сводка по сценариям» рядом с кроссплотом, как ``pressure_panel.scenario_summary``."""
    rows = [{'object': o, 'scenario': s, **legacy.statistics(g, cfg['percentiles'])}
            for (o, s), g in d.groupby(['object', 'scenario'], sort=False)]
    frame = pd.DataFrame(rows)[[k for k, _ in SUMMARY]].round(2)
    note = 'Объектов: {} · скважин: {}. Порог: ±{:g} {}.'.format(
        d.object.nunique(), d.well.nunique(), cfg['threshold'], '%' if cfg['threshold_mode'] == 'relative' else cfg['unit'])
    return Table('summary', 'Сводка по сценариям', frame,
                 [Column(k, label, decimals=2 if k not in ('object', 'scenario', 'Точек') else None,
                         kind='text' if k in ('object', 'scenario') else 'number') for k, label in SUMMARY], note=note)


def stat_tables(d: pd.DataFrame, cfg: Mapping[str, Any]) -> list[tuple[str, pd.DataFrame]]:
    tables = legacy.tables(d, cfg)
    return [(name, tables[name]) for name in STAT_ORDER]


def stat_columns(frame: pd.DataFrame) -> list[Column]:
    columns = []
    for c in frame.columns:
        if c in KEY_LABELS:
            columns.append(Column(c, KEY_LABELS[c]))
        elif c in ('Точек', 'Точек для порога', 'Выбросов IQR'):
            columns.append(Column(c, c, kind='number'))
        else:
            columns.append(Column(c, c, decimals=3, kind='number'))
    return columns


def point_table(raw: pd.DataFrame, cfg: Mapping[str, Any], data: Data) -> Table | None:
    d = selected_raw(raw, cfg, data.mapping)
    if d.empty or '_point_id' not in d:
        return None
    excluded = data.excluded
    d = d.assign(date=pd.to_datetime(d.date), _excluded=d['_point_id'].isin(excluded),
                 _reason=d['_point_id'].map(lambda i: (excluded.get(i) or {}).get('reason', '')))
    d = d.sort_values(['date', 'object', 'scenario', 'well'], ascending=[False, True, True, True], kind='stable')
    note = FILTER_NOTE
    if len(d) > POINT_TABLE_LIMIT:
        note += (f' Показаны {POINT_TABLE_LIMIT:,} самых свежих пар из {len(d):,}; сузьте выбор, чтобы увидеть остальные.'
                 .replace(',', ' '))
        d = d.head(POINT_TABLE_LIMIT)
    d = d.reset_index(drop=True)
    columns = [Column('object', 'Объект'), Column('scenario', 'Сценарий'), Column('well', 'Скважина'),
               Column('date', 'Дата', kind='date'), Column('fact', 'Факт', decimals=3, kind='number'),
               Column('model', 'Модель', decimals=3, kind='number'), Column('fond', 'Фонд')]
    for key, label, kind in (('file', 'Файл', 'text'), ('sheet', 'Лист', 'text'), ('_row', 'Строка', 'number')):
        if key in d:
            columns.append(Column(key, label, kind=kind))
    columns.append(Column('_reason', 'Причина исключения'))
    return Table('points', 'Ручной фильтр пар', d, columns, note=note, collapsed=True,
                 action=TableAction('exclude', PM, '_point_id', 'Применить ручной фильтр', checked_column='_excluded'))


# ---------- графики: то же, что ``legacy.figure``, в типах контракта ----------

def color_column(cfg: Mapping[str, Any]) -> str:
    mode = cfg.get('color', 'scenario')
    return mode if mode in COLORS else 'scenario'


def chart_title(d: pd.DataFrame, name: str) -> str:
    single = d.well.nunique() == 1
    return (f'Скважина №{d.well.iloc[0]} · ' if single else '') + legacy.LABELS[name]


def fixed_axis(axis: Axis, cfg: Mapping[str, Any], which: str) -> Axis:
    axes = cfg.get('axes') or {}
    if f'{which}_range' in axes:
        axis.minimum, axis.maximum = axes[f'{which}_range']
        axis.step = axes.get(f'{which}_dtick')
    return axis


def build(name: str, d: pd.DataFrame, cfg: Mapping[str, Any]) -> Chart:
    """График 5.8 ``name``; заданные вручную границы и шаг осей («Оси») действуют на все числовые оси, как в 5.8."""
    chart = _build(name, d, cfg)
    for axis, which in ((chart.x, 'x'), (chart.y, 'y')):
        if axis.scale == 'value':
            fixed_axis(axis, cfg, which)
    return chart


def _build(name: str, d: pd.DataFrame, cfg: Mapping[str, Any]) -> Chart:
    unit = cfg.get('unit', 'бар')
    title = chart_title(d, name)
    if name == 'cross':
        return cross_chart(d, cfg, title, unit)
    if name in ('time', 'error_time'):
        return time_chart(d, name, title, unit)
    if name == 'overall_box':
        return overall_box_chart(d, cfg, title, unit)
    if name in ('box', 'fond_box', 'object_box'):
        return box_chart(d, name, cfg, title, unit)
    if name == 'hist':
        return hist_chart(d, cfg, title, unit)
    if name == 'cdf':
        return cdf_chart(d, cfg, title, unit)
    return percentile_chart(d, cfg, title, unit)


def cross_chart(d: pd.DataFrame, cfg: Mapping[str, Any], title: str, unit: str) -> Chart:
    column = color_column(cfg)
    palette = well_colors(d[column])
    relative = cfg.get('threshold_mode') == 'relative'
    chart = Chart('pressure-cross', title, Axis('Фактическое давление', unit), Axis('Модельное давление', unit))
    shown = d.sample(SCREEN_POINTS, random_state=0).sort_index() if len(d) > SCREEN_POINTS else d
    # Форма маркера — по сценарию, если цвет не по сценариям и сценариев не больше форм.
    scenarios = ordered(str(v) for v in d.scenario)
    shapes = column != 'scenario' and 1 < len(scenarios) <= len(SHAPES)
    keys = [column, 'scenario'] if shapes else [column]
    dim = cfg.get('dim_outside', True)
    for key, g in shown.groupby(keys, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        label = str(key[0])
        name = f'{label} · {key[1]}' if shapes else label
        symbol = SHAPES[scenarios.index(str(key[1]))] if shapes else 'circle'
        for inside in ((True, False) if dim else (None,)):
            part = g if inside is None else g[g.within.eq(inside)]
            if part.empty:
                continue
            tips = [f'Скв. {w} · Группа: {gr} · {s} · {t.strftime("%d.%m.%Y")} · Факт: {f:.3f} · Модель: {m:.3f} · '
                    f'|ΔP|: {e:.3f} · Порог: {h:.3f} · {"в пороге" if ok else "вне порога"}'
                    for w, gr, s, t, f, m, e, h, ok in zip(part.well, part.group, part.scenario, part.date, part.fact,
                                                          part.model, part.error, part.threshold, part.within)]
            chart.series.append(Series(name if inside is not False else name + ' · вне порога',
                                       part.fact.to_numpy(float), part.model.to_numpy(float), 'points', group=name,
                                       color=palette[label], symbol=symbol, labels=tips,
                                       legend=inside is not False, opacity=OUTSIDE_OPACITY if inside is False else 1.0,
                                       ids=part['_point_id'].tolist() if '_point_id' in part else None, dataset=PM))
    lo = max(0.0, float(min(d.fact.min(), d.model.min())))
    hi = float(max(d.fact.max(), d.model.max()))
    x = np.array([lo, hi if hi > lo else lo + 1])
    chart.series.append(Series('Идеальное совпадение', x, x, 'line', color=IDEAL_COLOR, dash='solid'))
    if cfg.get('bands', True):
        by_group = bool(cfg.get('group_thresholds'))
        group_palette = well_colors(d.group) if by_group else {}
        pairs = d[['group', 'threshold']].drop_duplicates().sort_values(['threshold', 'group']) if by_group \
            else pd.DataFrame({'group': '', 'threshold': sorted(set(d.threshold))})
        for gr, threshold in zip(pairs.group, pairs.threshold):
            label = ('{} '.format(gr) if by_group else '') + '±{:g} {}'.format(threshold, '%' if relative else unit)
            for sign in (-1, 1):
                y = x * (1 + sign * threshold / 100) if relative else x + sign * threshold
                chart.series.append(Series(label, x, y, 'line', group=label, dash='dash', legend=sign == 1,
                                           color=group_palette[gr] if by_group else BAND_COLOR))
    if cfg.get('percentile_lines', False):
        for p in cfg.get('percentiles', [80, 85, 90]):
            delta = float(np.percentile(d.error, p))
            label = 'P{:g} = {:.3g}'.format(p, delta)
            for sign in (-1, 1):
                chart.series.append(Series(label, x, x + sign * delta, 'line', group=label, color=PERCENTILE_COLOR, dash='dot', legend=sign == 1))
    # Одинаковый масштаб осей (scaleanchor в 5.8): общие округлённые границы, если оси не заданы вручную.
    step = 10 ** np.floor(np.log10(max(x[1] - x[0], 1e-9) / 5))
    for axis in (chart.x, chart.y):
        axis.minimum, axis.maximum = float(np.floor(x[0] / step) * step), float(np.ceil(x[1] / step) * step)
    return chart


def time_chart(d: pd.DataFrame, name: str, title: str, unit: str) -> Chart:
    single = d.well.nunique() == 1
    many_objects = d.object.nunique() > 1
    colors = well_colors(ordered(str(v) for v in d.scenario))
    y_axis = Axis('Давление', unit) if name == 'time' else Axis('Модель − факт', unit)
    chart = Chart(f'pressure-{name}', title, Axis('Дата', scale='time'), y_axis)

    def suffix(well, obj):
        return ('' if single else f' · №{well}') + (f' · {obj}' if many_objects else '')

    if name == 'time':
        # Одна линия факта на объект и скважину: сценарии не размножают замеры.
        for (obj, well), g in d.drop_duplicates(['object', 'well', 'date']).groupby(['object', 'well']):
            chart.series.append(Series('Факт' + suffix(well, obj), g.date, g.fact.to_numpy(float), 'line',
                                       color=FACT_COLOR, dash='solid', group='Факт' + suffix(well, obj),
                                       labels=[f'Скв. {well}'] * len(g)))
    for (obj, scenario, well), g in d.groupby(['object', 'scenario', 'well'], sort=False):
        label = str(scenario) + suffix(well, obj)
        values = g.model if name == 'time' else g.signed_error
        chart.series.append(Series(label, g.date, values.to_numpy(float), 'line', color=colors[str(scenario)],
                                   dash='solid', labels=[f'Скв. {well} · {scenario}'] * len(g)))
    return chart


def box_stats(values: np.ndarray) -> tuple[list[float] | None, np.ndarray]:
    """Квартили (линейные, как quartilemethod='linear'), усы до крайних значений в 1,5 IQR и выбросы — как ``add_box``."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return None, values
    q1, median, q3 = np.percentile(values, [25, 50, 75])
    iqr = q3 - q1
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = values[(values >= low) & (values <= high)]
    out = values[(values < low) | (values > high)]
    if len(values) > legacy.BOX_EXACT_LIMIT and len(out) > OUTLIER_LIMIT:
        out = out[np.linspace(0, len(out) - 1, OUTLIER_LIMIT).astype(int)]
    return [float(inside.min()), float(q1), float(median), float(q3), float(inside.max())], out


def add_boxes(chart: Chart, name: str, categories: list[str], parts: Mapping[str, np.ndarray], color: str,
              outliers: bool) -> None:
    y, ox, oy = [], [], []
    for category in categories:
        stats, out = box_stats(parts[category]) if category in parts else (None, np.array([]))
        y.append(stats)
        ox.extend([category] * len(out))
        oy.extend(float(v) for v in out)
    chart.series.append(Series(name, categories, y, 'box', group=name, color=color))
    if outliers and ox:
        chart.series.append(Series(f'{name} · выбросы', ox, oy, 'points', group=name, color=color, legend=False))


def overall_box_chart(d: pd.DataFrame, cfg: Mapping[str, Any], title: str, unit: str) -> Chart:
    rows = [('Все данные', d), ('Последние 3 года', d[d.recent])]
    for fond in ordered(d.fond):
        rows.extend([(fond, d[d.fond.eq(fond)]), (f'{fond} · 3 года', d[d.fond.eq(fond) & d.recent])])
    rows = [(label, g) for label, g in rows if not g.empty]
    categories = [label for label, _ in rows]
    chart = Chart('pressure-overall_box', title, Axis('Период и фонд', scale='category', categories=categories),
                  Axis('Отклонение', unit))
    add_boxes(chart, '|ΔP|', categories, {label: g.error.to_numpy() for label, g in rows}, '#2563eb',
              cfg.get('outliers', True))
    return chart


def box_chart(d: pd.DataFrame, name: str, cfg: Mapping[str, Any], title: str, unit: str) -> Chart:
    col = {'box': 'well', 'fond_box': 'fond', 'object_box': 'object'}[name]
    medians = d.groupby(col).error.median()
    categories = [str(c) for c in sorted(medians.index, key=lambda c: medians[c])]
    label = {'box': 'Скважина (по медиане)', 'fond_box': 'Фонд', 'object_box': 'Объект'}[name]
    chart = Chart(f'pressure-{name}', title, Axis(label, scale='category', categories=categories), Axis('Отклонение', unit))
    colors = well_colors(ordered(str(v) for v in d.scenario))
    for scenario, g in d.groupby('scenario', sort=True):
        parts = {str(c): part.error.to_numpy() for c, part in g.groupby(col)}
        add_boxes(chart, str(scenario), categories, parts, colors[str(scenario)], cfg.get('outliers', True))
    return chart


def hist_chart(d: pd.DataFrame, cfg: Mapping[str, Any], title: str, unit: str) -> Chart:
    column = color_column(cfg)
    palette = well_colors(d[column])
    edges = np.histogram_bin_edges(d.error.to_numpy(), bins=int(cfg.get('bins', 20)))
    centers = (edges[:-1] + edges[1:]) / 2
    categories = ['{:.3g}'.format(c) for c in centers]
    chart = Chart('pressure-hist', title, Axis('Отклонение', unit, scale='category', categories=categories),
                  Axis('Количество точек', from_zero=True))
    for label, g in d.groupby(column, sort=False):
        counts, _ = np.histogram(g.error, bins=edges)
        chart.series.append(Series(str(label), categories, counts.astype(int).tolist(), 'bar', color=palette[str(label)]))
    return chart


def cdf_chart(d: pd.DataFrame, cfg: Mapping[str, Any], title: str, unit: str) -> Chart:
    column = color_column(cfg)
    palette = well_colors(d[column])
    y = Axis('Доля точек с отклонением ≤ X', '%', from_zero=True)
    y.maximum = 100.0
    chart = Chart('pressure-cdf', title, Axis('Отклонение', unit, from_zero=True), y)
    for label, g in d.groupby(column, sort=False):
        values, share = legacy.downsample_sorted(g.error.to_numpy())
        chart.series.append(Series(str(label), values, share, 'line', color=palette[str(label)], dash='solid'))
    return chart


def percentile_chart(d: pd.DataFrame, cfg: Mapping[str, Any], title: str, unit: str) -> Chart:
    ps = cfg.get('percentiles', [80, 85, 90])
    categories = ['P{:g}'.format(p) for p in ps]
    chart = Chart('pressure-percentiles', title, Axis('Процентиль', scale='category', categories=categories),
                  Axis('Отклонение', unit, from_zero=True))
    for (obj, scenario), g in d.groupby(['object', 'scenario'], sort=False):
        chart.series.append(Series(f'{obj} · {scenario}', categories, np.percentile(g.error, ps).tolist(), 'bar'))
    return chart
