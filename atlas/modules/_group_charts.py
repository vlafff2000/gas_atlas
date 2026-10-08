"""Графики суммарных показателей группы: доли скважин, гибрид «столбцы + кривая», Парето, группа к объекту.

Данные те же, что у ``group_analysis.daily`` (5.8): исключённые точки не учитываются, пропуски не считаются нулём.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from atlas.engine.core.performance import select_wells
from atlas.engine.modules.charts import well_colors

from ..contract import Axis, Chart, Series
from ..thinning import screen_decimate

SHARE_METRICS = ('shares', 'hybrid', 'pareto', 'vs_object')
Q_UNIT = 'тыс. м³/сут'


def _valid(d: pd.DataFrame) -> pd.Series:
    return d.q.where(~d.get('_excluded', pd.Series(False, index=d.index)).fillna(False))


def well_days(sel, wells: list[str]) -> pd.DataFrame:
    """Суточные объёмы скважин группы за выбранные периоды: date, well, period, v (м³)."""
    d = select_wells(sel.df, wells)
    d = d[d.kind.eq(sel.kind) & d.period.isin(sel.periods)]
    return d.assign(v=_valid(d))[['date', 'well', 'period', 'v']]


def object_days(sel) -> pd.DataFrame:
    """Сумма по всему объекту: period, date, total (м³/сут), cum (млн м³ с начала периода)."""
    d = sel.df[sel.df.kind.eq(sel.kind) & sel.df.period.isin(sel.periods)]
    d = d.assign(v=_valid(d))
    a = d.groupby(['period', 'date'], sort=False).v.sum(min_count=1).rename('total').reset_index()
    a = a.sort_values(['period', 'date'])
    a['cum'] = a.groupby('period', sort=False).total.transform(lambda s: s.fillna(0).cumsum()) / 1e6
    return a


def _wells_order(d: pd.DataFrame) -> list[str]:
    return d.groupby('well').v.sum().sort_values(ascending=False).index.tolist()


def share_chart(sel, d: pd.DataFrame, group: str) -> Chart:
    """Доля скважин в накопленном объёме группы, 100 % стопкой; по одному графику на период."""
    chart = Chart(f'production-group-{group}-shares', f'Группа {group} · доля скважин в накопленном объёме',
                  Axis('Дата', scale='time'), Axis('Доля накопленного объёма группы', '%', from_zero=True, maximum=100))
    palette = well_colors(sorted(d.well.unique()))
    for period, g in d.groupby('period', sort=False):
        cum = g.pivot_table(index='date', columns='well', values='v', aggfunc='sum').sort_index()
        cum = cum.reindex(pd.date_range(cum.index.min(), cum.index.max())).fillna(0).cumsum()
        total = cum.sum(axis=1).replace(0, np.nan)
        for well in _wells_order(g):
            share = cum[well] / total * 100
            part = pd.DataFrame({'date': cum.index, 'value': share.to_numpy(), 'cum': cum[well].to_numpy() / 1e6})
            part = screen_decimate(part, 'value')
            labels = ('накопленный ' + part.cum.map('{:.2f}'.format) + ' млн м³').tolist()
            chart.series.append(Series(f'№ {well} · {period}' if len(sel.periods) > 1 else f'№ {well}',
                                       part.date.to_numpy(), part.value.to_numpy(), 'line', color=palette[well],
                                       width=1.0, labels=labels, stack=f'share-{period}',
                                       facets={'Скважина': f'№ {well}', 'Период': str(period)}))
    return chart


def hybrid_chart(sel, d: pd.DataFrame, daily: pd.DataFrame, group: str) -> Chart:
    """Столбцы — объём группы за месяц по скважинам (стопка), линия справа — суточный расход группы."""
    chart = Chart(f'production-group-{group}-hybrid', f'Группа {group} · месячные объёмы и суточный расход',
                  Axis('Месяц', scale='time'), Axis('Объём за месяц', 'млн м³', from_zero=True),
                  y2=Axis('Суммарный расход', Q_UNIT, from_zero=True))
    palette = well_colors(sorted(d.well.unique()))
    d = d.assign(month=d.date.dt.to_period('M').dt.to_timestamp())
    month = d.pivot_table(index='month', columns='well', values='v', aggfunc='sum') / 1e6
    for well in _wells_order(d):
        m = month[well].dropna()
        chart.series.append(Series(f'№ {well}', m.index.to_numpy(), m.to_numpy(), 'bar', color=palette[well],
                                   stack='month', facets={'Скважина': f'№ {well}'}))
    for period, g in daily.groupby('period', sort=False) if not daily.empty else []:
        part = screen_decimate(g.assign(value=g.total / 1000), 'value')
        chart.series.append(Series(f'Суточный расход · {period}', part.date.to_numpy(), part.value.to_numpy(), 'line',
                                   width=2.4, axis='y2', facets={'Кривая': 'Суточный расход', 'Период': str(period)}))
    return chart


def pareto_chart(sel, d: pd.DataFrame, group: str) -> Chart:
    """Вклад скважин в накопленный объём за выбранные периоды по убыванию и линия накопленной доли."""
    order = _wells_order(d)
    volume = d.groupby('well').v.sum().reindex(order).fillna(0) / 1e6
    share = (volume.cumsum() / volume.sum() * 100) if volume.sum() > 0 else volume
    cats = [f'№ {w}' for w in order]
    chart = Chart(f'production-group-{group}-pareto', f'Группа {group} · вклад скважин (Парето)',
                  Axis('Скважина', scale='category', categories=cats), Axis('Накопленный объём', 'млн м³', from_zero=True),
                  y2=Axis('Накопленная доля', '%', from_zero=True, maximum=100))
    labels = [f'доля скважины {v / volume.sum() * 100:.1f} %' if volume.sum() > 0 else '' for v in volume]
    chart.series.append(Series('Объём скважины', cats, volume.to_numpy(), 'bar', color='', labels=labels))
    chart.series.append(Series('Накопленная доля', cats, share.to_numpy(), 'line', axis='y2', width=2.2, markers=True))
    return chart


def vs_object_chart(sel, daily: pd.DataFrame, obj: pd.DataFrame, group: str) -> Chart:
    """Суточный расход группы и объекта (левая ось) и доля группы в объекте (правая)."""
    chart = Chart(f'production-group-{group}-object', f'Группа {group} · группа и объект',
                  Axis('Дата', scale='time'), Axis('Суточный расход', Q_UNIT, from_zero=True),
                  y2=Axis('Доля группы в объекте', '%', from_zero=True, maximum=100))
    for period, g in daily.groupby('period', sort=False) if not daily.empty else []:
        o = obj[obj.period.eq(period)].set_index('date').total
        m = g.assign(obj=g.date.map(o), value=g.total / 1000)
        m['obj'] = m.obj / 1000
        m['share'] = m.value / m.obj.replace(0, np.nan) * 100
        for name, col, axis, width in (('Группа', 'value', 'y', 2.6), ('Объект', 'obj', 'y', 1.6),
                                       ('Доля группы', 'share', 'y2', 1.4)):
            part = screen_decimate(m[['date', col]].rename(columns={col: 'value'}), 'value')
            chart.series.append(Series(f'{name} · {period}', part.date.to_numpy(), part.value.to_numpy(), 'line',
                                       axis=axis, width=width, dashed=name == 'Доля группы',
                                       facets={'Кривая': name, 'Период': str(period)}))
    return chart
