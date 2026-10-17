"""Авторский надзор: графики сезона отбора и закачки, которые строятся по данным проекта.

Каждая функция принимает уже посчитанные таблицы (см. ``an_report``) и отдаёт ``Chart`` или None, если для графика нет данных.
Единицы: расход — тыс. м³/сут, накопленный объём — млн м³, давление — абсолютное, кгс/см².
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contract import Axis, Chart, Series

Q_UNIT = 'тыс. м³/сут'
P_UNIT = 'кгс/см²'
WHAT = {'withdrawal': ('отбор', 'отбора', 'Суточный отбор'), 'injection': ('закачка', 'закачки', 'Суточная закачка')}
WHOLE = 'Весь сезон'


def daily_of(prod: pd.DataFrame, kind: str, period: str) -> tuple[pd.Series, pd.Series]:
    """Суточный расход объекта (м³/сут) и число работающих скважин по датам сезона; только сутки с расходом."""
    pos = prod[prod.kind.eq(kind) & prod.period.eq(period) & prod.q.gt(0)]
    return pos.groupby('date').q.sum().sort_index(), pos.groupby('date').well.nunique()


def pressure_points(pressure: pd.DataFrame | None, start: Any, stop: Any) -> pd.DataFrame | None:
    if pressure is None or pressure.empty:
        return None
    p = pressure.dropna(subset=['pressure'])
    p = p[p.date.between(pd.Timestamp(start), pd.Timestamp(stop))].sort_values('date', kind='stable')
    return p if not p.empty else None


def curve_chart(kind: str, period: str, daily: pd.Series, wells: pd.Series, pressure: pd.DataFrame | None) -> Chart | None:
    """Суточный расход объекта по накопленному объёму за сезон; Рпл — на правой оси (точки по датам замеров).
    Число работающих скважин — в подсказке к точке."""
    if daily.empty:
        return None
    noun, genitive, _ = WHAT[kind]
    cum = daily.cumsum() / 1e6
    chart = Chart(f'an-curve-{kind}-{period}', f'Расход, давление и скважины от накопленного объёма {genitive} · {period}',
                  Axis(f'Накопленный {noun} за сезон', 'млн м³', from_zero=True),
                  Axis('Суточный расход', Q_UNIT, from_zero=True), y2=Axis('Рпл, абс.', P_UNIT))
    labels = [f'{d:%d.%m.%Y} · скважин в работе: {int(wells[d])}' for d in daily.index]
    chart.series.append(Series('Суточный расход', cum.to_numpy(), (daily / 1000).to_numpy(), 'line', labels=labels, width=1.0))
    p = pressure_points(pressure, daily.index.min(), daily.index.max())
    if p is not None:
        x = [cum[cum.index <= d].iloc[-1] if d >= cum.index[0] else 0.0 for d in p.date]
        chart.series.append(Series('Рпл, абс.', x, p.pressure.to_numpy(), 'points', axis='y2'))
    return chart


def rate_chart(kind: str, period: str, daily: pd.Series, wells: pd.Series, pressure: pd.DataFrame | None) -> Chart | None:
    """Суточный расход объекта по датам сезона; Рпл — точки на правой оси."""
    if daily.empty:
        return None
    genitive = WHAT[kind][1]
    chart = Chart(f'an-rate-{kind}-{period}', f'Суточный расход {genitive} и пластовое давление · {period}',
                  Axis('Дата', scale='time'), Axis('Суточный расход', Q_UNIT, from_zero=True), y2=Axis('Рпл, абс.', P_UNIT))
    labels = [f'скважин в работе: {int(wells[d])}' for d in daily.index]
    chart.series.append(Series('Суточный расход', daily.index.to_numpy(), (daily / 1000).to_numpy(), 'line',
                               labels=labels, width=1.0))
    p = pressure_points(pressure, daily.index.min(), daily.index.max())
    if p is not None:
        chart.series.append(Series('Рпл, абс.', p.date.to_numpy(), p.pressure.to_numpy(), 'points', axis='y2'))
    return chart


def wells_chart(kind: str, period: str, wells: pd.Series) -> Chart | None:
    """Число скважин с расходом по суткам сезона."""
    if wells.empty:
        return None
    chart = Chart(f'an-wells-{kind}-{period}', f'Скважины в работе по суткам · {period}',
                  Axis('Дата', scale='time'), Axis('Скважин в работе', 'скв.', from_zero=True))
    chart.series.append(Series('Скважин в работе', wells.index.to_numpy(), wells.to_numpy(float), 'line', width=1.0))
    return chart


def cumulative_chart(kind: str, period: str, daily: pd.Series) -> Chart | None:
    """Накопленный за сезон объём по датам, млн м³."""
    if daily.empty:
        return None
    noun = WHAT[kind][0]
    chart = Chart(f'an-cumulative-{kind}-{period}', f'Накопленный {noun} за сезон · {period}',
                  Axis('Дата', scale='time'), Axis(f'Накопленный {noun}', 'млн м³', from_zero=True))
    chart.series.append(Series(f'Накопленный {noun}', daily.index.to_numpy(), (daily.cumsum() / 1e6).to_numpy(), 'line', width=1.2))
    return chart


def pressure_chart(pressure: pd.DataFrame | None, period: str, start: Any, stop: Any) -> Chart | None:
    """Динамика среднего пластового давления объекта за сезон (факт)."""
    p = pressure_points(pressure, start, stop)
    if p is None:
        return None
    chart = Chart(f'an-pressure-{period}', f'Динамика пластового давления · {period}',
                  Axis('Дата', scale='time'), Axis('Рпл, абс.', P_UNIT))
    chart.series.append(Series('Среднее пластовое давление', p.date.to_numpy(), p.pressure.to_numpy(), 'line', markers=True))
    return chart


def group_means_chart(kind: str, period: str, means: pd.DataFrame) -> Chart | None:
    """Средний суточный расход за сезон по группам (строки «Весь сезон» таблицы средних)."""
    part = means[means.period.eq(WHOLE) & ~means.scope.eq('Объект')]
    if part.empty:
        return None
    cats = [str(g) for g in part.scope]
    chart = Chart(f'an-group-means-{kind}-{period}', f'Средний суточный расход по группам · {period}',
                  Axis('Группа', scale='category', categories=cats), Axis('Средний суточный расход', Q_UNIT, from_zero=True))
    chart.series.append(Series('Средний суточный расход', cats, part['mean'].to_numpy(float), 'bar',
                               labels=[f'суток с расходом: {int(d)}' for d in part.days]))
    return chart


def monthly_groups_chart(kind: str, period: str, means: pd.DataFrame) -> Chart | None:
    """Средний суточный расход по месяцам сезона, столбцы разбиты по группам (сумма групп — расход объекта)."""
    part = means[~means.period.eq(WHOLE) & ~means.scope.eq('Объект')]
    if part.empty:
        return None
    months = list(dict.fromkeys(part.period))
    chart = Chart(f'an-monthly-groups-{kind}-{period}', f'Средний суточный расход по месяцам и группам · {period}',
                  Axis('Месяц', scale='category', categories=months), Axis('Средний суточный расход', Q_UNIT, from_zero=True))
    for group, rows in part.groupby('scope', sort=False):
        by = rows.set_index('period')['mean']
        chart.series.append(Series(str(group), months, np.array([by.get(m, np.nan) for m in months], float), 'bar',
                                   group=str(group), stack='groups'))
    return chart


def fund_chart(kind: str, period: str, fund: pd.DataFrame) -> Chart | None:
    """Фонд и работавшие за сезон скважины по группам (без строки «Всего»)."""
    part = fund[~fund.group.eq('Всего')]
    if part.empty:
        return None
    cats = [str(g) for g in part.group]
    chart = Chart(f'an-fund-{kind}-{period}', f'Фонд и работавшие скважины по группам · {period}',
                  Axis('Группа', scale='category', categories=cats), Axis('Скважин', 'скв.', from_zero=True))
    chart.series.append(Series('Фонд', cats, part.fund.to_numpy(float), 'bar'))
    chart.series.append(Series('Работало за сезон', cats, part.working.to_numpy(float), 'bar',
                               labels=[f'доля работавших {v:.1f} %' for v in part.percent]))
    return chart


def water_chart(period: str, water: pd.DataFrame, start: Any, stop: Any) -> Chart | None:
    """Вынос воды по объекту (м³/сут) и суточный водный фактор на правой оси."""
    w = water[water.date.between(pd.Timestamp(start), pd.Timestamp(stop))].sort_values('date')
    day, wf = w[w.water_day.notna()], w[w.wf.notna()]
    if day.empty and wf.empty:
        return None
    chart = Chart(f'an-water-{period}', f'Вынос воды и водный фактор · {period}',
                  Axis('Дата', scale='time'), Axis('Вынос воды', 'м³/сут', from_zero=True),
                  y2=Axis('Водный фактор', 'л/тыс. м³', from_zero=True))
    if not day.empty:
        chart.series.append(Series('Вынос воды', day.date.to_numpy(), day.water_day.to_numpy(float), 'line',
                                   markers=True, width=1.0))
    if not wf.empty:
        chart.series.append(Series('Водный фактор, суточный', wf.date.to_numpy(), wf.wf.to_numpy(float), 'line',
                                   axis='y2', width=1.0, dashed=True))
    cum = w[w.wf_cum.notna()]
    if not cum.empty:
        chart.series.append(Series('Водный фактор, накопленный', cum.date.to_numpy(), cum.wf_cum.to_numpy(float), 'line',
                                   axis='y2', width=1.0))
    return chart


def gas_in_place_chart(period: str, factor: pd.DataFrame | None, start: Any, stop: Any) -> Chart | None:
    """Объём газа в пласте по суткам сезона (набор «Вынос воды по объекту»), млрд м³."""
    if factor is None or 'gas_in_place' not in factor or factor.empty:
        return None
    f = factor.assign(date=pd.to_datetime(factor.date), gas=pd.to_numeric(factor.gas_in_place, errors='coerce'))
    f = f[f.date.between(pd.Timestamp(start), pd.Timestamp(stop)) & f.gas.notna()].sort_values('date')
    if f.empty:
        return None
    chart = Chart(f'an-gas-in-place-{period}', f'Объём газа в пласте · {period}',
                  Axis('Дата', scale='time'), Axis('Объём газа в пласте', 'млрд м³'))
    chart.series.append(Series('Объём газа в пласте', f.date.to_numpy(), (f.gas / 1e6).to_numpy(float), 'line', width=1.2))
    return chart


def annulus_charts(wells: pd.DataFrame, label: str) -> list[Chart]:
    """Давление МКД и расход из МКП по скважинам с замерами (максимумы за выбранные сезоны), по убыванию."""
    out: list[Chart] = []
    for key, title, axis, unit in (('p_max', 'Давление МКД по скважинам', 'Давление МКД', P_UNIT),
                                   ('q_max', 'Расход из МКП по скважинам', 'Расход из МКП', 'м³/сут')):
        part = wells[wells[key] > 0].sort_values(key, ascending=False)
        if part.empty:
            continue
        cats = [str(int(w)) for w in part.well]
        chart = Chart(f'an-annulus-{key}', f'{title} · {label}', Axis('Скважина №', scale='category', categories=cats),
                      Axis(axis, unit, from_zero=True))
        chart.series.append(Series(axis, cats, part[key].to_numpy(float), 'bar', labels=[f'группа {g}' for g in part.group]))
        out.append(chart)
    return out

