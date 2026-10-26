"""Авторский надзор: фонд скважин за сезон — табл. 1.4, 1.5, 1.6 отчёта АН и разбор отклонений плана (рис. 1.8).

Фонд — скважины, по которым есть строки за сезон. Работавшие — с хотя бы одними сутками с положительным расходом.
Классы производительности — средний расход за сутки с расходом, тыс. м³/сут (как в сезонной сводке ``an_report``).
Вода по скважинам — набор «Контроль воды» (объём воды, м³) за даты сезона; водный фактор = вода / газ сезона, л/тыс. м³.
Группы приходят готовой схемой ``scopes`` (скважина → группа, единые имена из ``an_report.well_scopes``).
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from atlas.engine.core.config import ordered

LOW_LIMIT = 100          # тыс. м³/сут: граница класса «менее 100 тысяч» (табл. 1.5)
TOTAL = 'Всего'
# Табл. 1.5 отчёта: классы среднего расхода за сутки с расходом, тыс. м³/сут; граница класса — в верхнем. Нулевой класс — скважины без суток с расходом.
CLASS_EDGES = (100, 150, 200, 250, 300)
CLASS_NAMES = ('0', 'Менее 100', 'От 100 до 150', 'От 150 до 200', 'От 200 до 250', 'От 250 до 300', 'Более 300')
CLASS_KEYS = tuple(f'k{i}' for i in range(len(CLASS_NAMES)))
WF_UNIT = 'л/тыс. м³'


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


def class_table(wells: pd.DataFrame, scopes: Mapping[str, str]) -> pd.DataFrame:
    """Табл. 1.5: по группам — число и номера скважин с нулевым расходом за сезон, с расходом менее 100 тыс. м³/сут и не менее."""
    w = wells.assign(group=wells.well.map(scopes), rate_k=wells.rate / 1000)
    w['cls'] = np.where(w.days.eq(0), 'zero', np.where(w.rate_k.lt(LOW_LIMIT), 'low', 'high'))
    rows = []
    for name, part in [(TOTAL, w)] + [(g, w[w.group.eq(g)]) for g in ordered(w.group.unique())]:
        rows.append({
            'group': name,
            'zero': _numbers(ordered(part[part.cls.eq('zero')].well)),
            'low': _numbers(ordered(part[part.cls.eq('low')].well)),
            'high': _numbers(ordered(part[part.cls.eq('high')].well)),
        })
    return pd.DataFrame(rows)


def class_counts(wells: pd.DataFrame, scopes: Mapping[str, str]) -> pd.DataFrame:
    """Табл. 1.5 отчёта: по группам число скважин в каждом из семи классов производительности; строка «Всего» — первая.

    Колонки ``k0``…``k6`` — числа, ``zero_numbers`` — номера скважин нулевого класса."""
    w = wells.assign(group=wells.well.map(scopes), rate_k=wells.rate / 1000)
    index = np.searchsorted(np.array(CLASS_EDGES, float), w.rate_k.to_numpy(float), side='right') + 1
    w['cls'] = np.where(w.days.eq(0), 0, index)
    rows = []
    for name, part in [(TOTAL, w)] + [(g, w[w.group.eq(g)]) for g in ordered(w.group.unique())]:
        counts = np.bincount(part.cls.to_numpy(int), minlength=len(CLASS_KEYS))
        rows.append({'group': name, **dict(zip(CLASS_KEYS, (int(v) for v in counts))),
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
