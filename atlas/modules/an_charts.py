"""Авторский надзор: графики сезона отбора и закачки, которые строятся по данным проекта.

Каждая функция принимает уже посчитанные таблицы (см. ``an_report``) и отдаёт ``Chart`` или None, если для графика нет данных.
Единицы: расход — тыс. м³/сут, накопленный объём — млн м³, давление — абсолютное, кгс/см².
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from ..contract import Axis, Chart, Series

Q_UNIT = 'тыс. м³/сут'
P_UNIT = 'кгс/см²'
WHAT = {'withdrawal': ('отбор', 'отбора', 'Суточный отбор'), 'injection': ('закачка', 'закачки', 'Суточная закачка')}
WHOLE = 'Весь сезон'
MONTHS = ('январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь')


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


SHOW = (('rate', 'Суточный расход'), ('pressure', 'Среднее Рпл (замеры)'), ('wells', 'Скважин в работе'),
        ('cumulative', 'Накопленный объём'), ('water', 'Вынос воды'), ('wf', 'Водный фактор, суточный'),
        ('wf_cum', 'Водный фактор, накопленный'), ('gas', 'Объём газа в пласте'))
SHOW_DEFAULT = ('Суточный расход', 'Среднее Рпл (замеры)', 'Скважин в работе')      # в списке параметра значения — подписи
SHOW_KEY = {label: key for key, label in SHOW}


def canvas_chart(kind: str, period: str, show: list[str], daily: pd.Series, wells: pd.Series, pressure: pd.DataFrame | None,
                 water: pd.DataFrame | None = None, factor: pd.DataFrame | None = None) -> Chart | None:
    """Единый холст сезона: ряды по датам на выбор. Левая шкала — первая из выбранных величин, вторая — справа,
    третья — на дополнительной оси справа (если величин больше трёх, остальные делят её; единицы — в подписи оси)."""
    if daily.empty:
        return None
    genitive = WHAT[kind][1]
    start, stop = daily.index.min(), daily.index.max()
    show = [SHOW_KEY.get(v, v) for v in show]
    items: list[tuple[str, str, str, Series]] = []         # (ключ, подпись шкалы, единица, ряд)
    if 'rate' in show:
        labels = [f'скважин в работе: {int(wells[d])}' for d in daily.index]
        items.append(('rate', 'Суточный расход', Q_UNIT, Series('Суточный расход', daily.index.to_numpy(),
                                                                (daily / 1000).to_numpy(), 'line', width=1.0, labels=labels)))
    if 'cumulative' in show:
        items.append(('cumulative', f'Накопленный {WHAT[kind][0]}', 'млн м³',
                      Series(f'Накопленный {WHAT[kind][0]}', daily.index.to_numpy(), (daily.cumsum() / 1e6).to_numpy(), 'line', width=1.2)))
    p = pressure_points(pressure, start, stop) if 'pressure' in show else None
    if p is not None:
        items.append(('pressure', 'Рпл, абс.', P_UNIT, Series('Среднее Рпл, абс.', p.date.to_numpy(), p.pressure.to_numpy(), 'points')))
    if 'wells' in show:
        items.append(('wells', 'Скважин в работе', 'скв.', Series('Скважин в работе', wells.index.to_numpy(), wells.to_numpy(float),
                                                                    'points', symbol='square')))
    if water is not None and not water.empty:
        w = water[water.date.between(start, stop)].sort_values('date')
        for key, col, label, unit, name, line in (('water', 'water_day', 'Вынос воды', 'м³/сут', 'Вынос воды', {}),
                                                  ('wf', 'wf', 'Водный фактор', 'л/тыс. м³', 'Водный фактор, суточный', {'dashed': True}),
                                                  ('wf_cum', 'wf_cum', 'Водный фактор', 'л/тыс. м³', 'Водный фактор, накопленный', {})):
            part = w[w[col].notna()] if key in show else w.iloc[0:0]
            if not part.empty:
                items.append((key, label, unit, Series(name, part.date.to_numpy(), part[col].to_numpy(float), 'line', width=1.0, **line)))
    if 'gas' in show and factor is not None and 'gas_in_place' in factor and not factor.empty:
        f = factor.assign(date=pd.to_datetime(factor.date), gas=pd.to_numeric(factor.gas_in_place, errors='coerce'))
        f = f[f.date.between(start, stop) & f.gas.notna()].sort_values('date')
        if not f.empty:
            items.append(('gas', 'Объём газа в пласте', 'млрд м³', Series('Объём газа в пласте', f.date.to_numpy(),
                                                                          (f.gas / 1e6).to_numpy(float), 'line', width=1.2)))
    if not items:
        return None
    families = list(dict.fromkeys((label, unit) for _, label, unit, _ in items))        # величины в порядке первого появления
    main = families[0]
    side = {fam: ('y2' if n == 0 else 'y3') for n, fam in enumerate(families[1:])}       # третья и следующие величины делят ось y3

    def merged(keys):
        return Axis(' · '.join(dict.fromkeys(label for label, _ in keys)), ' · '.join(dict.fromkeys(unit for _, unit in keys)))

    chart = Chart(f'an-canvas-{kind}-{period}', f'Сезон {genitive}: ряды по суткам · {period}',
                  Axis('Дата', scale='time'), Axis(main[0], main[1], from_zero=True),
                  y2=merged([f for f, a in side.items() if a == 'y2']) if side else None,
                  y3=merged([f for f, a in side.items() if a == 'y3']) if 'y3' in side.values() else None)
    for _, label, unit, series in items:
        if (label, unit) != main:
            series = replace(series, axis=side[(label, unit)])
        chart.series.append(series)
    return chart


def _cum_frames(rates: pd.DataFrame) -> dict[str, pd.Series]:
    """Суточный расход (м³/сут) объекта и групп по всем суткам сезона (пропуск = 0), для накопления."""
    days = pd.date_range(rates.date.min(), rates.date.max(), freq='D')
    return {str(scope): part.set_index('date').q.reindex(days, fill_value=0.0) for scope, part in rates.groupby('scope', sort=False)}


def cum_groups_season(kind: str, period: str, rates: pd.DataFrame, object_name: str) -> Chart | None:
    """Накопленный за сезон объём по датам: объект и все группы на одном графике, млн м³."""
    if rates.empty:
        return None
    noun = WHAT[kind][0]
    chart = Chart(f'an-cum-groups-{kind}-{period}', f'Накопленный {noun} за сезон по группам · {period}',
                  Axis('Дата', scale='time'), Axis(f'Накопленный {noun}', 'млн м³', from_zero=True))
    for scope, daily in _cum_frames(rates).items():
        chart.series.append(Series(scope, daily.index.to_numpy(), (daily.cumsum() / 1e6).to_numpy(), 'line',
                                   group=scope, width=2.2 if scope == object_name else 1.2, dashed=scope == object_name))
    return chart


def cum_groups_months(kind: str, period: str, rates: pd.DataFrame, object_name: str) -> Chart | None:
    """Объём за каждый месяц сезона (накоплен в пределах месяца): столбцы по месяцам, ряд — группа, млн м³.
    Объект не рисуется: он в несколько раз выше групп и прячет их; его месячные объёмы — сумма столбцов."""
    rates = rates[rates.scope.astype(str).ne(object_name)]
    if rates.empty:
        return None
    noun = WHAT[kind][0]
    by = rates.assign(month=rates.date.dt.to_period('M')).groupby(['scope', 'month']).q.sum() / 1e6
    months = sorted(by.index.get_level_values('month').unique())
    cats = [month_name(m) for m in months]
    chart = Chart(f'an-cum-months-{kind}-{period}', f'Накопленный {noun} за месяц по группам · {period}',
                  Axis('Месяц', scale='category', categories=cats), Axis(f'Накопленный {noun} за месяц', 'млн м³', from_zero=True))
    for scope in dict.fromkeys(rates.scope.astype(str)):
        chart.series.append(Series(scope, cats, np.array([by.get((scope, m), np.nan) for m in months], float), 'bar', group=scope))
    return chart


def cum_group_months(kind: str, period: str, rates: pd.DataFrame, group: str) -> Chart | None:
    """Одна группа: накопленный объём внутри каждого месяца сезона по дням месяца (линия на месяц), млн м³."""
    part = rates[rates.scope.astype(str).eq(group)]
    if part.empty:
        return None
    noun = WHAT[kind][0]
    chart = Chart(f'an-cum-group-months-{kind}-{period}', f'Накопленный {noun} по месяцам · {group} · {period}',
                  Axis('День месяца', 'сут', from_zero=True), Axis(f'Накопленный {noun} в месяце', 'млн м³', from_zero=True))
    for month, rows in part.groupby(part.date.dt.to_period('M'), sort=True):
        days = pd.Series(rows.q.to_numpy(float), index=rows.date.dt.day.to_numpy()).groupby(level=0).sum()
        days = days.reindex(range(1, int(days.index.max()) + 1), fill_value=0.0)
        chart.series.append(Series(month_name(month), days.index.to_numpy(float), (days.cumsum() / 1e6).to_numpy(), 'line',
                                   group=month_name(month), width=1.4))
    return chart


def month_name(month: pd.Period) -> str:
    return f'{MONTHS[month.month - 1].capitalize()} {month.year}'


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

