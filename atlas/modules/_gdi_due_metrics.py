"""Показатели динамики скважины для «Анализа скважин для включения в программу ГДИ».

Всё считается по суточным данным отбора за два последних сезона: накопленный расход на одинаковом отрезке сезона, согласованность
недельной динамики скважины с группой и объектом, отклик расхода на раскрытие КРУ (ЭЛПРО). Это подсказки с видимыми числами,
решение — за инженером. Сезон без данных — пропуск, не нуль.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._production import NEUTRAL_PREFIXES

METRIC_COLUMNS = ['cum_last', 'cum_prev', 'cum_days', 'cum_change', 'cum_group_change', 'cum_gap', 'sync_group', 'sync_obj', 'slope_well', 'slope_group',
                  'slope_obj', 'slope_gap_group', 'slope_gap_obj', 'open_last', 'open_prev', 'open_change', 'eff_last', 'eff_prev', 'eff_change', 'eff_gap', 'open_corr']
STEP_MIN = 3          # меньше трёх недельных шагов — совпадение динамики не оцениваем
DAYS_MIN = 14         # и короче двух недель ряда — тоже
FLAT = 0.01           # недельное изменение индекса меньше 1% считаем «без изменения»


def withdrawal_days(prod: pd.DataFrame) -> pd.DataFrame:
    """Дни отбора с расходом > 0 и названием сезона; столбец сезона — ``period``."""
    if prod is None or prod.empty or 'q' not in prod:
        return pd.DataFrame(columns=['well', 'date', 'q', 'period'])
    col = 'period' if 'period' in prod else 'season'
    df = prod[prod.kind.eq('withdrawal') & prod.q.gt(0) & prod[col].notna()].copy()
    df = df[~df[col].astype(str).str.startswith(NEUTRAL_PREFIXES) & df[col].astype(str).ne('')]
    df['period'] = df[col].astype(str)
    df['well'] = df.well.astype(str)
    df['date'] = pd.to_datetime(df.date).dt.normalize()
    return df[['well', 'date', 'q', 'period']]


def last_two(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """Названия последнего и предыдущего сезонов отбора по дате начала."""
    if df.empty:
        return None, None
    order = df.groupby('period').date.min().sort_values().index.tolist()
    return order[-1], (order[-2] if len(order) > 1 else None)


def _slope_pct(index: pd.Series) -> float:
    """Наклон индекса расхода, % от среднего за сезон на 30 суток."""
    days = (index.index - index.index[0]).days.to_numpy(dtype=float)
    return float(np.polyfit(days, index.to_numpy(dtype=float), 1)[0] * 30 * 100) if len(index) >= 2 and days.max() > 0 else np.nan


def _weekly_sync(a: pd.Series, b: pd.Series) -> float:
    """Доля недельных шагов, где скважина и эталон движутся в одну сторону (шаги без изменения не считаются), %."""
    wa, wb = a.resample('7D').mean().diff().dropna(), b.resample('7D').mean().diff().dropna()
    common = wa.index.intersection(wb.index)
    wa, wb = wa.loc[common], wb.loc[common]
    moving = (wa.abs() > FLAT) & (wb.abs() > FLAT)
    if moving.sum() < STEP_MIN:
        return np.nan
    return float((np.sign(wa[moving]) == np.sign(wb[moving])).mean() * 100)


def cumulative(days: pd.DataFrame, last: str | None, prev: str | None, group_of: dict[str, str]) -> pd.DataFrame:
    """Накопленный расход скважины (млн м³) за один и тот же отрезок от начала сезона: последний и предыдущий сезоны, изменение и отставание от группы."""
    cols = ['well', 'cum_last', 'cum_prev', 'cum_days', 'cum_change', 'cum_group_change', 'cum_gap']
    if last is None:
        return pd.DataFrame(columns=cols)
    span = {}
    for p in (last, prev):
        if p is not None:
            d = days[days.period.eq(p)].date
            span[p] = (d.min(), (d.max() - d.min()).days + 1)
    n = min(v[1] for v in span.values())            # сезон может ещё идти: сравниваем одинаковое число суток от начала
    total = {}
    for p, (start, _) in span.items():
        d = days[days.period.eq(p) & days.date.lt(start + pd.Timedelta(days=n))]
        total[p] = d.groupby('well').q.sum() / 1e3
    out = pd.DataFrame({'well': sorted(days.well.unique())})
    out['cum_last'] = out.well.map(total[last])
    out['cum_prev'] = out.well.map(total[prev]) if prev is not None else np.nan
    out['cum_days'] = n
    out['cum_change'] = (out.cum_last - out.cum_prev) / out.cum_prev * 100
    out['cum_group_change'] = out.assign(g=out.well.map(lambda w: group_of.get(w, ''))).groupby('g').cum_change.transform('median')
    out['cum_gap'] = out.cum_change - out.cum_group_change
    return out[cols]


def dynamics(days: pd.DataFrame, last: str | None, group_of: dict[str, str]) -> pd.DataFrame:
    """Согласованность динамики внутри последнего сезона: сутки каждой скважины делятся на её средний расход (индекс), затем
    индекс скважины сравнивается с индексом группы и объекта. ``sync_*`` — доля совпавших недельных шагов, %; ``slope_*`` — тренд, % на 30 суток;
    ``slope_gap_obj`` — тренд скважины минус тренд объекта (п.п.)."""
    cols = ['well', 'sync_group', 'sync_obj', 'slope_well', 'slope_group', 'slope_obj', 'slope_gap_group', 'slope_gap_obj']
    if last is None:
        return pd.DataFrame(columns=cols)
    d = days[days.period.eq(last)].copy()
    d['idx'] = d.q / d.groupby('well').q.transform('mean')
    d['group'] = d.well.map(lambda w: group_of.get(w, ''))
    wide = d.pivot_table(index='date', columns='well', values='idx', aggfunc='mean').sort_index()
    obj = wide.mean(axis=1)
    groups = {g: wide[list(ws)].mean(axis=1) for g, ws in d.groupby('group').well.unique().items()}
    s_obj = _slope_pct(obj)
    rows = []
    for w in wide.columns:
        s = wide[w].dropna()
        g = groups.get(group_of.get(w, ''), obj)
        if len(s) < DAYS_MIN:
            rows.append((w, np.nan, np.nan, np.nan, np.nan, s_obj, np.nan, np.nan))
            continue
        sw, sg = _slope_pct(s), _slope_pct(g)
        rows.append((w, _weekly_sync(s, g), _weekly_sync(s, obj), sw, sg, s_obj, sw - sg, sw - s_obj))
    return pd.DataFrame(rows, columns=cols)


def kru_response(elpro: pd.DataFrame | None, days: pd.DataFrame, last: str | None, prev: str | None, group_of: dict[str, str]) -> pd.DataFrame:
    """Раскрытие КРУ (ЭЛПРО, ``y``, %) и отклик расхода: среднее раскрытие по сезонам, «расход на 1% раскрытия», его изменение и отставание от медианы группы (расход от раскрытия нелинеен, поэтому сравнение с группой).
    Больше раскрытие — должен быть больше расход; если расход падает при том же или большем раскрытии, продуктивность снизилась."""
    cols = ['well', 'open_last', 'open_prev', 'open_change', 'eff_last', 'eff_prev', 'eff_change', 'eff_gap', 'open_corr']
    if elpro is None or elpro.empty or 'y' not in elpro or last is None:
        return pd.DataFrame(columns=cols)
    e = elpro[elpro.kind.eq('withdrawal')] if 'kind' in elpro else elpro
    e = e.assign(well=e.well.astype(str), date=pd.to_datetime(e.date).dt.normalize())
    e = e[e.y.gt(0) & e.q.gt(0)]

    def window(p):
        if p is None:
            return e.iloc[0:0]
        r = days[days.period.eq(p)].date
        return e[e.date.between(r.min(), r.max())]
    el, ep = window(last), window(prev)
    out = pd.DataFrame({'well': sorted(el.well.unique())})
    out['open_last'] = out.well.map(el.groupby('well').y.mean())
    out['open_prev'] = out.well.map(ep.groupby('well').y.mean()) if not ep.empty else np.nan
    out['open_change'] = (out.open_last - out.open_prev) / out.open_prev * 100
    out['eff_last'] = out.well.map(el.groupby('well').q.mean()) / out.open_last
    out['eff_prev'] = out.well.map(ep.groupby('well').q.mean()) / out.open_prev if not ep.empty else np.nan
    out['eff_change'] = (out.eff_last - out.eff_prev) / out.eff_prev * 100
    out['eff_gap'] = out.eff_change - out.assign(g=out.well.map(lambda w: group_of.get(w, ''))).groupby('g').eff_change.transform('median')
    corr = el.groupby('well').apply(lambda g: g.q.corr(g.y) if len(g) >= DAYS_MIN and g.y.nunique() > 1 else np.nan, include_groups=False)
    out['open_corr'] = out.well.map(corr)
    return out[cols]
