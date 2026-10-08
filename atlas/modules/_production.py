"""Общее для разделов «Производительность скважин» и «Гистограммы по эксплуатации».

Математика не переписана: сезоны, накопленный объём, средние, ранжирование и суммы групп —
``app.modules.production`` и ``app.modules.group_analysis`` из 5.8. Здесь выбор данных и представление.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from app.core.config import COLORS, ordered
from app.core.performance import index_for, select_wells
from app.modules import group_analysis
from app.modules import production as legacy
from app.modules.charts import DASH, well_colors

from ..thinning import screen_decimate

from ..contract import Axis, Chart, Column, Data, Module, Note, Option, Result, Series, Stat, Table, TableAction
from ..domain import DatasetKind
from ._group_charts import object_days
from ._events import gdi_events, on_cumulative, regime_events

PRODUCTION, GDI = DatasetKind.PRODUCTION, DatasetKind.GDI
KINDS = (Option('withdrawal', 'Отбор'), Option('injection', 'Закачка'))
DIRECTIONS = (Option('number', 'По номеру'), Option('desc', 'Больший дебит слева'), Option('asc', 'Больший дебит справа'))
POINT_BUDGET = 20000          # как в 5.8: бюджет точек на график, делится между кривыми
POINT_TABLE_LIMIT = 20000     # строк в таблице ручного фильтра
Q_UNIT = 'тыс. м³/сут'

AVERAGES_NOTE = ('Средний расход — по дням с положительным расходом. Накопленный объем считается по всему объекту. '
                 'Пропущенные даты не считаются простоями.')
CURVE_NOTE = ('Накопление по всему загруженному объекту в пределах периода. Подсказки отмечают пропуски. '
              'Экспорт использует все исходные точки.')
FILTER_NOTE = ('Отметьте «Исключить» и примените изменения. Исходные значения сохраняются; снятый флажок восстанавливает '
               'точку. Гистограммы и накопленный объем пересчитываются по действующим точкам.')
GROUP_NOTE = ('Сумма включает все скважины выбранной группы. Выбор кривых наложения не меняет сумму. Неполные наблюдения '
              'отмечены в подсказках; пропущенные даты не считаются простоями.')


# ---------- вспомогательное ----------

def wells_of(df: pd.DataFrame) -> list[str]:
    index = index_for(df)
    return ordered(index.wells) if index is not None else ordered(df.well.unique())


NEUTRAL_PREFIXES = ('Нейтральный период', 'Вне сезона')


def visible_periods(periods: list[str], settings: Mapping[str, Any] | None) -> list[str]:
    """Списки «Сезон» без нейтральных периодов, если в «Настройках» не включён их показ."""
    if settings and settings.get('show_neutral_periods'):
        return list(periods)
    return [p for p in periods if not str(p).startswith(NEUTRAL_PREFIXES)]


def periods_of(df: pd.DataFrame, kind: str) -> list[str]:
    index = index_for(df)
    return ordered(index.periods.get(kind, [])) if index is not None else ordered(df.loc[df.kind.eq(kind), 'period'])


def group_of(mapping: Mapping[str, Mapping[str, str]], well: str) -> str:
    return mapping.get(well, {}).get('group', 'Без группы')


def well_title(wells: list[str], group: str | None = None) -> str:
    if len(wells) == 1:
        return f'Скважина №{wells[0]}'
    if group:
        return f'Группа {group}'
    return 'Скважины №' + ', '.join(map(str, wells))


def x_step(maximum: float) -> float | None:
    """Шаг делений по оси накопленного объёма, как в 5.8."""
    for limit, step in ((1000, 1000), (300, 100), (150, 50), (60, 20), (30, 10), (15, 5), (3, 1)):
        if maximum >= limit:
            return float(step)
    return None


def kind_label(kind: str) -> str:
    return 'Отбор' if kind == 'withdrawal' else 'Закачка'


class Selection:
    """Что выбрал пользователь, приведённое к данным проекта (лишнее отбрасывается)."""

    def __init__(self, data: Data, params: Mapping[str, Any]):
        self.df = data[PRODUCTION]
        self.raw = data.raw[PRODUCTION]
        self.mapping = data.mapping
        self.excluded = data.excluded
        self.kind = params['kind']
        self.periods = [p for p in params['periods'] if p in periods_of(self.df, self.kind)]
        self.groups = [g for g in params['groups'] if g in groups_of(self.df, self.mapping)]
        self.params = params
        self.gdi = data[GDI] if GDI in data else None      # даты ГДИ — отметки на графике по дате

    def choices(self) -> list[str]:
        return [w for w in wells_of(self.df) if group_of(self.mapping, w) in self.groups]

    def wells(self) -> list[str]:
        chosen = set(self.params.get('wells') or [])
        ws = [w for w in self.choices() if w in chosen]
        return legacy.rank_wells(self.df, self.kind, self.periods, ws, self.params.get('direction', 'number'))


def groups_of(df: pd.DataFrame, mapping) -> list[str]:
    return ordered(group_of(mapping, w) for w in wells_of(df))


# ---------- графики ----------

def curve_chart(sel: Selection, ws: list[str], xmode: str, chart_id: str = 'production-curve') -> Chart:
    """Q по накопленному объёму объекта или по дате, как ``charts.production_curve``."""
    data = legacy.curve_data(sel.df, sel.kind, sel.periods, ws)
    by_cumulative = xmode == 'cumulative'
    x_axis = (Axis('Накопленный объем объекта', 'млн м³', from_zero=True,
                   step=x_step(float(data.cumulative.max())) if not data.empty else None)
              if by_cumulative else Axis('Дата', scale='time'))
    chart = Chart(chart_id, well_title(ws), x_axis, Axis('Суточный расход', Q_UNIT, from_zero=True))
    if data.empty:
        return chart
    colors, palette = legacy.period_colors(sel.df, sel.kind), well_colors(ws)
    groups = data.groupby(['well', 'period'], sort=False)
    limit = min(5000, max(4, POINT_BUDGET // max(1, groups.ngroups)))
    # Несколько скважин: цвет — скважина, стиль линии — период (легенда двумя рядами «Скважина» и «Период»).
    # Одна скважина — цвета периодов, как в 5.8; один период — цвета скважин.
    by_well = len(ws) > 1
    for (well, period), g in groups:
        points = len(g)
        g = screen_decimate(g, 'q', limit)
        single = len(sel.periods) == 1
        ids = g['_point_id'].where(~g.missing, '')
        status = g.missing.map({True: 'Нет записи: показан 0', False: 'Измерение'})
        labels = (g.date.dt.strftime('%d.%m.%Y') + ' · накопленный ' + g.cumulative.map('{:.2f}'.format) + ' млн м³ · '
                  + status + ' · ' + g.file.astype(str) + ' / ' + g.sheet.astype(str) + ' / строка ' + g['_row'].astype(str))
        chart.series.append(Series(
            str(period) if len(ws) == 1 else f'№ {well} · {period}',
            g.cumulative.to_numpy() if by_cumulative else g.date.to_numpy(), g.q.to_numpy(), 'line',
            color=palette[well] if single or by_well else colors[period],
            dash='solid' if single or not by_well else DASH[sel.periods.index(period) % len(DASH)], width=2.0,
            labels=labels.tolist(), ids=ids.tolist(), dataset=PRODUCTION, total=points,
            facets={'Скважина': f'№ {well}', 'Период': str(period)} if by_well and not single else None))
    start, end = data.date.min(), data.date.max()
    if by_cumulative:   # сезоны начинаются с нуля, отметки начала режима слились бы в одну точку: только ГДИ
        chart.events = on_cumulative(gdi_events(sel.gdi, ws, start, end), data)
    else:
        chart.events = regime_events(sel.df, start, end) + gdi_events(sel.gdi, ws, start, end)
    return chart


def histogram_charts(sel: Selection, ws: list[str], axis: str, size: int, prefix: str) -> list[Chart]:
    """Столбцы средних расходов; по ``size`` скважин на гистограмму, как ``charts.histogram``."""
    charts = []
    colors = legacy.period_colors(sel.df, sel.kind)
    parts = [ws[i:i + size] for i in range(0, len(ws), size)]
    for number, part in enumerate(parts):
        data = legacy.averages(sel.df, sel.kind, sel.periods, part)
        order = part if axis == 'well' else sel.periods
        chart = Chart(f'{prefix}-histogram-{number + 1}', well_title(part),
                      Axis('Скважина' if axis == 'well' else 'Период', scale='category', categories=list(order)),
                      Axis('Средний расход', Q_UNIT, from_zero=True))
        for i, key in enumerate(sel.periods if axis == 'well' else part):
            d = data[data.period.eq(key)] if axis == 'well' else data[data.well.eq(key)]
            d = d.set_index('well' if axis == 'well' else 'period').reindex(order).reset_index()
            labels = [('Нет данных за период' if bool(m) or pd.isna(a) else
                       f'Активных дней: {int(a)} · нулевых записей: {int(z)} · объем {v:.3f} млн м³')
                      for a, z, v, m in zip(d.active, d.zero, d.volume, d.missing)]
            chart.series.append(Series('Средний расход' if len(part) == 1 and axis == 'period' else str(key),
                                       d.iloc[:, 0].astype(str).tolist(), d.value.to_numpy(), 'bar',
                                       color=colors.get(key, COLORS[i % len(COLORS)]), labels=labels))
        charts.append(chart)
    return charts


GROUP_AXES = {'daily': ('Суммарный расход', 'тыс. м³/сут'), 'cumulative': ('Накопленный объем', 'млн м³'),
              'active': ('Работающих скважин с наблюдениями', ''), 'share': ('Доля группы в объекте', '%')}

OVERLAY_METRICS = ('daily', 'cumulative', 'active', 'share')     # метрики, у которых группы можно наложить друг на друга


def group_xmode(metric: str, xmode: str) -> str:
    """Накопленный объём группы по её же накопленному объёму — диагональ без смысла: берём объём объекта."""
    return 'object' if metric == 'cumulative' and xmode == 'group' else xmode


def _x_axis(xmode: str) -> Axis:
    if xmode == 'object':
        return Axis('Накопленный объем объекта', 'млн м³', from_zero=True)
    if xmode == 'group':
        return Axis('Накопленный объем группы', 'млн м³', from_zero=True)
    return Axis('Дата', scale='time')


def object_lookup(sel: Selection, xmode: str, metric: str) -> dict:
    """По периодам: накопленный объём объекта (``cum``) и его суточная сумма (``total``); строится, только если нужна."""
    if group_xmode(metric, xmode) != 'object' and metric != 'share':
        return {}
    days = object_days(sel)
    return {'cum': {p: g.set_index('date').cum for p, g in days.groupby('period', sort=False)},
            'total': {p: g.set_index('date').total for p, g in days.groupby('period', sort=False)}}


def group_curves(sel: Selection, daily: pd.DataFrame, metric: str, xmode: str, objects: dict) -> list[tuple[str, pd.DataFrame]]:
    """Суммарная кривая группы по периодам: колонки ``x`` (дата или накопленный объём), ``value``, ``label`` (подсказка)."""
    xmode = group_xmode(metric, xmode)
    out = []
    for period, g in daily.groupby('period', sort=False) if not daily.empty else []:
        g = g.copy()
        if metric == 'share':
            obj = g.date.map(objects['total'].get(period, pd.Series(dtype=float))) / 1000
            g['value'] = g.total / 1000 / obj.replace(0, np.nan) * 100
        else:
            g['value'] = (g.total / 1000 if metric == 'daily' else g.cumulative if metric == 'cumulative'
                          else g.active.where(g.observed.gt(0)))
        if xmode == 'object':
            g['x'] = g.date.map(objects['cum'].get(period, pd.Series(dtype=float)))
            g = g[g.x.notna()]
        elif xmode == 'group':
            g['x'] = g.cumulative.ffill().fillna(0)
        else:
            g['x'] = g.date
        g = screen_decimate(g, 'value')
        g['label'] = ('Наблюдений: ' + g.observed.fillna(0).astype(int).astype(str) + ' / ' + g.expected.astype(int).astype(str)
                      + ' скважин · покрытие ' + g.coverage.fillna(0).map('{:.1f}'.format) + '%')
        out.append((period, g))
    return out


def group_chart(sel: Selection, daily: pd.DataFrame, wells: list[str], group: str, metric: str,
                overlay: list[str], xmode: str = 'date', objects: dict | None = None) -> Chart:
    """Сумма по группе по периодам и наложение отдельных скважин, как ``group_analysis.figure``.

    ``xmode``: ``date`` — по дате, ``object`` — по накопленному объёму объекта за период (как «Q / накопленный объем
    объекта» у скважин), ``group`` — по накопленному объёму самой группы.
    """
    xmode = group_xmode(metric, xmode)
    objects = object_lookup(sel, xmode, metric) if objects is None else objects
    chart = Chart(f'production-group-{group}', f'Группа {group}', _x_axis(xmode), Axis(*GROUP_AXES[metric], from_zero=True))
    colors, palette = legacy.period_colors(sel.df, sel.kind), well_colors(wells)
    for period, g in group_curves(sel, daily, metric, xmode, objects):
        chart.series.append(Series('Сумма · ' + period, g.x.to_numpy(), g.value.to_numpy(), 'line',
                                   color=colors.get(period), width=3.0, labels=g.label.tolist(),
                                   facets={'Кривая': 'Сумма', 'Период': str(period)}))
    if metric in ('daily', 'cumulative'):
        d = select_wells(sel.df, [w for w in overlay if w in wells])
        d = d[d.kind.eq(sel.kind) & d.period.isin(sel.periods)]
        group_cum = {p: g.set_index('date').cumulative.ffill() for p, g in daily.groupby('period', sort=False)} if xmode == 'group' else {}
        for (well, period), g in d.groupby(['well', 'period'], sort=False):
            calendar = pd.date_range(g.date.min(), g.date.max())
            g = g.set_index('date').reindex(calendar)
            values = g.q.where(~g.get('_excluded', pd.Series(False, index=g.index)).fillna(False))
            g['value'] = values / 1000 if metric == 'daily' else values.cumsum() / 1e6
            g['date'] = calendar
            if xmode == 'object':
                g['x'] = g.date.map(objects['cum'].get(period, pd.Series(dtype=float)))
            elif xmode == 'group':
                g['x'] = g.date.map(group_cum.get(period, pd.Series(dtype=float)))
            else:
                g['x'] = g.date
            g = screen_decimate(g[g.x.notna()], 'value')
            chart.series.append(Series(f'№ {well} · {period}', g.x.to_numpy(), g.value.to_numpy(), 'line',
                                       color=palette[well], width=1.4,
                                       facets={'Кривая': f'№ {well}', 'Период': str(period)}))
    if not daily.empty and xmode == 'date':
        chart.events = regime_events(sel.df, daily.date.min(), daily.date.max())
    return chart


def groups_overlay_chart(sel: Selection, dailies: dict[str, pd.DataFrame], metric: str, xmode: str) -> Chart:
    """Кривые выбранных групп на одной координатной плоскости: цвет — группа, штрих — период, легенда по группам."""
    xmode = group_xmode(metric, xmode)
    objects = object_lookup(sel, xmode, metric)
    title = {'daily': 'суммарный расход', 'cumulative': 'накопленный объем', 'active': 'работающие скважины',
             'share': 'доля в объекте'}[metric]
    chart = Chart('production-groups-overlay', f'Группы на одном графике: {title}', _x_axis(xmode),
                  Axis(*GROUP_AXES[metric], from_zero=True))
    palette = well_colors(list(dailies))
    single = len(sel.periods) == 1
    for group, daily in dailies.items():
        for period, g in group_curves(sel, daily, metric, xmode, objects):
            chart.series.append(Series(
                group if single else f'{group} · {period}', g.x.to_numpy(), g.value.to_numpy(), 'line',
                color=palette[group], dash='solid' if single else DASH[sel.periods.index(period) % len(DASH)], width=2.4,
                labels=g.label.tolist(), facets={'Группа': group} if single else {'Группа': group, 'Период': str(period)}))
    bounds = [(d.date.min(), d.date.max()) for d in dailies.values() if not d.empty]
    if bounds and xmode == 'date':
        chart.events = regime_events(sel.df, min(b[0] for b in bounds), max(b[1] for b in bounds))
    return chart


# ---------- таблицы ----------

def averages_table(sel: Selection, ws: list[str], a: pd.DataFrame | None = None) -> Table:
    a = legacy.averages(sel.df, sel.kind, sel.periods, ws) if a is None else a
    a = a.assign(missing=a.missing.map({True: 'да', False: ''}))
    return Table('averages', 'Расчетные значения', a, [
        Column('well', 'Скважина'), Column('period', 'Период'),
        Column('value', 'Средний расход', Q_UNIT, 2, 'number'),
        Column('active', 'Активных дней', kind='number'), Column('zero', 'Нулевых записей', kind='number'),
        Column('volume', 'Объем', 'млн м³', 3, 'number'), Column('missing', 'Нет данных')],
        note=AVERAGES_NOTE, collapsed=True)


def group_table(group: str, daily: pd.DataFrame) -> Table:
    columns = [Column('date', 'Дата', kind='date'), Column('period', 'Период'),
               Column('total', 'Суммарный расход', 'м³/сут', 0, 'number'),
               Column('observed', 'Скважин с данными', kind='number'), Column('active', 'Работают', kind='number'),
               Column('cumulative', 'Объем', 'млн м³', 3, 'number'), Column('coverage', 'Покрытие', '%', 1, 'number'),
               Column('expected', 'Всего скважин', kind='number')]
    return Table(f'group-{group}', f'Расчетные показатели · {group}', daily, columns, collapsed=True)


def point_table(sel: Selection, ws: list[str]) -> Table | None:
    """Ручной фильтр точек: исходные значения выбранных скважин, как ``PointControls.tools``."""
    part = select_wells(sel.raw, ws)
    part = part[part.kind.eq(sel.kind) & part.period.isin(sel.periods)]
    if part.empty:
        return None
    total = len(part)
    part = part.sort_values(['date', 'well'], ascending=[False, True], kind='stable').head(POINT_TABLE_LIMIT)
    part = part.assign(_excluded=part['_point_id'].isin(sel.excluded),
                       _reason=part['_point_id'].map(lambda i: (sel.excluded.get(i) or {}).get('reason', '')),
                       kind=part.kind.map(kind_label))
    columns = [Column('well', 'Скважина'), Column('date', 'Дата', kind='date'), Column('kind', 'Тип'),
               Column('period', 'Период'), Column('q', 'Q', 'м³/сут', 0, 'number')]
    for key, label, unit, decimals in (('work_hours', 'Часы работы', 'ч', 1), ('gas_volume_m3', 'Объем газа', 'м³', 0),
                                       ('water_volume_m3', 'Объем воды', 'м³', 2), ('water_rate', 'Расход воды', 'м³/сут', 2)):
        if key in part:
            columns.append(Column(key, label, unit, decimals, 'number'))
    for key, label in (('water_flag', 'Вода'), ('file', 'Файл'), ('sheet', 'Лист'), ('_row', 'Строка')):
        if key in part:
            columns.append(Column(key, label, kind='number' if key == '_row' else 'text'))
    columns.append(Column('_reason', 'Причина исключения'))
    note = FILTER_NOTE + (f' Показаны {POINT_TABLE_LIMIT:,} самых свежих точек из {total:,}: сузьте выбор скважин или '
                          'периодов, чтобы увидеть остальные.'.replace(',', ' ') if total > POINT_TABLE_LIMIT else '')
    return Table('points', 'Ручной фильтр точек', part.reset_index(drop=True), columns, note=note, collapsed=True,
                 action=TableAction('exclude', PRODUCTION, '_point_id', 'Применить ручной фильтр',
                                    checked_column='_excluded'))


# ---------- строка итогов ----------

def period_stat(periods: list[str]) -> Stat:
    if not periods:
        return Stat('Периоды', 'нет')
    value = periods[0] if len(periods) == 1 else f'{periods[0]} – {periods[-1]}'
    return Stat('Периоды' if len(periods) > 1 else 'Период', value,
                ', '.join(periods) if len(periods) > 2 else '')


def summary(sel: Selection, ws: list[str], averages: pd.DataFrame) -> list[Stat]:
    """Скважины, периоды, средний расход по выбранным скважинам и периодам, исключённые точки выборки."""
    values = pd.to_numeric(averages.value, errors='coerce') if 'value' in averages else pd.Series(dtype=float)
    mean = values.mean()
    part = select_wells(sel.raw, ws)
    part = part[part.kind.eq(sel.kind) & part.period.isin(sel.periods)]
    excluded = int(part['_point_id'].isin(sel.excluded).sum()) if sel.excluded and '_point_id' in part else 0
    ordered_periods = [p for p in periods_of(sel.df, sel.kind) if p in sel.periods]
    return [
        Stat('Скважин', str(len(ws))),
        Stat('Режим', kind_label(sel.kind)),
        period_stat(ordered_periods),
        Stat('Средний расход', '—' if pd.isna(mean) else f'{mean:.2f}'.replace('.', ',') + ' ' + Q_UNIT,
             'Среднее средних по скважинам и периодам; дни с положительным расходом'),
        Stat('Исключено точек', str(excluded), 'В выбранных скважинах и периодах'),
    ]


# ---------- общая часть модулей ----------

class ProductionBase(Module):
    """Списки, зависящие друг от друга: группы → скважины, режим → периоды."""

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        df, mapping = data[PRODUCTION], data.mapping
        if name == 'groups':
            return groups_of(df, mapping)
        if name == 'periods':
            return visible_periods(periods_of(df, params.get('kind') or 'withdrawal'), data.settings)
        if name in ('wells', 'overlay'):
            groups = set(params.get('groups') or [])
            return [w for w in wells_of(df) if group_of(mapping, w) in groups]
        return super().options(name, data, params)

    @staticmethod
    def common_tables(result: Result, sel: Selection, ws: list[str]) -> None:
        averages = legacy.averages(sel.df, sel.kind, sel.periods, ws)
        result.summary = summary(sel, ws, averages)
        result.tables.append(averages_table(sel, ws, averages))
        points = point_table(sel, ws)
        if points is not None:
            result.tables.append(points)

    @staticmethod
    def nothing_selected(result: Result) -> Result:
        result.notes.append(Note('Выберите скважины и периоды.'))
        return result
