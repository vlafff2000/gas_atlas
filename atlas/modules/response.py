"""Графики реагирования: уровень жидкости и приведённое пластовое давление контрольных горизонтов.

Как в 5.8 (``app/main.py``, страница «Графики реагирования»; рисунок — ``app.modules.charts.response_chart``):
выбор горизонтов → скважин → периода; вид (уровень и давление отдельно, на двух шкалах, только одно);
построение по горизонтам, все вместе или по скважинам. Новой математики нет: здесь выбор данных и представление,
прореживание точек — ``charts.decimate``, цвета скважин — ``charts.well_colors``, идентификаторы точек —
``exclusions.point_id``. Полный перечень функций раздела — docs/parity/response.md.
"""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from app.core import exclusions
from app.core.config import ordered
from app.modules.charts import decimate, well_colors, well_title

from ..contract import (Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Source,
                        Stat, Table, TableAction)
from ..domain import UNITS, DatasetKind
from ._events import regime_events

RESPONSE, OBJECT, PRODUCTION = DatasetKind.RESPONSE, DatasetKind.OBJECT_PRESSURE, DatasetKind.PRODUCTION
SECTION_DATA, SECTION_VIEW = 'Выбор данных', 'Вид'
POINT_TABLE_LIMIT = 20000

VIEWS = (Option('separate', 'Уровень и давление отдельно'), Option('combined', 'Уровень + давление (две шкалы Y)'),
         Option('level', 'Только уровень'), Option('pressure', 'Только давление'))
SPLITS = (Option('horizon', 'Отдельно по горизонтам'), Option('all', 'Все выбранные на одной диаграмме'),
          Option('well', 'Отдельно по скважинам'))
METRIC_WORDS = {'level': 'уровень', 'pressure': 'давление', 'combined': 'уровень и давление'}

# Цвета 5.8 для графиков по скважине (горизонт с давлением): уровень — мятный, ГДМ — фиолетовый,
# пересчёт — синий, объект — красный.
LEVEL_COLOR, MANOMETER_COLOR, RECALC_COLOR, OBJECT_COLOR = '#32BDA4', '#8B5CF6', '#2563EB', '#DC3545'
LEVEL_AXIS = Axis('Уровень жидкости', 'м')
PRESSURE_AXIS = Axis('Пластовое давление', UNITS['pressure'])

VIEW_NOTE = ('При совмещении давление — слева, уровень — справа с обратной шкалой. В графиках по скважине: '
             'объект — красный, уровень — мятный, ГДМ — фиолетовый, пересчет — синий.')
FILTER_NOTE = ('Отметьте «Исключить» и примените изменения. Исходные значения сохраняются; снятый флажок восстанавливает '
               'точку. Уровень и давление одного замера исключаются раздельно.')


def well_order(df: pd.DataFrame, horizons: list[str]) -> list[str]:
    return ordered(df.loc[df.horizon.astype(str).isin(horizons), 'well']) if not df.empty else []


def between(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if start:
        df = df[df.date >= pd.Timestamp(start)]
    if end:
        df = df[df.date <= pd.Timestamp(end)]
    return df


class Selection:
    """Выбор пользователя, приведённый к данным проекта (недопустимое отбрасывается)."""

    def __init__(self, data: Data, params: Mapping[str, Any]):
        self.df, self.raw = data[RESPONSE], data.raw[RESPONSE]
        everything = ordered(self.df.horizon)
        chosen = [h for h in params['horizons'] if h in everything]
        self.horizons = chosen or everything          # пустой список — все горизонты
        allowed = set(well_order(self.df, self.horizons))
        self.wells = [w for w in params['wells'] if w in allowed]
        self.start, self.end = params['date_from'], params['date_to']

    def frame(self, df: pd.DataFrame) -> pd.DataFrame:
        part = df[df.horizon.astype(str).isin(self.horizons) & df.well.astype(str).isin(self.wells)]
        return between(part, self.start, self.end)


def response_chart(part: pd.DataFrame, metric: str, title: str, chart_id: str, palette: Mapping[str, str],
                   object_pressure: pd.DataFrame | None, manometer: set[str], by_well: bool,
                   pressure_horizons: set[str]) -> Chart:
    """Перенос ``charts.response_chart``: те же серии, цвета, маркеры, оси и прореживание."""
    wells = ordered(part.well)
    pressure_enabled = bool(set(part.horizon).intersection(pressure_horizons)) if not part.empty else False
    dual = metric == 'combined' and pressure_enabled
    y = PRESSURE_AXIS if metric == 'pressure' or dual else LEVEL_AXIS
    y = Axis(y.label, y.unit, inverse=metric == 'level' or (metric == 'combined' and not dual))
    chart = Chart(chart_id, title, Axis('Дата', scale='time'), y,
                  y2=Axis(LEVEL_AXIS.label, LEVEL_AXIS.unit, inverse=True) if dual else None)
    if part.empty:
        return chart
    legends = set()
    fields = ['level', 'pressure'] if metric == 'combined' else [metric]
    for (h, w), g in part.groupby(['horizon', 'well'], sort=True):
        w = str(w)
        semantic = by_well and h in pressure_horizons
        for field in fields:
            if field not in g or not g[field].notna().any():
                continue
            data = decimate(g.sort_values('date'), field)
            ids = (data['_point_id'].map(lambda v: exclusions.point_id('response', v, field)).tolist()
                   if '_point_id' in data else None)
            suffix = ('уровень жидкости' if field == 'level' else
                      'давление (глубинный манометр)' if w in manometer else 'давление (пересчет)')
            color = ((LEVEL_COLOR if field == 'level' else MANOMETER_COLOR if w in manometer else RECALC_COLOR)
                     if semantic else palette[w])
            name = suffix.capitalize() if by_well and len(wells) == 1 else f'№ {w}'
            legend_key = (h, w, field) if by_well else w
            chart.series.append(Series(
                name, data.date.to_numpy(), data[field].to_numpy(float), 'line', group=name, color=color,
                dash='solid', width=2.0, markers=True, symbol='circle' if field == 'level' else 'diamond',
                hollow=field == 'level' and semantic, legend=legend_key not in legends,
                axis='y2' if dual and field == 'level' else 'y',
                labels=[f'{h} · скв. {w} · {suffix}'] * len(data), ids=ids, dataset=RESPONSE))
            legends.add(legend_key)
    if pressure_enabled and metric in ('pressure', 'combined') and object_pressure is not None \
            and not object_pressure.empty:
        data = object_pressure.sort_values('date')
        data = decimate(data[data.date.between(part.date.min(), part.date.max())], 'pressure')
        if not data.empty:
            chart.series.append(Series(
                'Пластовое давление объекта', data.date.to_numpy(), data.pressure.to_numpy(float), 'line',
                color=OBJECT_COLOR, dash='solid', width=2.0, markers=True,
                ids=data['_point_id'].astype(str).tolist() if '_point_id' in data else None, dataset=OBJECT))
    return chart


def chart_title(wells: list[str], label: str, split: str) -> str:
    """``charts.response_title``."""
    return f'Горизонт {label}' if split == 'horizon' else well_title(wells)


# ---------- таблицы ----------

def measurements_table(f: pd.DataFrame) -> Table:
    """«Выбранные замеры · CSV» из 5.8: действующие значения (исключённые — пусто)."""
    d = exclusions.public_table(f).reset_index(drop=True)
    columns = [Column('well', 'Скважина'), Column('date', 'Дата', kind='date'), Column('horizon', 'Горизонт')]
    for key, label, unit in (('level', 'Уровень жидкости', 'м'), ('pressure', 'Рпл привед.', UNITS['pressure'])):
        if key in d:
            columns.append(Column(key, label, unit, 2, 'number'))
    for key, label in (('group', 'Группа'), ('subgroup', 'Подгруппа'), ('file', 'Файл'), ('sheet', 'Лист'),
                       ('_row', 'Строка')):
        if key in d:
            columns.append(Column(key, label, kind='number' if key == '_row' else 'text'))
    return Table('measurements', 'Выбранные замеры', d, columns, collapsed=True)


def limited(part: pd.DataFrame, note: str) -> tuple[pd.DataFrame, str]:
    total = len(part)
    part = part.sort_values(['date', 'well'], ascending=[False, True], kind='stable').head(POINT_TABLE_LIMIT)
    if total > POINT_TABLE_LIMIT:
        note += (f' Показаны {POINT_TABLE_LIMIT:,} самых свежих точек из {total:,}: сузьте выбор, '
                 'чтобы увидеть остальные.').replace(',', ' ')
    return part, note


def point_table(original: pd.DataFrame, field: str, excluded: Mapping[str, dict]) -> Table | None:
    """Ручной фильтр 5.8 (``PointControls.tools('response')``) для одного показателя."""
    if field not in original or '_point_id' not in original:
        return None
    part = original[original[field].notna()]
    if part.empty:
        return None
    part, note = limited(part, FILTER_NOTE)
    ids = part['_point_id'].map(lambda v: exclusions.point_id('response', v, field))
    part = part.assign(_id=ids, _excluded=ids.isin(excluded),
                       _reason=ids.map(lambda i: (excluded.get(i) or {}).get('reason', ''))).reset_index(drop=True)
    word = 'уровень жидкости' if field == 'level' else 'приведенное давление'
    columns = [Column('well', 'Скважина'), Column('date', 'Дата', kind='date'), Column('horizon', 'Горизонт'),
               Column(field, 'Уровень' if field == 'level' else 'Рпл привед.',
                      'м' if field == 'level' else UNITS['pressure'], 2, 'number')]
    for key, label in (('file', 'Файл'), ('sheet', 'Лист'), ('_row', 'Строка')):
        if key in part:
            columns.append(Column(key, label, kind='number' if key == '_row' else 'text'))
    columns.append(Column('_reason', 'Причина исключения'))
    return Table(f'points-{field}', f'Ручной фильтр точек · {word}', part, columns, note=note, collapsed=True,
                 action=TableAction('exclude', RESPONSE, '_id', 'Применить ручной фильтр', checked_column='_excluded'))


def object_point_table(raw: pd.DataFrame, excluded: Mapping[str, dict]) -> Table | None:
    """Ручной фильтр 5.8 · давление объекта."""
    if raw is None or raw.empty or '_point_id' not in raw or 'pressure' not in raw:
        return None
    part = raw.sort_values('date', ascending=False, kind='stable').head(POINT_TABLE_LIMIT)
    part = part.assign(_excluded=part['_point_id'].isin(excluded),
                       _reason=part['_point_id'].map(lambda i: (excluded.get(i) or {}).get('reason', '')))
    columns = [Column('date', 'Дата', kind='date'), Column('pressure', 'Пластовое давление', UNITS['pressure'], 2, 'number')]
    for key, label in (('file', 'Файл'), ('sheet', 'Лист'), ('_row', 'Строка')):
        if key in part:
            columns.append(Column(key, label, kind='number' if key == '_row' else 'text'))
    columns.append(Column('_reason', 'Причина исключения'))
    return Table('points-object', 'Ручной фильтр точек · давление объекта', part.reset_index(drop=True), columns,
                 note=FILTER_NOTE.split(' Уровень')[0], collapsed=True,
                 action=TableAction('exclude', OBJECT, '_point_id', 'Применить ручной фильтр', checked_column='_excluded'))


class ResponseModule(Module):
    spec = ModuleSpec(
        id='response',
        title='Графики реагирования',
        group='Контроль горизонтов',
        description='Сравнение скважин внутри горизонта; уровень и приведенное давление на одной диаграмме или отдельно.',
        needs=(RESPONSE,),
        optional=(OBJECT, PRODUCTION),      # эксплуатация — только отметки смены режима на графиках
        order=40,
        save_label='Сохранить параметры графиков',
        params=(
            Param('working', 'Рабочие горизонты', 'multi', default=[], source=Source(RESPONSE, 'horizon'),
                  setting='working_horizons', empty='ничего', section=SECTION_DATA,
                  help='Общая настройка проекта: сохраняется сразу и видна в версии 5.8'),
            Param('horizons', 'Показывать горизонты', 'multi', default=[], source=Source(RESPONSE, 'horizon'),
                  section=SECTION_DATA),
            Param('wells', 'Скважины', 'multi', default=[], dynamic=True, depends=('horizons',), auto='first:10',
                  empty='ничего', prefix='№ ', section=SECTION_DATA),
            Param('date_from', 'Период с', 'date', default=None, section=SECTION_DATA,
                  help='Пусто — с первого замера'),
            Param('date_to', 'по', 'date', default=None, section=SECTION_DATA, help='Пусто — до последнего замера'),
            Param('view', 'Вид графиков', 'choice', default='separate', options=VIEWS, section=SECTION_VIEW),
            Param('split', 'Построение', 'choice', default='horizon', options=SPLITS, section=SECTION_VIEW),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'wells':
            df = data[RESPONSE]
            everything = ordered(df.horizon)
            horizons = [h for h in params.get('horizons') or [] if h in everything] or everything
            return well_order(df, horizons)
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        sel = Selection(data, params)
        result = Result()
        f, original = sel.frame(sel.df), sel.frame(sel.raw)
        if not sel.wells:
            result.notes.append(Note('Выберите скважины.'))
        elif f.empty:
            result.notes.append(Note('Нет замеров в выбранном диапазоне.'))
        else:
            level = int(f.level.notna().sum()) if 'level' in f else 0
            pressure = int(f.pressure.notna().sum()) if 'pressure' in f else 0
            excluded = sum(int((original['_point_id'] + ':' + m).isin(data.excluded).sum())
                           for m in ('level', 'pressure') if m in original) if data.excluded and '_point_id' in original else 0
            result.summary = [
                Stat('Горизонтов', str(f.horizon.nunique())), Stat('Скважин', str(f.well.nunique())),
                Stat('Период', f'{f.date.min():%d.%m.%Y} – {f.date.max():%d.%m.%Y}'),
                Stat('Действующих уровней', str(level)), Stat('Замеров давления', str(pressure)),
                Stat('Исключено точек', str(excluded), 'Уровень и давление одного замера считаются отдельно')]
            result.notes.append(Note(VIEW_NOTE))
            result.charts.extend(self.charts(data, sel, f, params['view'], params['split']))
            result.tables.append(measurements_table(f))
        for field in ('level', 'pressure'):
            table = point_table(original, field, data.excluded)
            if table is not None:
                result.tables.append(table)
        if OBJECT in data.raw:
            table = object_point_table(data.raw[OBJECT], data.excluded)
            if table is not None:
                result.tables.append(table)
        return result

    @staticmethod
    def charts(data: Data, sel: Selection, f: pd.DataFrame, view: str, split: str) -> list[Chart]:
        raw = sel.raw
        pressure_horizons = set(ordered(raw.loc[raw.pressure.notna(), 'horizon'])) if 'pressure' in raw else set()
        palette = well_colors(sel.df.well)
        manometer = {str(w) for w in data.settings.get('manometer_wells', [])}
        object_pressure = data[OBJECT] if OBJECT in data else None
        column = 'horizon' if split == 'horizon' else 'well'
        sets = ({'Все выбранные': f} if split == 'all' else    # естественный порядок: 31, 45, 132
                {label: f[f[column].astype(str).eq(label)] for label in ordered(f[column])})
        out = []
        production = data[PRODUCTION] if PRODUCTION in data else None
        events = regime_events(production, f.date.min(), f.date.max()) if not f.empty else []
        for label, part in sets.items():
            for metric in (['level', 'pressure'] if view == 'separate' else [view]):
                if metric != 'combined' and (metric not in part or not part[metric].notna().any()):
                    continue
                title = chart_title(ordered(part.well), label, split) + ' · ' + METRIC_WORDS[metric]
                chart = response_chart(part, metric, title, f'response-{split}-{label}-{metric}', palette,
                                       object_pressure, manometer, split == 'well', pressure_horizons)
                chart.events = list(events)
                out.append(chart)
        return out

    # --- сохранённый вид: формат 5.8 (settings.panels.response) ---
    def save_state(self, params: dict[str, Any], data: Data) -> dict[str, Any]:
        sel = Selection(data, params)
        df = data.raw[RESPONSE]
        start = params['date_from'] or (df.date.min().strftime('%Y-%m-%d') if not df.empty else None)
        end = params['date_to'] or (df.date.max().strftime('%Y-%m-%d') if not df.empty else None)
        return {'wells': sel.wells, 'horizons': sel.horizons, 'working': params['working'],
                'dates': [d for d in (start, end) if d], 'view': params['view'], 'split': params['split']}

    def load_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        out = {k: state[k] for k in ('wells', 'horizons', 'view', 'split') if state.get(k) is not None}
        dates = list(state.get('dates') or [])
        if len(dates) == 2:
            out['date_from'], out['date_to'] = (pd.Timestamp(d).strftime('%Y-%m-%d') for d in dates)
        return out
