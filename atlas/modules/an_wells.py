"""Авторский надзор: фонд скважин за сезон — табл. 1.4, 1.5, 1.6 отчёта АН и разбор отклонений плана (рис. 1.8).

Фонд — скважины, по которым есть строки за сезон. Работавшие — с хотя бы одними сутками с положительным расходом.
Классы производительности — средний расход за сутки с расходом, тыс. м³/сут (как в сезонной сводке ``an_report``).
Вода по скважинам — набор «Контроль воды» (объём воды, м³) за даты сезона; водный фактор = вода / газ сезона, л/тыс. м³.
Группы приходят готовой схемой ``scopes`` (скважина → группа, единые имена из ``an_report.well_scopes``).
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from atlas.engine.core.config import ordered

LOW_LIMIT = 100          # тыс. м³/сут: граница двухклассовой таблицы по умолчанию (табл. 1.5); теперь — первая граница схемы
TOTAL = 'Всего'
# Классы среднего расхода за сутки с расходом, тыс. м³/сут; граница класса — в верхнем. Класс «0» — скважины без суток с расходом.
DEFAULT_EDGES = (100, 150, 200, 250, 300)   # схема до настройки: та же, что была в табл. 1.5 и 2.3
DEFAULT_COUNT = 6                           # классов с расходом в автоматическом режиме (как у DEFAULT_EDGES)
CLASS_STEP = 5                              # автоматические границы кратны 5 тыс. м³/сут
WF_UNIT = 'л/тыс. м³'


def class_labels(edges: Sequence[int]) -> tuple[str, ...]:
    """Подписи классов: «0», затем диапазоны по границам — «Менее a», «От a до b», …, «Более z». Без границ — один класс «С расходом»."""
    if not edges:
        return ('0', 'С расходом')
    ranges = [f'Менее {edges[0]}', *(f'От {a} до {b}' for a, b in zip(edges, edges[1:])), f'Более {edges[-1]}']
    return ('0', *ranges)


def class_keys(edges: Sequence[int]) -> tuple[str, ...]:
    """Колонки классов: ``k0`` — «0», далее ``k1``… — диапазоны в порядке ``class_labels``."""
    return tuple(f'k{i}' for i in range(len(class_labels(edges))))


def class_index(days: np.ndarray, rate_k: np.ndarray, edges: Sequence[int]) -> np.ndarray:
    """Номер класса по скважинам: 0 — нет суток с расходом; 1… — диапазон по границам (граница относится к верхнему классу)."""
    index = np.searchsorted(np.asarray(edges, float), rate_k, side='right') + 1
    return np.where(days == 0, 0, index)


def parse_edges(text: str) -> tuple[int, ...]:
    """Ручные границы из строки «100, 150, 200»: целые положительные числа по возрастанию, без повторов. Иначе ValueError с пояснением."""
    parts = [p for p in re.split(r'[\s,;]+', str(text or '')) if p]
    if not parts:
        raise ValueError('не указано ни одной границы')
    for p in parts:
        if not p.isdigit() or int(p) <= 0:
            raise ValueError(f'«{p}» — не целое положительное число (дробные границы не используются)')
    edges = tuple(int(p) for p in parts)
    if any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError('границы должны идти по возрастанию без повторов')
    return edges


def auto_edges(rates_k: Iterable[float], count: int = DEFAULT_COUNT) -> tuple[int, ...]:
    """Подсказка границ: квантили среднего расхода по скважинам с расходом (примерно равное число скважин в классе),
    округлённые до кратных ``CLASS_STEP``. Совпавшие границы убираются, поэтому классов может стать меньше ``count``."""
    values = np.asarray(list(rates_k), float)
    values = values[np.isfinite(values) & (values > 0)]
    if values.size == 0 or count < 2:
        return ()
    raw = np.quantile(values, np.arange(1, count) / count)
    rounded = CLASS_STEP * np.maximum(1, np.floor(raw / CLASS_STEP + 0.5))
    return tuple(dict.fromkeys(int(v) for v in rounded))


CLASS_NAMES = class_labels(DEFAULT_EDGES)
CLASS_KEYS = class_keys(DEFAULT_EDGES)


def season_wells(prod: pd.DataFrame, kind: str, period: str) -> pd.DataFrame:
    """Скважины сезона: well, days (сутки с расходом), gas (м³ за сезон), rate (м³/сут, среднее по суткам с расходом)."""
    d = prod[prod.kind.eq(kind) & prod.period.eq(period)][['well', 'date', 'q']].copy()
    d['well'] = d.well.astype(str)
    fund = pd.DataFrame({'well': ordered(d.well.unique())})
    pos = d[d.q.gt(0)].groupby('well').q.agg(days='count', gas='sum', rate='mean').reset_index()
    out = fund.merge(pos, on='well', how='left')
    out['days'] = out.days.fillna(0).astype(int)
    out['gas'] = out.gas.fillna(0.0)
    out['rate'] = out.rate.fillna(0.0)
    return out


def _numbers(wells: list[str]) -> str:
    return f'{len(wells)} ({", ".join(wells)})' if wells else '0'


def fund_table(wells: pd.DataFrame, scopes: Mapping[str, str]) -> pd.DataFrame:
    """Табл. 1.4: по группам — фонд, работавшие за сезон, доля работавших (%)."""
    w = wells.assign(group=wells.well.map(scopes), working=wells.days.gt(0))
    rows = [{'group': TOTAL, 'fund': len(w), 'working': int(w.working.sum())}]
    for group in ordered(w.group.unique()):
        part = w[w.group.eq(group)]
        rows.append({'group': group, 'fund': len(part), 'working': int(part.working.sum())})
    out = pd.DataFrame(rows)
    out['percent'] = np.where(out.fund > 0, out.working / out.fund.where(out.fund > 0) * 100, np.nan)
    return out


def class_table(wells: pd.DataFrame, scopes: Mapping[str, str], edges: Sequence[int] = DEFAULT_EDGES) -> pd.DataFrame:
    """Табл. 1.5 (две группы): по группам — число и номера скважин с нулевым расходом за сезон, с расходом ниже первой границы и не ниже."""
    split = edges[0] if edges else LOW_LIMIT
    w = wells.assign(group=wells.well.map(scopes), rate_k=wells.rate / 1000)
    w['cls'] = np.where(w.days.eq(0), 'zero', np.where(w.rate_k.lt(split), 'low', 'high'))
    rows = []
    for name, part in [(TOTAL, w)] + [(g, w[w.group.eq(g)]) for g in ordered(w.group.unique())]:
        rows.append({
            'group': name,
            'zero': _numbers(ordered(part[part.cls.eq('zero')].well)),
            'low': _numbers(ordered(part[part.cls.eq('low')].well)),
            'high': _numbers(ordered(part[part.cls.eq('high')].well)),
        })
    return pd.DataFrame(rows)


MONTH_NAMES = ('Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек')


def month_working(prod: pd.DataFrame, kind: str, period: str, scopes: Mapping[str, str]) -> tuple[pd.DataFrame, list[str]]:
    """Табл. 1.4 отчёта: по группам — фонд сезона и число скважин, работавших в каждом месяце (хотя бы одни сутки с расходом).

    Строка «Всего» — первая; колонки ``m0``…``m{n-1}`` идут по месяцам сезона, подписи месяцев — во втором результате («Ноя.24»)."""
    d = prod[prod.kind.eq(kind) & prod.period.eq(period)][['well', 'date', 'q']].copy()
    d['well'] = d.well.astype(str)
    d['group'] = d.well.map(scopes)
    d['month'] = d.date.dt.to_period('M')
    months = sorted(d.month.unique())
    working = d[d.q.gt(0)].groupby(['group', 'month']).well.nunique()
    fund = d.groupby('group').well.nunique()
    total_working = d[d.q.gt(0)].groupby('month').well.nunique()
    keys = [f'm{i}' for i in range(len(months))]
    rows = [{'group': TOTAL, 'fund': int(d.well.nunique()), **{k: int(total_working.get(m, 0)) for k, m in zip(keys, months)}}]
    for group in ordered(d.group.dropna().unique()):
        rows.append({'group': group, 'fund': int(fund.get(group, 0)),
                     **{k: int(working.get((group, m), 0)) for k, m in zip(keys, months)}})
    return pd.DataFrame(rows), [f'{MONTH_NAMES[m.month - 1]}.{str(m.year)[2:]}' for m in months]


def month_peaks(prod: pd.DataFrame, kind: str, period: str) -> list[tuple[int, Any]]:
    """Максимум скважин, работавших одновременно в одни сутки, по месяцам сезона (те же месяцы, что в ``month_working``): (число, дата первых суток с максимумом)."""
    d = prod[prod.kind.eq(kind) & prod.period.eq(period)][['well', 'date', 'q']]
    if d.empty:
        return []
    days = d[d.q.gt(0)].assign(date=lambda x: x.date.dt.normalize()).groupby('date').well.nunique()
    out = []
    for month in sorted(d.date.dt.to_period('M').unique()):
        part = days[days.index.to_period('M') == month]
        out.append((int(part.max()), part.idxmax()) if not part.empty else (0, None))
    return out


def class_counts(wells: pd.DataFrame, scopes: Mapping[str, str], edges: Sequence[int] = DEFAULT_EDGES) -> pd.DataFrame:
    """Табл. 1.5 отчёта: по группам число скважин в каждом классе производительности (``class_keys(edges)``); строка «Всего» — первая.

    Колонки ``k0``… — числа, ``zero_numbers`` — номера скважин нулевого класса."""
    keys = class_keys(edges)
    w = wells.assign(group=wells.well.map(scopes), rate_k=wells.rate / 1000)
    w['cls'] = class_index(w.days.to_numpy(), w.rate_k.to_numpy(float), edges)
    rows = []
    for name, part in [(TOTAL, w)] + [(g, w[w.group.eq(g)]) for g in ordered(w.group.unique())]:
        counts = np.bincount(part.cls.to_numpy(int), minlength=len(keys))
        rows.append({'group': name, **dict(zip(keys, (int(v) for v in counts))),
                     'zero_numbers': _numbers(ordered(part[part.cls.eq(0)].well))})
    return pd.DataFrame(rows)


def water_by_well(water: pd.DataFrame | None, wells: pd.DataFrame, scopes: Mapping[str, str],
                  start: Any, stop: Any) -> pd.DataFrame | None:
    """Вода по скважинам за сезон: well, group, gas (м³), water (м³), wf (л/тыс. м³). None, если нет объёма воды."""
    if water is None or water.empty or 'water_volume_m3' not in water:
        return None
    v = water.assign(well=water.well.astype(str), date=pd.to_datetime(water.date).dt.normalize(),
                     v=pd.to_numeric(water.water_volume_m3, errors='coerce'))
    v = v[v.v.notna() & v.v.ge(0) & v.date.between(pd.Timestamp(start), pd.Timestamp(stop))]
    w = v.groupby('well').v.sum().rename('water').reset_index()
    out = wells[['well', 'gas']].merge(w, on='well', how='left')
    out['water'] = out.water.fillna(0.0)
    out['group'] = out.well.map(scopes)
    out['wf'] = np.where(out.gas > 0, out.water * 1e6 / out.gas.where(out.gas > 0), np.nan)   # м³ воды на тыс. м³ газа ×1000
    return out


def water_table(by_well: pd.DataFrame) -> pd.DataFrame:
    """Табл. 1.6: по группам — скважины с водой за сезон (число и номера), вода, максимальный водный фактор и его скважина."""
    rows = []
    for name, part in [(TOTAL, by_well)] + [(g, by_well[by_well.group.eq(g)]) for g in ordered(by_well.group.unique())]:
        wet = part[part.water.gt(0)]
        top = wet.loc[wet.wf.idxmax()] if wet.wf.notna().any() else None
        rows.append({
            'group': name,
            'wet': _numbers(ordered(wet.well)),
            'water': part.water.sum(),
            'wf_max': float(top.wf) if top is not None else np.nan,
            'wf_well': str(top.well) if top is not None else '',
        })
    return pd.DataFrame(rows)


def water_extremes(by_well: pd.DataFrame) -> dict[str, Any]:
    """Итоги для текста под табл. 1.6: сколько скважин с водой и максимальный водный фактор среди них."""
    wet = by_well[by_well.water.gt(0)]
    out: dict[str, Any] = {'wet_wells': int(len(wet))}
    if wet.wf.notna().any():
        top = wet.loc[wet.wf.idxmax()]
        out.update(wf_max=float(top.wf), wf_max_well=str(top.well), wf_max_group=top.group)
    return out


def deviation_extremes(by_group: pd.DataFrame) -> dict[str, Any]:
    """Самое большое и самое маленькое отклонение факта от плана среди групп: абсолютное (млн м³) и в процентах.

    ``by_group`` — как ``plan_fact.summed`` по группам: group, plan, fact, percent, delta. Группы без факта не участвуют.
    """
    g = by_group[by_group.fact.notna() & by_group.plan.gt(0)]
    out: dict[str, Any] = {}
    if g.empty:
        return out
    hi, lo = g.loc[g.delta.idxmax()], g.loc[g.delta.idxmin()]
    out.update(delta_max=float(hi.delta), delta_max_group=hi.group, delta_min=float(lo.delta), delta_min_group=lo.group)
    hi, lo = g.loc[g.percent.idxmax()], g.loc[g.percent.idxmin()]
    out.update(percent_max=float(hi.percent), percent_max_group=hi.group, percent_min=float(lo.percent), percent_min_group=lo.group)
    return out
