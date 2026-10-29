"""Авторский надзор: расчёт сезона, на котором строятся главы отчёта АН (Касимовское ПХГ, 2025).

По каждому выбранному сезону отбора: даты начала и остановки по суткам с расходом, длительность в календарных сутках
(високосный год учитывается календарём), длительность нейтрального периода перед сезоном, число скважин, работавших
хотя бы сутки, средние суточные расходы по объекту и группам за сезон и по месяцам, пик суточного расхода объекта
с фондом и давлением на эту дату, давление объекта на начало сезона. Если загружен «Вынос воды по объекту» —
максимумы суточного выноса воды, суточного и накопленного водного фактора с показателями объекта на их даты.

Группы — единая схема имён: регистр, пробелы, «_» и «-» не различают группы, «ГСП-1» = «ГСП 1»
(``loader.unify_groups`` и ``canonical_gsp`` из импорта). Давления — абсолютные, кгс/см²: Атлас их не пересчитывает.

Глава 1.2 (режим закачки): табл. 1.10 — объёмы закачки ГСП 9 по последним сезонам, план по группам против факта.
Глава 2 (сезон закачки, разделы 2.1.1–2.1.2) для режима «Закачка»: рис. 2.1 (расход, Рпл и число скважин от накопленной
закачки), рис. 2.2 (план и факт по месяцам), рис. 2.3 (по ГСП — как в «План и факт»), рис. 2.4 (Рпл за сезон),
табл. 2.1 (план и факт по группам), 2.2 (работавшие скважины по месяцам), 2.3 (классы приёмистости), 2.4 (план по месяцам).

Графики сезона (отбор и закачка) собирает ``an_charts``: расход и давление по датам и по накопленному объёму, скважины в работе,
накопленный объём, давление, средние по группам и месяцам, фонд, вынос воды, объём газа в пласте, МКД.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from atlas.engine.core.config import ordered
from atlas.engine.core.loader import canonical_gsp, unify_groups

from ..contract import builder_layouts_param, Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, ParamError, Result, Series, Stat, Table
from ..domain import DatasetKind
from . import an_annulus, an_charts, an_wells
from ._production import KINDS, NEUTRAL_PREFIXES, group_of, periods_of, visible_periods
from .plan_fact import UNIT, PlanFactModule, compare as plan_compare, month_label, plan_periods, summed as plan_summed

PRODUCTION, OBJECT, FACTOR = DatasetKind.PRODUCTION, DatasetKind.OBJECT_PRESSURE, DatasetKind.WATER_FACTOR
ANNULUS, RESPONSE, MATCH = DatasetKind.ANNULUS, DatasetKind.RESPONSE, DatasetKind.PRESSURE_MATCH
PLAN, WATER = DatasetKind.PLAN, DatasetKind.WATER
Q_UNIT = 'тыс. м³/сут'
P_UNIT = 'кгс/см²'
WATER_UNIT = 'м³/сут'
WF_UNIT = 'л/тыс. м³'
GSP9 = 'ГСП 9'            # группа табл. 1.10 в едином написании
INJECTION_SEASONS = 7     # табл. 1.10: последние 7 сезонов закачки
INJECTION_COLS = ('season', 'recommended', 'fact', 'percent')
WATER_COLS = ('water_day', 'wf', 'wf_cum')
WATER_KEYS = ('water_peak', 'water_peak_date', 'water_peak_q', 'water_peak_wells', 'water_peak_pressure',
              'wf_peak', 'wf_peak_date', 'wf_cum_peak', 'wf_cum_peak_date')
OBJECT_SCOPE = 'Объект'
WHOLE = 'Весь сезон'
GAP_DAYS = 30             # дней: дальше от даты давление объекта не берётся (иначе «на начало» — замер за год до него)
GROUP_NONE = 'Без группы'  # скважина без группы в схеме проекта
NOTE = ('Средние считаются по суткам с положительным расходом; пропущенные даты не считаются нулём и простоем. '
        'Длительность — календарные сутки от первого до последнего суток с расходом включительно (високосный год — по календарю). '
        'Нейтральный период — календарные сутки последнего нейтрального периода перед сезоном по данным отбора и закачки. '
        'Давления абсолютные, кгс/см²: давление объекта берётся на дату начала, пика или на ближайшую к ней дату (не дальше 30 суток). '
        'Водный фактор — л воды на 1000 м³ газа; накопленный фактор — максимум за сезон (обычно на последние сутки).')

# Не строятся: геологические запасы газа и модельный объём газа; карты — вне Атласа.
CHAPTER2_SKIPPED = ('Не построены: геологические запасы газа (ГПО) '
                    'и модельный объём газа — в Атласе нет этих данных; карты — вне Атласа.')

# Табл. 2.3 (закачка) — те же классы, что у отбора (границы — общая схема ``class_scheme``); колонки c0… — диапазоны без «0».
def injection_keys(edges: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f'c{i}' for i in range(len(edges) + 1))


CLASS_MODES = (Option('manual', 'Вручную: границы из списка'),
               Option('auto', 'Автоматически: подсказка по фонду, границы кратны 5'))


def class_scheme(prod: pd.DataFrame, kind: str, periods: list[str], params: Mapping[str, Any]) -> tuple[tuple[int, ...], Note | None]:
    """Границы классов производительности (тыс. м³/сут) для выбранных сезонов.

    «Вручную» — границы из поля ``class_edges``; при ошибке в поле — стандартные и предупреждение. «Автоматически» — подсказка
    по фонду: квантили среднего расхода по всем выбранным сезонам сразу, чтобы классы были одинаковы между сезонами."""
    if params.get('class_mode') != 'auto':
        try:
            return an_wells.parse_edges(params.get('class_edges') or ''), None
        except ValueError as exc:
            default = ', '.join(map(str, an_wells.DEFAULT_EDGES))
            return an_wells.DEFAULT_EDGES, Note(f'Границы классов: {exc}. Использованы стандартные: {default}.', 'warning')
    rates: list[float] = []
    for period in periods:
        wells = an_wells.season_wells(prod, kind, period)
        rates.extend((wells.rate[wells.days.gt(0)] / 1000).tolist())
    count = int(params.get('class_count') or an_wells.DEFAULT_COUNT)
    edges = an_wells.auto_edges(rates, count)
    if not edges:
        reason = ('выберите сезоны' if not periods else 'задайте число классов не меньше 2' if count < 2
                  else 'в выбранных сезонах нет скважин с расходом')
        return (), Note(f'Автоматические границы классов не подобраны: {reason}.', 'warning')
    shown = ', '.join(map(str, edges))
    return edges, Note(f'Автоматические границы классов, тыс. м³/сут: {shown}. Подобраны по {len(rates)} скв.-сезонам с расходом '
                       f'(квантили фонда, кратно 5; совпавшие границы убраны — классов с расходом {len(edges) + 1} из {count}). '
                       'Это подсказка: при необходимости перенесите границы в ручной режим.')


def pressure_near(pressure: pd.DataFrame | None, when: Any) -> float | None:
    """Давление объекта на дату ``when`` или на ближайшую к ней в пределах ``GAP_DAYS``; при равной разнице берётся более ранняя дата."""
    if pressure is None or pressure.empty:
        return None
    p = pressure.dropna(subset=['pressure']).sort_values('date', kind='stable')
    if p.empty:
        return None
    gap = (p.date - pd.Timestamp(when)).abs()
    if gap.min() > pd.Timedelta(days=GAP_DAYS):
        return None
    return float(p.loc[gap.idxmin(), 'pressure'])


REFERENCE_LABELS = {'grid': 'реагирование, давление (пересчёт)', 'match': 'кроссплот, факт'}


def reference_pressure(data: Data, source: str) -> tuple[pd.DataFrame | None, str]:
    """Замеры опорной сетки (одна скважина — одна группа): well, date, pressure, scope — одно давление на скважину и дату.

    ``source``: «grid» — «Реагирование», давление (пересчёт по уровню); «match» — «Кроссплот давлений», факт;
    «auto» — сначала «grid», иначе «match». Скважины без группы в схеме проекта не попадают в сетку.
    Второй результат — подпись взятого источника (пусто, если замеров нет)."""
    for name in (('grid', 'match') if source == 'auto' else (source,)):
        key, column = (MATCH, 'fact') if name == 'match' else (RESPONSE, 'pressure')
        if key not in data or column not in data[key]:
            continue
        d = data[key][['well', 'date', column]].dropna(subset=[column])
        if d.empty:
            continue
        d = d.assign(well=d.well.astype(str)).groupby(['well', 'date'], as_index=False)[column].mean()
        d = d.rename(columns={column: 'pressure'})
        d['scope'] = d.well.map(well_scopes(data.mapping, ordered(d.well.unique())))
        d = d[d.scope.ne(GROUP_NONE)].reset_index(drop=True)
        if not d.empty:
            return d, REFERENCE_LABELS[name]
    return None, ''


def grid_object_pressure(reference: pd.DataFrame) -> pd.DataFrame:
    """Давление объекта по опорной сетке: среднее по группам на дату, каждая группа с одинаковым весом. Колонки — date, pressure."""
    by_group = reference.groupby(['scope', 'date'], as_index=False).pressure.mean()
    return by_group.groupby('date', as_index=False).pressure.mean()


def object_pressure_of(data: Data, source: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None, str]:
    """Давление объекта по выбранному источнику: (давление объекта или None, опорная сетка или None, подпись источника).

    «auto» берёт столбец «Давление объекта» из БД, если он загружен, иначе среднее по опорной сетке; «object» — только столбец;
    «grid» и «match» — только опорная сетка своего вида. Опорная сетка строится всегда, кроме «object»: нужна для графика по группам."""
    column = data[OBJECT] if OBJECT in data else None
    reference, ref_label = (None, '') if source == 'object' else reference_pressure(data, source)
    if source == 'object' or (source == 'auto' and column is not None):
        return column, reference, 'столбец «Давление объекта» из БД'
    if reference is None:
        return None, None, ''
    return grid_object_pressure(reference), reference, \
        f'опорная сетка ({ref_label}): {reference.well.nunique()} скв. в {reference.scope.nunique()} группах'


def neutral_days_before(prod: pd.DataFrame, start: Any) -> int | None:
    """Календарные сутки последнего нейтрального периода до даты ``start``; None, если его нет в данных."""
    neutral = prod[prod.period.astype(str).str.startswith(NEUTRAL_PREFIXES) & prod.date.lt(pd.Timestamp(start))]
    if neutral.empty:
        return None
    span = neutral.groupby('period').date.agg(['min', 'max']).sort_values('max')
    last = span.iloc[-1]
    return int((last['max'] - last['min']).days + 1)


def water_table(df: pd.DataFrame) -> pd.DataFrame:
    """«Вынос воды по объекту»: дата и числовые колонки (суточный вынос м³/сут, суточный и накопленный водный фактор)."""
    w = df.assign(date=pd.to_datetime(df.date).dt.normalize())
    for col in WATER_COLS:
        w[col] = pd.to_numeric(w[col], errors='coerce') if col in w else np.nan
    return w[w.date.notna()]


def water_summary(water: pd.DataFrame, start: Any, stop: Any, q_by_date: pd.Series, wells_by_date: pd.Series,
                  pressure: pd.DataFrame | None) -> dict[str, Any]:
    """Максимумы выноса воды и водного фактора за сезон; для максимума выноса — Q объекта, фонд и Рпл на его дату."""
    w = water[water.date.between(pd.Timestamp(start), pd.Timestamp(stop))]
    out: dict[str, Any] = {}
    if w.water_day.notna().any():
        row = w.loc[w.water_day.idxmax()]
        out.update(water_peak=row.water_day, water_peak_date=row.date,
                   water_peak_q=q_by_date.get(row.date, 0.0) / 1000,
                   water_peak_wells=int(wells_by_date.get(row.date, 0)),
                   water_peak_pressure=pressure_near(pressure, row.date))
    if w.wf.notna().any():
        row = w.loc[w.wf.idxmax()]
        out.update(wf_peak=row.wf, wf_peak_date=row.date)
    if w.wf_cum.notna().any():
        row = w.loc[w.wf_cum.idxmax()]
        out.update(wf_cum_peak=row.wf_cum, wf_cum_peak_date=row.date)
    return out


def unified_names(values: pd.Series) -> pd.Series:
    """Названия групп в едином написании: регистр, пробелы, «_» и «-» не различают группы."""
    return canonical_gsp(unify_groups(values.astype(str)))


def well_scopes(mapping: Mapping[str, Mapping[str, str]], wells: list[str]) -> dict[str, str]:
    """Скважина → группа в едином написании: регистр, пробелы, «_» и «-» не различают группы."""
    raw = pd.Series([group_of(mapping, w) for w in wells], dtype=object)
    names = canonical_gsp(unify_groups(raw)).to_numpy()
    return dict(zip(wells, names))


def daily_rates(d: pd.DataFrame, scopes: Mapping[str, str]) -> pd.DataFrame:
    """Суточный расход (м³/сут) объекта и каждой группы: scope, date, q; только сутки с положительным расходом."""
    obj = d.groupby('date').q.sum(min_count=1).reset_index().assign(scope=OBJECT_SCOPE)
    grp = d.assign(scope=d.well.map(scopes)).groupby(['scope', 'date']).q.sum(min_count=1).reset_index()
    out = pd.concat([obj, grp], ignore_index=True)
    out = out[out.q.gt(0)].copy()
    out['month'] = out.date.dt.to_period('M').dt.to_timestamp()
    return out


def injection_group_table(prod: pd.DataFrame, plan: pd.DataFrame | None, mapping: Mapping[str, Mapping[str, str]],
                          settings: Mapping[str, Any], group: str = GSP9, seasons: int = INJECTION_SEASONS) -> pd.DataFrame:
    """Табл. 1.10: по последним сезонам закачки — рекомендованный объём группы (план по группам), фактический (сумма
    суточных объёмов её скважин), оба в млрд м³, и доля группы в общем фактическом объёме сезона (%).

    Пустая таблица, если в закачке нет скважин группы ``group``. Рекомендованный объём — NaN, если плана за сезон нет.
    """
    d = prod[prod.kind.eq('injection')][['well', 'period', 'q']].copy()
    if d.empty:
        return pd.DataFrame(columns=INJECTION_COLS)
    d['well'] = d.well.astype(str)
    d['group'] = d.well.map(well_scopes(mapping, ordered(d.well.unique())))
    if not d.group.eq(group).any():
        return pd.DataFrame(columns=INJECTION_COLS)
    periods = visible_periods(ordered(d.period.astype(str).unique()), settings)[-seasons:]
    total = d.groupby('period').q.sum(min_count=1)
    fact = d[d.group.eq(group)].groupby('period').q.sum(min_count=1)
    recommended = pd.Series(dtype=float)
    if plan is not None and not plan.empty:
        p = plan[plan.kind.eq('injection')]
        if not p.empty:
            p = p.assign(period=plan_periods(prod, p, settings),
                         group=canonical_gsp(unify_groups(p.group.astype(str))))
            recommended = p[p.group.eq(group)].groupby('period').plan_volume.sum(min_count=1)
    rows = []
    for season in periods:
        volume, share = fact.get(season, 0.0), total.get(season, np.nan)
        rows.append({'season': season,
                     'recommended': recommended.get(season, np.nan) / 1000,       # млн м³ → млрд м³
                     'fact': volume / 1e9,                                        # м³ → млрд м³
                     'percent': volume / share * 100 if share and share > 0 else np.nan})
    return pd.DataFrame(rows, columns=INJECTION_COLS)


def season_report(prod: pd.DataFrame, mapping: Mapping[str, Mapping[str, str]], pressure: pd.DataFrame | None,
                  kind: str, period: str, water: pd.DataFrame | None = None) -> tuple[dict[str, Any] | None, pd.DataFrame]:
    """Сводка одного сезона и средние по объекту и группам (за весь сезон и по месяцам).

    ``water`` — «Вынос воды по объекту» (см. ``water_table``); учитывается только для отбора.
    Возвращает (сводка или None, если в сезоне нет суток с расходом; таблица средних: scope, period, days, mean).
    """
    d = prod[prod.kind.eq(kind) & prod.period.eq(period)][['well', 'date', 'q']].copy()
    d['well'] = d.well.astype(str)
    scopes = well_scopes(mapping, ordered(d.well.unique())) if not d.empty else {}
    daily = daily_rates(d, scopes)
    obj = daily[daily.scope.eq(OBJECT_SCOPE)]
    if obj.empty:
        return None, pd.DataFrame(columns=['scope', 'period', 'days', 'mean'])
    start, stop = obj.date.min(), obj.date.max()
    peak = obj.loc[obj.q.idxmax()]
    q_by_date = obj.set_index('date').q
    wells_by_date = d[d.q.gt(0)].groupby('date').well.nunique()
    summary = {
        'period': period,
        'start': start,
        'stop': stop,
        'days': (stop - start).days + 1,
        'neutral_days': neutral_days_before(prod, start),
        'active_days': len(obj),
        'wells': int(d[d.q.gt(0)].well.nunique()),
        'mean': obj.q.mean() / 1000,
        'peak': peak.q / 1000,
        'peak_date': peak.date,
        'peak_wells': int(wells_by_date.get(peak.date, 0)),
        'pressure_start': pressure_near(pressure, start),
        'pressure_peak': pressure_near(pressure, peak.date),
    }
    if kind == 'withdrawal' and water is not None:
        summary.update(water_summary(water, start, stop, q_by_date, wells_by_date, pressure))
    rows = []
    for scope in [OBJECT_SCOPE] + [s for s in ordered(daily.scope.unique()) if s != OBJECT_SCOPE]:
        part = daily[daily.scope.eq(scope)]
        rows.append({'scope': scope, 'period': WHOLE, 'days': len(part), 'mean': part.q.mean() / 1000})
        for month, chunk in part.groupby('month', sort=True):
            rows.append({'scope': scope, 'period': month_label(month), 'days': len(chunk), 'mean': chunk.q.mean() / 1000})
    return summary, pd.DataFrame(rows)


def injection_class_table(wells: pd.DataFrame, scopes: Mapping[str, str], edges: tuple[int, ...] = an_wells.DEFAULT_EDGES) -> pd.DataFrame:
    """Табл. 2.3: по группам — число и номера скважин с нулевым расходом за сезон и по классам среднего расхода (тыс. м³/сут)."""
    w = wells.assign(group=wells.well.map(scopes), rate_k=wells.rate / 1000)
    w['cls'] = an_wells.class_index(w.days.to_numpy(), w.rate_k.to_numpy(float), edges)
    keys = injection_keys(edges)
    rows = []
    for name, part in [(an_wells.TOTAL, w)] + [(g, w[w.group.eq(g)]) for g in ordered(w.group.unique())]:
        row = {'group': name, 'zero': an_wells._numbers(ordered(part[part.cls.eq(0)].well))}
        for i, key in enumerate(keys, start=1):
            row[key] = an_wells._numbers(ordered(part[part.cls.eq(i)].well))
        rows.append(row)
    return pd.DataFrame(rows, columns=['group', 'zero', *keys])


def monthly_wells(prod: pd.DataFrame, mapping: Mapping[str, Mapping[str, str]], period: str) -> tuple[pd.DataFrame, list[Any]]:
    """Табл. 2.2: по группам — фонд сезона и число скважин с расходом в каждом месяце; months — месяцы в порядке дат."""
    d = prod[prod.kind.eq('injection') & prod.period.eq(period)][['well', 'date', 'q']].copy()
    d['well'] = d.well.astype(str)
    scopes = well_scopes(mapping, ordered(d.well.unique())) if not d.empty else {}
    d = d.assign(group=d.well.map(scopes), month=d.date.dt.to_period('M').dt.to_timestamp())
    work = d[d.q.gt(0)]
    months = sorted(work.month.unique())
    rows = []
    for name, fund, wk in [(an_wells.TOTAL, d, work)] + [(g, d[d.group.eq(g)], work[work.group.eq(g)])
                                                         for g in ordered(d.group.unique())]:
        row = {'group': name, 'fund': fund.well.nunique()}
        for i, month in enumerate(months):
            row[f'm{i}'] = wk[wk.month.eq(month)].well.nunique()
        rows.append(row)
    return pd.DataFrame(rows), months


def plan_card(plan_cmp: pd.DataFrame, period: str) -> tuple[pd.DataFrame, list[Any]]:
    """Табл. 2.4: план закачки по группам и месяцам сезона, млн м³ (из «План по группам»)."""
    part = plan_cmp[plan_cmp.period.eq(period)]
    months = sorted(part.month.unique())
    wide = part.pivot_table(index='group', columns='month', values='plan', aggfunc='sum')
    wide = wide.reindex(ordered(part.group.unique()))
    rows = []
    for name, values in wide.iterrows():
        row = {'group': name}
        for i, month in enumerate(months):
            row[f'm{i}'] = values.get(month, np.nan)
        rows.append(row)
    return pd.DataFrame(rows, columns=['group', *[f'm{i}' for i in range(len(months))]]), months


def plan_fact_by_group(plan_cmp: pd.DataFrame, period: str) -> pd.DataFrame:
    """Табл. 2.1: план и факт закачки сезона по группам и итогом; млн м³."""
    part = plan_cmp[plan_cmp.period.eq(period)]
    by = plan_summed(part, 'group')
    by = by.set_index('group').loc[ordered(by.group)].reset_index()
    total = plan_summed(part.assign(group=an_wells.TOTAL), 'group')
    return pd.concat([by, total], ignore_index=True).assign(season=period)


def _signed(value: float) -> str:
    """Отклонение со знаком: тысячи через пробел, десятичная запятая."""
    return f'{value:+,.1f}'.replace(',', ' ').replace('.', ',')


VIEWS = (Option('canvas', 'Ряды по суткам'), Option('curve', 'Расход от накопленного объёма'),
         Option('group_mean', 'Средний расход по группам'), Option('group_mean_months', 'Средний расход по месяцам'),
         Option('cum_season', 'Накопленный объём за сезон по группам'), Option('cum_months', 'Объём за месяц по группам'),
         Option('group_months', 'Накопленный объём по месяцам, одна группа'))


PRESSURE_SOURCES = (Option('auto', 'Авто: столбец «Давление объекта», иначе опорная сетка'),
                    Option('object', 'Столбец «Давление объекта» из БД'),
                    Option('grid', 'Опорная сетка: реагирование, давление (пересчёт)'),
                    Option('match', 'Опорная сетка: кроссплот, факт'))
CLASS_CHARTS = (Option('none', 'Только таблица классов (номера скважин)'), Option('box', 'График: узкие сегменты — выноска в рамке'),
                Option('dot', 'График: узкие сегменты — точка, числа в таблице под графиком'))
MONTH_CHARTS = (Option('none', 'Нет'), Option('table', 'График с таблицей по группам под ним'))
SIDES = (Option('fund', 'Фонд и работавшие скважины'), Option('none', 'Нет'),
         *(o for o in VIEWS if o.value != 'canvas'))


class AuthorReportModule(Module):
    spec = ModuleSpec(
        id='an_report',
        title='Авторский надзор: сезон',
        group='Авторский надзор',
        description='Статистика сезона для глав отчёта АН: даты, нейтральный период, средние по объекту и группам, пик, вода.',
        needs=(PRODUCTION,),
        optional=(OBJECT, FACTOR, PLAN, WATER, ANNULUS, RESPONSE, MATCH),
        order=110,
        save_label='Сохранить вид',
        params=(
            Param('kind', 'Режим', 'choice', default='withdrawal', options=KINDS, section='Выбор данных'),
            Param('periods', 'Сезоны', 'multi', default=[], dynamic=True, depends=('kind',), auto='last:1',
                  empty='ничего', section='Выбор данных'),
            Param('view', 'График', 'choice', default='canvas', section='Вид', chart_kind=True, options=VIEWS),
            Param('side', 'Правый график', 'choice', default='fund', section='Вид', chart_kind=True, options=SIDES),
            Param('class_chart', 'Классы производительности (табл. 1.5)', 'choice', default='none', section='Вид', chart_kind=True,
                  options=CLASS_CHARTS, help='Для отбора и закачки. Добавляет таблицу «Количество скважин по классам производительности» и график к ней: '
                  'столбики — доли классов по группам, числа скважин внутри сегментов, узкие сегменты — выноской или точкой с таблицей под графиком.'),
            Param('class_mode', 'Границы классов', 'choice', default='manual', section='Вид', options=CLASS_MODES,
                  help='Общие для классов отбора (табл. 1.5) и закачки (табл. 2.3) и их графиков. «Вручную» — границы из поля ниже. '
                       '«Автоматически» — подсказка по фонду выбранных сезонов, границы кратны 5; её можно перенести в ручной режим и поправить.'),
            Param('class_edges', 'Границы классов, тыс. м³/сут', 'text', default=', '.join(map(str, an_wells.DEFAULT_EDGES)), section='Вид',
                  show_if={'class_mode': 'manual'},
                  help='Целые числа через запятую, по возрастанию. Например 20, 75, 100, 250 — классы: менее 20, от 20 до 75, от 75 до 100, от 100 до 250 и более 250. '
                       'Граница относится к верхнему классу. Классов с расходом на одно больше, чем границ: пять границ — шесть классов. '
                       'Первая граница — также порог двухклассовой таблицы.'),
            Param('class_count', 'Классов с расходом (автоматически)', 'integer', default=an_wells.DEFAULT_COUNT, minimum=2, maximum=12,
                  section='Вид', show_if={'class_mode': 'auto'},
                  help='Сколько классов с расходом подобрать. Границы — квантили фонда по среднему расходу (примерно равное число скважин в классе), '
                       'округлённые до кратных 5. Совпавшие границы убираются, поэтому классов может стать меньше.'),
            Param('class_seasons', 'Сезоны для сравнения классов по группам', 'multi', default=[], dynamic=True, depends=('kind',),
                  empty='ничего', section='Вид',
                  help='Два и более сезона: график «Классы производительности по группам за сезоны» — столбик на пару «группа · сезон», '
                       'группы по возрастанию номера, внутри группы сезоны по порядку. Не обязаны совпадать с сезонами отчёта. Для отбора и закачки.'),
            Param('month_chart', 'Работавшие по месяцам (табл. 1.4)', 'choice', default='table', section='Вид', chart_kind=True,
                  options=MONTH_CHARTS, help='Для отбора и закачки. Добавляет таблицу «Работавшие скважины по месяцам» и график к ней: '
                  'работавшие и простаивавшие скважины объекта по месяцам сезона, под графиком — таблица по группам.'),
            Param('pressure_source', 'Давление объекта', 'choice', default='auto', section='Выбор данных',
                  options=PRESSURE_SOURCES, help='Откуда берётся Рпл объекта и динамика по группам. «Авто» — столбец БД, иначе опорная сетка.'),
            Param('show', 'Ряды на графике', 'multi', default=list(an_charts.SHOW_DEFAULT), section='Вид',
                  show_if={'view': 'canvas'}, empty='ничего', options=tuple(Option(v, v) for _, v in an_charts.SHOW)),
            Param('show_curve', 'Ряды на графике «от накопленного объёма»', 'multi', default=list(an_charts.CURVE_SHOW_DEFAULT),
                  section='Вид', empty='ничего', options=tuple(Option(v, v) for _, v in an_charts.CURVE_SHOW),
                  help='Для графика «Расход от накопленного объёма» (основного или правого). По оси X — накопленный объём. '
                       'Рпл — точки по датам замеров; скважины — в подсказке к точке и отдельным рядом.'),
            Param('groups', 'Группы', 'multi', default=[], dynamic=True, depends=('kind', 'periods'), auto='first:1',
                  empty='ничего', section='Вид', show_if={'view': 'group_months'},
                  help='Группы для графика накопленного объёма по месяцам: по графику на группу.'),
            builder_layouts_param('Макеты конструктора в отчёте', 'Сохранённые макеты «Конструктора графиков» проекта: каждый идёт в конце отчёта как отдельный рисунок.'),
            Param('annulus', 'Сезоны замеров МКД', 'multi', default=[], dynamic=True, auto='last:1',
                  empty='ничего', section='Выбор данных'),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'annulus':
            return sorted(data[ANNULUS]['season'].dropna().unique()) if ANNULUS in data else []
        if name == 'builder_layouts':
            from .. import builder_library
            return builder_library.layout_names(data)
        if name == 'groups':
            kind = params.get('kind') or 'withdrawal'
            d = data[PRODUCTION]
            d = d[d.kind.eq(kind) & d.period.isin(params.get('periods') or periods_of(d, kind))]
            wells = ordered(d.well.astype(str).unique())
            return ordered(set(well_scopes(data.mapping, wells).values()))
        if name not in ('periods', 'class_seasons'):
            return super().options(name, data, params)
        return visible_periods(periods_of(data[PRODUCTION], params.get('kind') or 'withdrawal'), data.settings)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        kind = params['kind']
        source = params.get('pressure_source') or 'auto'
        pressure, reference, source_label = object_pressure_of(data, source)
        if pressure is None:
            result.notes.append(Note('Давление объекта не построено: нет столбца «Давление объекта» и замеров опорной сетки. '
                                     'Загрузите «Давление объекта» или замеры по скважинам с группами.', 'warning'))
        else:
            result.notes.append(Note(f'Давление объекта: {source_label}.'))
        if source != 'object' and reference is None:
            result.notes.append(Note('Опорная сетка: замеров давления по скважинам с группой нет — график по группам пропущен.'))
        water = water_table(data[FACTOR]) if FACTOR in data and not data[FACTOR].empty else None
        if kind == 'withdrawal' and water is None:
            result.notes.append(Note('«Вынос воды по объекту» не загружен: максимумы по выносу воды и водному фактору пропущены.',
                                     'warning'))
        known = set(periods_of(data[PRODUCTION], kind))
        periods = [p for p in params['periods'] if p in known]
        if not periods:
            result.notes.append(Note('Выберите сезон: в проекте нет данных для выбранного режима.'))
        edges, class_note = class_scheme(data[PRODUCTION], kind, periods, params)
        if class_note is not None:
            result.notes.append(class_note)
        summaries, means = [], []
        fund, classes, wet, counts, month_tables = [], [], [], [], []
        if PLAN not in data:
            result.notes.append(Note('План по группам не загружен: график «План и факт по группам» пропущен.', 'warning'))
        if kind == 'withdrawal' and WATER not in data:
            result.notes.append(Note('«Контроль воды» не загружен: таблица «Вода по группам» пропущена.', 'warning'))
        for period in periods:
            summary, table = season_report(data[PRODUCTION], data.mapping, pressure, kind, period, water)
            if summary is None:
                result.notes.append(Note(f'Сезон {period}: нет суток с расходом — расчёт пропущен.'))
                continue
            summaries.append(summary)
            means.append(table.assign(period_season=period))
            result.summary += [Stat(f'Длительность · {period}', f'{summary["days"]} сут', 'Календарные сутки с расходом'),
                               Stat(f'Средний расход · {period}', f'{summary["mean"]:.1f} {Q_UNIT}'.replace('.', ','))]
            self.fund_details(result, data, kind, period, summary, fund, classes, wet, counts, params.get('class_chart') or 'none',
                              params.get('month_chart') or 'none', month_tables, edges=edges)
            self.season_charts(result, data, kind, period, summary, table, pressure, params, fund[-1])
            group_pressure = an_charts.group_pressure_chart(kind, period, reference, summary['start'], summary['stop'])
            if group_pressure is not None:
                result.charts.append(group_pressure)
            self.plan_details(result, data, kind, period)
        self.class_seasons_details(result, data, kind, params, edges)
        if kind == 'injection':
            self.injection_details(result, data)
            self.injection_season(result, data, summaries, edges)
        if summaries:
            result.tables.append(self.season_table(summaries))
            if water is not None and kind == 'withdrawal':
                result.tables.append(self.water_table_report(summaries))
            result.tables.append(self.means_table(means))
        if fund:
            result.tables.append(self.fund_table_report(fund))
        if classes:
            result.tables.append(self.class_table_report(classes, edges))
        if counts:
            result.tables.append(self.class_counts_report(counts, edges))
        if month_tables:
            result.tables.append(self.month_working_report(month_tables))
        if wet:
            result.tables.append(self.wet_table_report(wet))
        result.notes.append(Note(NOTE))
        if kind == 'injection' and summaries:
            result.notes.append(Note(CHAPTER2_SKIPPED, 'warning'))
        self.annulus_details(result, data, params.get('annulus') or [])
        from .. import builder_library
        builder_library.add_layout_charts(result, data, params.get('builder_layouts') or [], noun='рисунок')
        return result

    def annulus_details(self, result: Result, data: Data, seasons: list[str]) -> None:
        """Результаты замеров МКД: межколонные давления и расход из МКП по выбранным сезонам замеров + текст под таблицей."""
        if ANNULUS not in data or data[ANNULUS].empty:
            result.notes.append(Note('Результаты замеров МКД не построены: в проекте нет «Межколонных давлений» (База межколонок).'))
            return
        rows = data[ANNULUS]
        picked = [s for s in seasons if s in set(rows['season'])]
        if not picked:
            result.notes.append(Note('Результаты замеров МКД: выберите сезон замеров МКД.'))
            return
        chosen, bad = an_annulus.valid_rows(rows[rows['season'].isin(picked)])
        if bad:
            result.notes.append(Note('Межколонные давления: пропущены строки с некорректным номером скважины: '
                                     + ', '.join(f'«{b}»' for b in bad) + '. Исправьте номер в базе межколонок.', 'warning'))
        wells = an_annulus.annulus_wells(chosen)
        frame = an_annulus.table_11_3(wells)
        columns = [Column(an_annulus.COLUMNS[0], an_annulus.COLUMNS[0], decimals=0, kind='number'),
                   Column(an_annulus.COLUMNS[1], an_annulus.COLUMNS[1], decimals=1, kind='number'),
                   Column(an_annulus.COLUMNS[2], an_annulus.COLUMNS[2], decimals=0, kind='number'),
                   Column(an_annulus.COLUMNS[3], an_annulus.COLUMNS[3])]
        result.tables.append(Table('an-annulus-113', 'Результаты замеров МКД', frame, columns,
                                   note='Максимумы за выбранные сезоны: расход из МКП и давление МКД, кгс/см² (абсолютные).'))
        result.charts += an_charts.annulus_charts(wells, ', '.join(picked))
        for line in an_annulus.classification_text(wells):
            result.notes.append(Note(line))

    def injection_details(self, result: Result, data: Data) -> None:
        """Объёмы закачки газа: объёмы закачки ГСП 9 по последним сезонам — рекомендованный и фактический."""
        plan = data[PLAN] if PLAN in data else None
        if plan is None or plan.empty:
            result.notes.append(Note('«План по группам» не загружен: рекомендованный объём в таблице «Объёмы закачки газа» пустой.', 'warning'))
        frame = injection_group_table(data[PRODUCTION], plan, data.mapping, data.settings)
        if frame.empty:
            result.notes.append(Note(f'Таблица «Объёмы закачки газа» пропущена: в закачке нет скважин группы {GSP9}.', 'warning'))
            return
        result.tables.append(self.injection_table(frame))

    def injection_season(self, result: Result, data: Data, summaries: list[dict[str, Any]], edges: tuple[int, ...]) -> None:
        """Глава 2 (разделы 2.1.1–2.1.2): рис. 2.1, 2.2, 2.3, 2.4 и табл. 2.1–2.4 по выбранным сезонам закачки."""
        prod = data[PRODUCTION]
        plan_cmp = None
        if PLAN in data and not data[PLAN].empty:
            # Имена групп плана и факта приводятся к единой схеме до сопоставления, иначе «ГСП-9» и «гсп_9» не совпадут.
            plan = data[PLAN].assign(group=unified_names(data[PLAN].group))
            mapping = {well: {**info, 'group': unified_names(pd.Series([info.get('group', '')])).iloc[0]}
                       for well, info in data.mapping.items()}
            plan_cmp = plan_compare(prod, plan, mapping, 'injection', data.settings)
        plan_rows, months_parts, classes, cards = [], [], [], []
        for summary in summaries:
            period = summary['period']
            months, mlist = monthly_wells(prod, data.mapping, period)
            months_parts.append(self.injection_months_table(months, mlist, period, len(months_parts)))
            wells = an_wells.season_wells(prod, 'injection', period)
            classes.append(injection_class_table(wells, well_scopes(data.mapping, ordered(wells.well)), edges).assign(season=period))
            if plan_cmp is None or not plan_cmp.period.eq(period).any():
                continue
            part = plan_cmp[plan_cmp.period.eq(period)]
            result.charts.append(PlanFactModule().months_chart(plan_summed(part, 'month').sort_values('month'), period, 'injection'))
            plan_rows.append(plan_fact_by_group(plan_cmp, period))
            card, card_months = plan_card(plan_cmp, period)
            cards.append(self.plan_card_table(card, card_months, period, len(cards)))
        if plan_rows:
            result.tables.append(self.plan_fact_table(pd.concat(plan_rows, ignore_index=True)))
        result.tables.extend(months_parts)
        if classes:
            result.tables.append(self.injection_class_report(pd.concat(classes, ignore_index=True), edges))
        result.tables.extend(cards)

    @staticmethod
    def injection_table(frame: pd.DataFrame) -> Table:
        columns = [Column('season', 'Сезон'),
                   Column('recommended', 'Рекомендованный объём закачки, млрд м³', decimals=2, kind='number'),
                   Column('fact', 'Фактический объём закачки, млрд м³', decimals=3, kind='number'),
                   Column('percent', 'Доля в общем объёме закачки, %', decimals=1, kind='number')]
        return Table('an-injection-gsp9', f'Объёмы закачки газа по {GSP9}', frame, columns,
                     note=f'Рекомендованный — «План по группам» (закачка); фактический — сумма суточных объёмов скважин {GSP9}; '
                          f'доля — от общего фактического объёма сезона. Последние {INJECTION_SEASONS} сезонов закачки.')

    @staticmethod
    def season_table(summaries: list[dict[str, Any]]) -> Table:
        frame = pd.DataFrame(summaries)
        columns = [Column('period', 'Сезон'), Column('start', 'Начало', kind='date'), Column('stop', 'Остановка', kind='date'),
                   Column('days', 'Длительность, сут', decimals=0, kind='number'),
                   Column('neutral_days', 'Нейтральный период перед сезоном, сут', decimals=0, kind='number'),
                   Column('active_days', 'Суток с расходом', decimals=0, kind='number'),
                   Column('wells', 'Скважин в работе', decimals=0, kind='number'),
                   Column('mean', 'Средний расход объекта', Q_UNIT, 1, 'number'),
                   Column('peak', 'Максимум суточного', Q_UNIT, 1, 'number'),
                   Column('peak_date', 'Дата максимума', kind='date'),
                   Column('peak_wells', 'Скважин на дату максимума', decimals=0, kind='number'),
                   Column('pressure_start', f'Рпл на начало, абс. {P_UNIT}', decimals=2, kind='number'),
                   Column('pressure_peak', f'Рпл на дату максимума, абс. {P_UNIT}', decimals=2, kind='number')]
        return Table('an-season', 'Основные показатели сезона', frame, columns)

    @staticmethod
    def water_table_report(summaries: list[dict[str, Any]]) -> Table:
        frame = pd.DataFrame(summaries).reindex(columns=['period', *WATER_KEYS])
        columns = [Column('period', 'Сезон'),
                   Column('water_peak', 'Максимальный вынос воды', WATER_UNIT, 1, 'number'),
                   Column('water_peak_date', 'Дата', kind='date'),
                   Column('water_peak_q', 'Q объекта на эту дату', Q_UNIT, 1, 'number'),
                   Column('water_peak_wells', 'Скважин на эту дату', decimals=0, kind='number'),
                   Column('water_peak_pressure', f'Рпл на эту дату, абс. {P_UNIT}', decimals=2, kind='number'),
                   Column('wf_peak', 'Максимальный водный фактор, суточный', WF_UNIT, 1, 'number'),
                   Column('wf_peak_date', 'Дата', kind='date'),
                   Column('wf_cum_peak', 'Максимальный водный фактор, накопленный', WF_UNIT, 1, 'number'),
                   Column('wf_cum_peak_date', 'Дата', kind='date')]
        return Table('an-season-water', 'Вынос воды и водный фактор за сезон', frame, columns,
                     note='Вода и фактор — по «Выносу воды по объекту»; пустые ячейки — за сезон нет данных.')

    @staticmethod
    def means_table(parts: list[pd.DataFrame]) -> Table:
        frame = pd.concat(parts, ignore_index=True)
        frame = frame.rename(columns={'period_season': 'season'})
        columns = [Column('season', 'Сезон'), Column('scope', 'Группа'), Column('period', 'Период'),
                   Column('days', 'Суток с расходом', decimals=0, kind='number'),
                   Column('mean', 'Средний суточный расход', Q_UNIT, 1, 'number')]
        return Table('an-season-means', 'Средние суточные расходы объекта и групп', frame[['season', 'scope', 'period', 'days', 'mean']],
                     columns, note='Строка «Весь сезон» — среднее за сезон, остальные — по месяцам.')

    def season_charts(self, result: Result, data: Data, kind: str, period: str, summary: dict[str, Any],
                      means: pd.DataFrame, pressure: pd.DataFrame | None, params: dict[str, Any],
                      fund_frame: pd.DataFrame) -> None:
        """Графики сезона: основной по выбранному виду и второй («Правый график»: по умолчанию фонд скважин)."""
        daily, wells = an_charts.daily_of(data[PRODUCTION], kind, period)
        start, stop = summary['start'], summary['stop']
        factor = data[FACTOR] if FACTOR in data else None
        rates: list[pd.DataFrame] = []                # считается один раз и только если нужен группам

        def group_rates() -> pd.DataFrame:
            if not rates:
                d = data[PRODUCTION]
                d = d[d.kind.eq(kind) & d.period.eq(period)][['well', 'date', 'q']].copy()
                d['well'] = d.well.astype(str)
                rates.append(daily_rates(d, well_scopes(data.mapping, ordered(d.well.unique()))))
            return rates[0]

        def charts_of(view: str) -> list[Chart | None]:
            if view == 'canvas':
                show = list(params['show']) if 'show' in params else list(an_charts.SHOW_DEFAULT)
                water = water_table(factor) if factor is not None and not factor.empty and kind == 'withdrawal' else None
                return [an_charts.canvas_chart(kind, period, show, daily, wells, pressure, water, factor)]
            if view == 'curve':
                show = list(params['show_curve']) if 'show_curve' in params else list(an_charts.CURVE_SHOW_DEFAULT)
                water = water_table(factor) if factor is not None and not factor.empty and kind == 'withdrawal' else None
                return [an_charts.curve_chart(kind, period, daily, wells, pressure, show, water)]
            if view == 'group_mean':
                return [an_charts.group_means_chart(kind, period, means)]
            if view == 'group_mean_months':
                return [an_charts.monthly_groups_chart(kind, period, means)]
            if view == 'fund':
                return [an_charts.fund_chart(kind, period, fund_frame)]
            if view == 'cum_season':
                return [an_charts.cum_groups_season(kind, period, group_rates(), OBJECT_SCOPE)]
            if view == 'cum_months':
                return [an_charts.cum_groups_months(kind, period, group_rates(), OBJECT_SCOPE)]
            if view == 'group_months':
                names = ordered(set(group_rates().scope.astype(str)) - {OBJECT_SCOPE})
                picked = [g for g in params.get('groups') or [] if g in names] or names[:1]
                return [an_charts.cum_group_months(kind, period, group_rates(), g) for g in picked]
            return []

        main, side = params.get('view') or 'canvas', params.get('side') or 'fund'
        charts = charts_of(main) + (charts_of(side) if side != main else [])
        result.charts += [c for c in charts if c is not None]
        start_p, stop_p = summary.get('pressure_start'), pressure_near(pressure, stop)
        if an_charts.pressure_points(pressure, start, stop) is not None and start_p is not None and stop_p is not None:
            result.summary.append(Stat(f'Рпл за сезон · {period}', f'{_signed(stop_p - start_p)} {P_UNIT}',
                                       f'На конец сезона {stop_p:.1f}, на начало {start_p:.1f}'.replace('.', ',')))

    def fund_details(self, result: Result, data: Data, kind: str, period: str, summary: dict[str, Any],
                     fund: list[pd.DataFrame], classes: list[pd.DataFrame], wet: list[pd.DataFrame],
                     counts: list[pd.DataFrame], class_chart: str = 'none',
                     month_chart: str = 'none', months: list[pd.DataFrame] | None = None,
                     edges: tuple[int, ...] = an_wells.DEFAULT_EDGES) -> None:
        """Фонд сезона: табл. 1.4 и 1.5, а для отбора — табл. 1.6 по воде и сводка по воде для текста."""
        wells = an_wells.season_wells(data[PRODUCTION], kind, period)
        scopes = well_scopes(data.mapping, ordered(wells.well))
        fund_frame = an_wells.fund_table(wells, scopes).assign(season=period)
        fund.append(fund_frame)
        if month_chart != 'none' and months is not None:
            by_month, labels = an_wells.month_working(data[PRODUCTION], kind, period, scopes)
            if kind == 'withdrawal':                 # у закачки своя таблица по месяцам — табл. 2.2 (injection_months_table)
                months.append(by_month.assign(season=period, labels=[labels] * len(by_month)))
            chart = an_charts.month_working_chart(kind, period, by_month, labels, an_wells.month_peaks(data[PRODUCTION], kind, period))
            if chart is not None:
                result.charts.append(chart)
        if kind == 'withdrawal':
            classes.append(an_wells.class_table(wells, scopes, edges).assign(season=period))      # закачка: классы — табл. 2.3 (injection_class_table)
        if class_chart != 'none':
            by_class = an_wells.class_counts(wells, scopes, edges)
            counts.append(by_class.assign(season=period))
            for chart in (an_charts.class_share_chart(kind, period, by_class, class_chart, edges),
                          an_charts.class_total_chart(kind, period, by_class, edges)):
                if chart is not None:
                    result.charts.append(chart)
        if kind != 'withdrawal':
            return
        by_well = an_wells.water_by_well(data[WATER] if WATER in data else None, wells, scopes,
                                         summary['start'], summary['stop'])
        if by_well is None:
            if WATER in data:
                result.notes.append(Note(f'{period}: в «Контроль воды» нет объёма воды — таблица «Вода по группам» пропущена.', 'warning'))
            return
        wet.append(an_wells.water_table(by_well).assign(season=period))
        extremes = an_wells.water_extremes(by_well)
        result.summary.append(Stat(f'Скважин с водой · {period}', str(extremes['wet_wells']), 'Суммарная вода за сезон больше нуля'))
        if 'wf_max' in extremes:
            result.summary.append(Stat(f'Максимальный ВФ · {period}', f'{extremes["wf_max"]:.1f} {WF_UNIT}'.replace('.', ','),
                                       f'Скважина {extremes["wf_max_well"]}, группа {extremes["wf_max_group"]}'))

    def class_seasons_details(self, result: Result, data: Data, kind: str, params: dict[str, Any], edges: tuple[int, ...]) -> None:
        """График классов по группам сквозь выбранные сезоны (параметр «Сезоны для сравнения классов»): считается сам, не зависит от «Классы производительности»."""
        chosen = set(params.get('class_seasons') or [])
        seasons = [p for p in periods_of(data[PRODUCTION], kind) if p in chosen]
        if len(seasons) == 1:
            result.notes.append(Note('Сравнение классов по группам: выберите два и более сезона — график за один сезон не строится.'))
        if len(seasons) < 2:
            return
        parts = []
        for season in seasons:
            wells = an_wells.season_wells(data[PRODUCTION], kind, season)
            if not wells.empty:
                parts.append(an_wells.class_counts(wells, well_scopes(data.mapping, ordered(wells.well)), edges).assign(season=season))
        if not parts:
            return
        callouts = 'dot' if params.get('class_chart') == 'dot' else 'box'
        chart = an_charts.class_seasons_chart(kind, pd.concat(parts, ignore_index=True), seasons, callouts, edges)
        if chart is not None:
            result.charts.append(chart)

    def plan_details(self, result: Result, data: Data, kind: str, period: str) -> None:
        """Рис. 1.8: план и факт по группам сезона (модуль «План и факт»), самое большое и маленькое отклонение."""
        if PLAN not in data or data[PLAN].empty:
            return
        plan = plan_compare(data[PRODUCTION], data[PLAN], data.mapping, kind, data.settings)
        part = plan[plan.period.eq(period)]
        if part.empty:
            result.notes.append(Note(f'{period}: в плане нет строк за сезон — график «План и факт по группам» пропущен.', 'warning'))
            return
        by_group = plan_summed(part, 'group')
        by_group = by_group.set_index('group').loc[ordered(by_group.group)].reset_index()
        result.charts.append(PlanFactModule().groups_chart(by_group, period, kind))
        if kind == 'withdrawal':
            result.charts.append(PlanFactModule().months_chart(plan_summed(part, 'month').sort_values('month'), period, kind))
        ext = an_wells.deviation_extremes(by_group)
        if not ext:
            return
        result.summary += [
            Stat(f'Наибольшее отклонение · {period}', f'{_signed(ext["delta_max"])} {UNIT} · {ext["delta_max_group"]}',
                 'Факт минус план, группа с наибольшим превышением'),
            Stat(f'Наименьшее отклонение · {period}', f'{_signed(ext["delta_min"])} {UNIT} · {ext["delta_min_group"]}',
                 'Факт минус план, группа с наибольшим недобором'),
            Stat(f'Выполнение макс./мин. · {period}',
                 f'{ext["percent_max"]:.1f} % · {ext["percent_min"]:.1f} %'.replace('.', ','),
                 f'Макс.: {ext["percent_max_group"]}; мин.: {ext["percent_min_group"]}'),
        ]

    @staticmethod
    def fund_table_report(parts: list[pd.DataFrame]) -> Table:
        frame = pd.concat(parts, ignore_index=True)[['season', 'group', 'fund', 'working', 'percent']]
        columns = [Column('season', 'Сезон'), Column('group', 'Группа'),
                   Column('fund', 'Фонд, скв.', decimals=0, kind='number'),
                   Column('working', 'Работало за сезон, скв.', decimals=0, kind='number'),
                   Column('percent', 'Доля работавших, %', '%', 1, 'number')]
        return Table('an-fund', 'Фонд скважин по группам', frame, columns,
                     note='Фонд — скважины с данными за сезон; работали — с хотя бы одними сутками с расходом.')

    @staticmethod
    def injection_months_table(frame: pd.DataFrame, months: list[Any], period: str, index: int) -> Table:
        columns = [Column('group', 'ГСП'), Column('fund', 'Фонд, скв.', decimals=0, kind='number')]
        columns += [Column(f'm{i}', month_label(m), decimals=0, kind='number') for i, m in enumerate(months)]
        return Table(f'an-inj-wells-{index}', f'Работавшие скважины по месяцам · {period}', frame, columns,
                     note='Скважины с расходом хотя бы в одни сутки месяца; фонд — скважины сезона.')

    @staticmethod
    def injection_class_report(frame: pd.DataFrame, edges: tuple[int, ...]) -> Table:
        keys, labels = injection_keys(edges), an_wells.class_labels(edges)[1:]
        columns = [Column('season', 'Сезон'), Column('group', 'Группа'),
                   Column('zero', 'Нулевой расход за сезон, скв. (номера)')]
        columns += [Column(key, f'{name} тыс. м³/сут, скв. (номера)') for key, name in zip(keys, labels)]
        return Table('an-inj-classes', 'Условная классификация скважин по производительности', frame[['season', 'group', 'zero', *keys]],
                     columns, note='Средний расход за сутки с расходом, тыс. м³/сут; граница класса относится к верхнему. Номера — в скобках.')

    @staticmethod
    def plan_fact_table(frame: pd.DataFrame) -> Table:
        columns = [Column('season', 'Сезон'), Column('group', 'Группа'),
                   Column('plan', f'План, {UNIT}', decimals=2, kind='number'),
                   Column('fact', f'Факт, {UNIT}', decimals=2, kind='number'),
                   Column('delta', f'Факт минус план, {UNIT}', decimals=2, kind='number'),
                   Column('percent', 'Выполнение плана, %', decimals=1, kind='number')]
        return Table('an-inj-plan-fact', 'Плановые и фактические объёмы закачки по группам', frame[['season', 'group', 'plan', 'fact', 'delta', 'percent']],
                     columns, note='Группы — единые имена; итог — строка «Всего». План и факт — за сезон.')

    @staticmethod
    def plan_card_table(frame: pd.DataFrame, months: list[Any], period: str, index: int) -> Table:
        columns = [Column('group', 'ГСП')]
        columns += [Column(f'm{i}', month_label(m), UNIT, 2, 'number') for i, m in enumerate(months)]
        return Table(f'an-inj-plan-card-{index}', f'Технологическая карта: план закачки по месяцам · {period}', frame, columns,
                     note='Рекомендованный объём закачки по группам и месяцам (План по группам).')

    @staticmethod
    def class_table_report(parts: list[pd.DataFrame], edges: tuple[int, ...]) -> Table:
        keys, labels = an_wells.class_keys(edges)[1:], an_wells.class_labels(edges)[1:]
        frame = pd.concat(parts, ignore_index=True)[['season', 'group', 'zero', *keys]]
        columns = [Column('season', 'Сезон'), Column('group', 'Группа'),
                   Column('zero', 'Нулевой расход за сезон, скв. (номера)')]
        columns += [Column(key, f'{name} тыс. м³/сут, скв. (номера)') for key, name in zip(keys, labels)]
        return Table('an-fund-classes', 'Классы производительности скважин', frame, columns,
                     note='Расход — средний за сутки с расходом, тыс. м³/сут; граница класса относится к верхнему. Номера скважин — в скобках.')

    @staticmethod
    def class_counts_report(parts: list[pd.DataFrame], edges: tuple[int, ...]) -> Table:
        keys = an_wells.class_keys(edges)
        frame = pd.concat(parts, ignore_index=True)[['season', 'group', *keys]]
        columns = [Column('season', 'Сезон'), Column('group', 'Группа')]
        columns += [Column(key, name if name == '0' else f'{name}, тыс. м³/сут', decimals=0, kind='number')
                    for key, name in zip(keys, an_wells.class_labels(edges))]
        return Table('an-fund-class-counts', 'Количество скважин с различной производительностью', frame, columns,
                     note='Расход — средний за сутки с расходом, тыс. м³/сут; граница класса относится к верхнему. Класс «0» — скважины без суток с расходом.')

    @staticmethod
    def month_working_report(parts: list[pd.DataFrame]) -> Table:
        first = parts[0]
        keys = [c for c in first.columns if c.startswith('m') and c[1:].isdigit()]
        frame = pd.concat([p[['season', 'group', 'fund', *keys]] for p in parts], ignore_index=True)
        columns = [Column('season', 'Сезон'), Column('group', 'Группа'), Column('fund', 'Фонд', decimals=0, kind='number')]
        columns += [Column(k, label, decimals=0, kind='number') for k, label in zip(keys, first.labels.iloc[0])]
        return Table('an-fund-months', 'Количество эксплуатационных скважин, участвующих в отборе газа по месяцам', frame, columns,
                     note='Работавшая скважина — с хотя бы одними сутками с расходом в месяце. Фонд — скважины с данными за сезон. '
                          'Если у сезонов разное число месяцев, берутся подписи первого сезона.')

    @staticmethod
    def wet_table_report(parts: list[pd.DataFrame]) -> Table:
        frame = pd.concat(parts, ignore_index=True)[['season', 'group', 'wet', 'water', 'wf_max', 'wf_well']]
        columns = [Column('season', 'Сезон'), Column('group', 'Группа'),
                   Column('wet', 'Скважин с водой, скв. (номера)'),
                   Column('water', 'Вода за сезон, м³', decimals=0, kind='number'),
                   Column('wf_max', f'Максимальный водный фактор, {WF_UNIT}', decimals=1, kind='number'),
                   Column('wf_well', 'Скважина с максимальным ВФ')]
        return Table('an-fund-water', 'Вода по группам', frame, columns,
                     note='Водный фактор скважины = вода за сезон / газ за сезон. Источник — «Контроль воды».')
