"""Авторский надзор: графики сезона отбора и закачки, которые строятся по данным проекта.

Каждая функция принимает уже посчитанные таблицы (см. ``an_report``) и отдаёт ``Chart`` или None, если для графика нет данных.
Единицы: расход — тыс. м³/сут, накопленный объём — млн м³, давление — абсолютное, кгс/см².
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from atlas.engine.modules.charts import well_colors

from ..contract import Axis, Chart, ChartTable, HeatMap, Series
from . import an_wells

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


def group_pressure_chart(kind: str, period: str, reference: pd.DataFrame | None, start: Any, stop: Any) -> Chart | None:
    """Пластовое давление по группам за сезон: одна линия на группу (среднее замеров её скважин на дату).

    ``reference`` — замеры опорной сетки: well, date, pressure, scope (см. ``an_report.reference_pressure``)."""
    if reference is None or reference.empty:
        return None
    part = reference[reference.date.between(pd.Timestamp(start), pd.Timestamp(stop))]
    if part.empty:
        return None
    by_group = part.groupby(['scope', 'date'], as_index=False).pressure.mean().sort_values('date', kind='stable')
    colors = well_colors(by_group.scope.astype(str))
    chart = Chart(f'an-group-pressure-{kind}-{period}', f'Пластовое давление по группам · {period}',
                  Axis('Дата', scale='time'), Axis('Рпл, абс.', P_UNIT))
    for group, rows in by_group.groupby('scope', sort=False):
        chart.series.append(Series(str(group), rows.date.to_numpy(), rows.pressure.to_numpy(float), 'line',
                                   color=colors.get(str(group)), width=2.0, markers=True))
    return chart


SHOW = (('rate', 'Суточный расход'), ('pressure', 'Среднее Рпл (замеры)'), ('wells', 'Скважин в работе'),
        ('cumulative', 'Накопленный объём'), ('water', 'Вынос воды'), ('wf', 'Водный фактор, суточный'),
        ('wf_cum', 'Водный фактор, накопленный'), ('gas', 'Объём газа в пласте'))
SHOW_DEFAULT = ('Суточный расход', 'Среднее Рпл (замеры)', 'Скважин в работе')      # в списке параметра значения — подписи
SHOW_KEY = {label: key for key, label in SHOW}
# Ряды режима «от накопленного объёма»: по оси X — накопленный объём, поэтому накопленный объём и газ в пласте не выводятся.
CURVE_SHOW = tuple(s for s in SHOW if s[0] not in ('cumulative', 'gas'))
CURVE_SHOW_DEFAULT = ('Суточный расход', 'Среднее Рпл (замеры)')
WATER_LINES = (('water', 'water_day', 'Вынос воды', 'м³/сут', 'Вынос воды', {}),
               ('wf', 'wf', 'Водный фактор', 'л/тыс. м³', 'Водный фактор, суточный', {'dashed': True}),
               ('wf_cum', 'wf_cum', 'Водный фактор', 'л/тыс. м³', 'Водный фактор, накопленный', {}))


def _cum_at(cum: pd.Series, dates: Any) -> np.ndarray:
    """Накопленный объём (млн м³) на даты: значение за последние сутки не позже даты; до начала сезона — ноль."""
    pos = cum.index.searchsorted(pd.DatetimeIndex(dates), side='right') - 1
    return np.where(pos >= 0, cum.to_numpy()[np.maximum(pos, 0)], 0.0)


def _water_items(water: pd.DataFrame | None, show: list[str], start: Any, stop: Any, x_of: Any) -> list[tuple[str, str, str, Series]]:
    """Вынос воды и водный фактор за сезон из «Выноса воды по объекту»; ``x_of`` переводит даты в координаты X."""
    if water is None or water.empty:
        return []
    w = water[water.date.between(start, stop)].sort_values('date')
    items = []
    for key, col, label, unit, name, line in WATER_LINES:
        if key not in show:
            continue
        part = w[w[col].notna()]
        if not part.empty:
            items.append((key, label, unit, Series(name, x_of(part.date), part[col].to_numpy(float), 'line', width=1.0, **line)))
    return items


def _place(items: list[tuple[str, str, str, Series]]) -> tuple[Axis, Axis | None, Axis | None, list[Series]]:
    """Раскладка рядов по осям: величины в порядке первого появления; первая — левая шкала, вторая — y2 справа,
    третья и следующие делят y3 (единицы — в подписи оси)."""
    families = list(dict.fromkeys((label, unit) for _, label, unit, _ in items))
    main = families[0]
    side = {fam: ('y2' if n == 0 else 'y3') for n, fam in enumerate(families[1:])}

    def merged(axis: str) -> Axis:
        fams = [f for f, a in side.items() if a == axis]
        return Axis(' · '.join(dict.fromkeys(label for label, _ in fams)), ' · '.join(dict.fromkeys(unit for _, unit in fams)))

    series = [replace(s, axis=side[(label, unit)]) if (label, unit) != main else s for _, label, unit, s in items]
    y2 = merged('y2') if 'y2' in side.values() else None
    y3 = merged('y3') if 'y3' in side.values() else None
    return Axis(main[0], main[1], from_zero=True), y2, y3, series


def curve_chart(kind: str, period: str, daily: pd.Series, wells: pd.Series, pressure: pd.DataFrame | None,
                show: tuple[str, ...] | list[str] = CURVE_SHOW_DEFAULT, water: pd.DataFrame | None = None) -> Chart | None:
    """Суточный расход объекта по накопленному объёму за сезон; остальные ряды на выбор (``show``), все — по накопленному объёму.
    Рпл — по датам замеров; число работающих скважин — в подсказке к точке (и отдельным рядом, если выбрано)."""
    if daily.empty:
        return None
    noun, genitive, _ = WHAT[kind]
    cum = daily.cumsum() / 1e6
    start, stop = daily.index.min(), daily.index.max()
    show = [SHOW_KEY.get(v, v) for v in show]
    items: list[tuple[str, str, str, Series]] = []
    if 'rate' in show:
        labels = [f'{d:%d.%m.%Y} · скважин в работе: {int(wells[d])}' for d in daily.index]
        items.append(('rate', 'Суточный расход', Q_UNIT, Series('Суточный расход', cum.to_numpy(), (daily / 1000).to_numpy(), 'line',
                                                              labels=labels, width=1.0)))
    p = pressure_points(pressure, start, stop) if 'pressure' in show else None
    if p is not None:
        items.append(('pressure', 'Рпл, абс.', P_UNIT, Series('Рпл, абс.', _cum_at(cum, p.date), p.pressure.to_numpy(), 'points')))
    if 'wells' in show:
        items.append(('wells', 'Скважин в работе', 'скв.', Series('Скважин в работе', _cum_at(cum, wells.index), wells.to_numpy(float),
                                                                    'points', symbol='square')))
    items += _water_items(water, show, start, stop, lambda dates: _cum_at(cum, dates))
    if not items:
        return None
    y, y2, y3, series = _place(items)
    return Chart(f'an-curve-{kind}-{period}', f'Расход, давление и скважины от накопленного объёма {genitive} · {period}',
                 Axis(f'Накопленный {noun} за сезон', 'млн м³', from_zero=True), y, y2=y2, y3=y3, series=series)


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
    items += _water_items(water, show, start, stop, lambda dates: dates.to_numpy())
    if 'gas' in show and factor is not None and 'gas_in_place' in factor and not factor.empty:
        f = factor.assign(date=pd.to_datetime(factor.date), gas=pd.to_numeric(factor.gas_in_place, errors='coerce'))
        f = f[f.date.between(start, stop) & f.gas.notna()].sort_values('date')
        if not f.empty:
            items.append(('gas', 'Объём газа в пласте', 'млрд м³', Series('Объём газа в пласте', f.date.to_numpy(),
                                                                          (f.gas / 1e6).to_numpy(float), 'line', width=1.2)))
    if not items:
        return None
    y, y2, y3, series = _place(items)
    return Chart(f'an-canvas-{kind}-{period}', f'Сезон {genitive}: ряды по суткам · {period}', Axis('Дата', scale='time'), y,
                 y2=y2, y3=y3, series=series)


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


def class_share_chart(kind: str, period: str, counts: pd.DataFrame, callouts: str = 'box') -> Chart | None:
    """Классы производительности по группам (табл. 1.5): высота столбика — доля скважин класса в группе, число скважин — внутри сегмента.

    Узкие сегменты: ``callouts='box'`` — выноска в рамке цвета класса, ``'dot'`` — точка, а числа в таблице под графиком."""
    part = counts[~counts.group.eq(an_wells.TOTAL)]
    if part.empty:
        return None
    part = pd.concat([part, counts[counts.group.eq(an_wells.TOTAL)]])        # «Всего» — последним столбцом
    cats = [str(g) for g in part.group]
    size = part[list(an_wells.CLASS_KEYS)].sum(axis=1).to_numpy(float)
    chart = Chart(f'an-class-share-{kind}-{period}', f'Классы производительности скважин по группам · {period}',
                  Axis('Группа', scale='category', categories=cats), Axis('Доля скважин группы', '%', from_zero=True, minimum=0, maximum=100))
    chart.callouts = 'dot' if callouts == 'dot' else 'box'
    for key, name in zip(an_wells.CLASS_KEYS, an_wells.CLASS_NAMES):
        n = part[key].to_numpy(int)
        label = name if name == '0' else f'{name} тыс. м³/сут'
        chart.series.append(Series(label, cats, np.where(size > 0, n / np.where(size > 0, size, 1) * 100, 0.0), 'bar', stack='classes',
                                   segments=[str(v) if v else '' for v in n], labels=[f'{v} из {int(t)} скв.' for v, t in zip(n, size)]))
    if chart.callouts == 'dot':
        chart.table = ChartTable([s.name for s in chart.series], cats, [[str(v) for v in part[k].to_numpy(int)] for k in an_wells.CLASS_KEYS])
    return chart


def month_working_chart(kind: str, period: str, months: pd.DataFrame, labels: list[str]) -> Chart | None:
    """Табл. 1.4: по месяцам сезона — работавшие и простаивавшие скважины объекта (столбики с числами), под графиком — таблица по группам."""
    total = months[months.group.eq(an_wells.TOTAL)]
    if total.empty or not labels:
        return None
    fund = int(total.fund.iloc[0])
    working = np.array([int(total[f'm{i}'].iloc[0]) for i in range(len(labels))])
    idle = fund - working
    chart = Chart(f'an-month-working-{kind}-{period}', f'Работавшие скважины по месяцам · {period}',
                  Axis('Месяц', scale='category', categories=labels), Axis('Скважин', 'скв.', from_zero=True))
    chart.series.append(Series('Работало', labels, working.astype(float), 'bar', stack='months', segments=[str(v) for v in working],
                               labels=[f'{v} из {fund} скв., {v / fund * 100:.0f} %' for v in working]))
    chart.series.append(Series('Не работало', labels, idle.astype(float), 'bar', stack='months', segments=[str(v) if v else '' for v in idle],
                               labels=[f'{v} из {fund} скв.' for v in idle]))
    rows = [str(g) for g in months.group]
    cells = [[str(int(f))] + [str(int(r[f'm{i}'])) for i in range(len(labels))] for f, (_, r) in zip(months.fund, months.iterrows())]
    chart.table = ChartTable(rows, ['Фонд', *labels], cells, swatches=False)
    return chart


def heat_chart(chart_id: str, title: str, rows: list[str], columns: list[str], values: list[list[float | None]], texts: list[list[str]],
               unit: str, maximum: float | None = None, missing_text: str = 'нет данных') -> Chart:
    """Тепловая карта строка × столбец (ГСП × сезоны): оси нужны только подписями, ряды пусты."""
    chart = Chart(chart_id, title, Axis('Сезон', scale='category', categories=columns), Axis('ГСП', scale='category', categories=rows))
    chart.heat = HeatMap(rows, columns, values, texts, unit, maximum, missing_text)
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

