"""Сезонные показатели: расчёт по сезонам закачки и отбора (без интерфейса).

Сезон — подпись ``period`` в данных проекта (автоопределение или расписание из «Настроек», правятся вручную).
Объём сезона — сумма суточных расходов объекта; источник: эталон узла учёта («БД по учету газа») или сумма по скважинам.
Единицы: расход в данных — м³/сут, на экране — тыс. м³/сут, объём — млн м³.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from ._production import NEUTRAL_PREFIXES

KINDS = ('injection', 'withdrawal')
KIND_LABEL = {'injection': 'Закачка', 'withdrawal': 'Отбор'}
SOURCE_AUTO, SOURCE_WELLS, SOURCE_REF = 'auto', 'wells', 'gas_db'
SOURCE_LABEL = {SOURCE_WELLS: 'Сумма по скважинам', SOURCE_REF: 'Узел учёта'}
REF_COVERAGE = 0.8      # «авто»: эталон берётся, если в сезоне есть его данные не меньше чем за эту долю суток с расходом по скважинам

SEASON_COLUMNS = ['kind', 'period', 'cycle', 'start', 'end', 'span', 'days', 'volume', 'mean', 'max', 'max_date', 'wells',
                  'source', 'volume_wells', 'volume_ref', 'diff_pct', 'delta', 'delta_pct']


def _daily(frame: pd.DataFrame) -> pd.Series:
    """Суточная сумма (м³/сут) по датам; исключённые точки не входят, пропуск остаётся пропуском."""
    v = frame.q.where(~frame.get('_excluded', pd.Series(False, index=frame.index)).fillna(False).astype(bool))
    return v.groupby(frame.date.dt.normalize()).sum(min_count=1).dropna().sort_index()


def cycle_of(kind: str, start: pd.Timestamp) -> int:
    """Цикл — сезон отбора и следующий за ним сезон закачки; его номер — год начала отбора (отбор 2025/2026 и закачка 2026 — цикл 2025).
    Для сезона отбора (с июля — этого года, раньше — предыдущего); закачку к циклу относит ``assign_cycles`` по предшествующему отбору,
    здесь — запасной вариант: закачка весны-лета идёт после отбора прошлой зимы."""
    return start.year if kind == 'withdrawal' and start.month >= 7 else start.year - 1


def cycle_label(cycle: Any) -> str:
    """Подпись цикла: «2025/2026» (отбор 2025/2026 и закачка 2026); вид тире или слэша задают настройки проекта."""
    return f'{int(cycle)}/{int(cycle) + 1}'


def assign_cycles(seasons: pd.DataFrame) -> pd.DataFrame:
    """Закачка относится к циклу ближайшего предшествующего отбора (не дальше года); без такого отбора — по запасному правилу."""
    out = seasons.copy()
    w = out[out.kind.eq('withdrawal')].sort_values('start')
    starts, cycles = w.start.to_numpy(), w.cycle.to_numpy()
    for i in out.index[out.kind.eq('injection')]:
        at = int(np.searchsorted(starts, out.at[i, 'start'].to_datetime64(), side='right')) - 1
        fallback = cycle_of('injection', out.at[i, 'start'])
        out.at[i, 'cycle'] = int(cycles[at]) if at >= 0 and out.at[i, 'start'].year - int(cycles[at]) <= 1 else fallback
    return out


def _stats(daily: pd.Series) -> dict[str, Any]:
    flow = daily[daily > 0]
    if flow.empty:
        return {}
    return {'start': flow.index.min(), 'end': flow.index.max(), 'days': int(len(flow)), 'volume': float(flow.sum()) / 1e6,
            'mean': float(flow.mean()) / 1e3, 'max': float(flow.max()) / 1e3, 'max_date': flow.idxmax()}


def real_periods(df: pd.DataFrame) -> list[str]:
    return [p for p in df.period.dropna().unique() if not str(p).startswith(NEUTRAL_PREFIXES)]


def season_table(df: pd.DataFrame, ref: pd.DataFrame | None = None, source: str = SOURCE_AUTO,
                 periods: list[str] | None = None) -> pd.DataFrame:
    """Одна строка на сезон и вид: границы, сутки, объём (млн м³), средний и максимальный расход (тыс. м³/сут), скважин,
    источник объёма, объём по обоим источникам, расхождение, Δ к прошлому сезону того же вида."""
    rows: list[dict[str, Any]] = []
    for kind in KINDS:
        part = df[df.kind.eq(kind)]
        refd = None
        if ref is not None and len(ref):
            r = ref[ref.kind.eq(kind)]
            refd = (r.set_index(r.date.dt.normalize()).gas.astype(float) * 1e3).groupby(level=0).sum()   # тыс. м³ → м³
        for period in real_periods(part):
            if periods is not None and period not in periods:
                continue
            rows_p = part[part.period.eq(period)]
            wells = _stats(_daily(rows_p))
            if not wells:
                continue
            ref_s = {}
            if refd is not None:
                ref_s = _stats(refd[(refd.index >= wells['start']) & (refd.index <= wells['end'])])
            use_ref = bool(ref_s) and (source == SOURCE_REF or (source == SOURCE_AUTO and ref_s['days'] >= REF_COVERAGE * wells['days']))
            used = ref_s if use_ref else wells
            row = {'kind': kind, 'period': period, 'cycle': cycle_of(kind, used['start']),
                   'span': (used['end'] - used['start']).days + 1,
                   'wells': int(rows_p[rows_p.q > 0].well.nunique()), 'source': SOURCE_LABEL[SOURCE_REF if use_ref else SOURCE_WELLS],
                   'volume_wells': wells['volume'], 'volume_ref': ref_s.get('volume', np.nan),
                   **{k: used[k] for k in ('start', 'end', 'days', 'volume', 'mean', 'max', 'max_date')}}
            row['diff_pct'] = ((ref_s['volume'] - wells['volume']) / wells['volume'] * 100.0
                               if ref_s and wells['volume'] else np.nan)
            rows.append(row)
    out = pd.DataFrame(rows, columns=SEASON_COLUMNS)
    out = out.sort_values(['kind', 'start']).reset_index(drop=True)
    if not out.empty:
        out = assign_cycles(out)
    prev = out.groupby('kind').volume.shift()
    out['delta'] = out.volume - prev
    out['delta_pct'] = (out.delta / prev * 100.0).where(prev > 0)
    return out


def group_table(df: pd.DataFrame, seasons: pd.DataFrame, group_of: Mapping[str, str], groups: list[str] | None = None) -> pd.DataFrame:
    """Объём (млн м³), сутки, средний и максимальный расход по группам в границах сезонов; доля группы в сумме по группам."""
    cols = ['kind', 'period', 'group', 'days', 'volume', 'share', 'mean', 'max']
    rows: list[dict[str, Any]] = []
    for s in seasons.itertuples():
        part = df[df.kind.eq(s.kind) & df.period.eq(s.period)]
        part = part.assign(group=part.well.map(lambda w: group_of.get(str(w), 'Без группы')))
        found = []
        for name, g in part.groupby('group', sort=True):
            if groups and name not in groups:
                continue
            st = _stats(_daily(g))
            if st:
                found.append({'kind': s.kind, 'period': s.period, 'group': name, **{k: st[k] for k in ('days', 'volume', 'mean', 'max')}})
        total = sum(r['volume'] for r in found)
        for r in found:
            r['share'] = r['volume'] / total * 100.0 if total else np.nan
        rows += found
    return pd.DataFrame(rows, columns=cols)


def cycles_table(seasons: pd.DataFrame) -> pd.DataFrame:
    """Закачка и отбор бок о бок: строка на цикл (год), колонки ``i_*`` и ``w_*`` по видам."""
    keys = ['period', 'start', 'end', 'days', 'volume', 'mean', 'max', 'delta', 'delta_pct']
    frame = pd.DataFrame({'cycle': sorted(seasons.cycle.unique())})
    for kind, tag in (('injection', 'i'), ('withdrawal', 'w')):
        part = seasons[seasons.kind.eq(kind)].drop_duplicates('cycle', keep='last').set_index('cycle')
        for k in keys:
            frame[f'{tag}_{k}'] = frame.cycle.map(part[k]) if k in part else np.nan
    return frame


# ---------- месяцы внутри сезона ----------

MONTHS = ('Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь')
MONTH_COLUMNS = ['kind', 'period', 'no', 'month', 'moy', 'days', 'volume', 'mean', 'max', 'partial', 'delta', 'delta_pct']


def month_name(month: pd.Period) -> str:
    return f'{MONTHS[month.month - 1]} {month.year}'


def _ref_daily(ref: pd.DataFrame | None, kind: str) -> pd.Series | None:
    if ref is None or not len(ref):
        return None
    r = ref[ref.kind.eq(kind)]
    return (r.set_index(r.date.dt.normalize()).gas.astype(float) * 1e3).groupby(level=0).sum() if len(r) else None


def _month_rows(daily: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    """Календарные месяцы в границах сезона; ``partial`` — сезон начался позже 1-го числа или закончился раньше конца месяца."""
    daily = daily[(daily.index >= start) & (daily.index <= end)]
    rows = []
    for month, part in daily.groupby(daily.index.to_period('M')):
        st = _stats(part)
        if not st:
            continue
        rows.append({'month': month, 'moy': month.month, 'days': st['days'], 'volume': st['volume'], 'mean': st['mean'], 'max': st['max'],
                     'partial': bool(start > month.start_time or end < month.end_time.normalize())})
    return rows


def month_table(df: pd.DataFrame, seasons: pd.DataFrame, ref: pd.DataFrame | None = None) -> pd.DataFrame:
    """Месячные показатели каждого сезона (объект): объём, сутки, средний и максимальный расход; тот же источник, что у сезона.
    Δ — к тому же календарному месяцу предыдущего (по номеру) сезона того же вида; ``no`` — номер сезона вида."""
    rows: list[dict[str, Any]] = []
    for s in seasons.itertuples():
        if s.source == SOURCE_LABEL[SOURCE_REF]:
            daily = _ref_daily(ref, s.kind)
        else:
            daily = _daily(df[df.kind.eq(s.kind) & df.period.eq(s.period)])
        if daily is None:
            continue
        rows += [{'kind': s.kind, 'period': s.period, **r} for r in _month_rows(daily, s.start, s.end)]
    out = pd.DataFrame(rows, columns=[c for c in MONTH_COLUMNS if c not in ('no', 'delta', 'delta_pct')])
    if out.empty:
        return out
    number = seasons.sort_values('start').groupby('kind').cumcount() + 1       # номер сезона вида по порядку
    out['no'] = [int(number[seasons[seasons.kind.eq(k) & seasons.period.eq(p)].index[0]]) for k, p in zip(out.kind, out.period)]
    out = out.sort_values(['kind', 'no', 'month']).reset_index(drop=True)
    key = out.set_index(['kind', 'no', 'moy']).volume
    prev = pd.Series([key.get((k, n - 1, m), np.nan) for k, n, m in zip(out.kind, out.no, out.moy)], index=out.index)
    out['delta'] = out.volume - prev
    out['delta_pct'] = (out.delta / prev * 100.0).where(prev > 0)
    return out


def month_group_table(df: pd.DataFrame, seasons: pd.DataFrame, group_of: Mapping[str, str], groups: list[str] | None = None) -> pd.DataFrame:
    """Объём (млн м³) по группам и месяцам каждого сезона; группы — по скважинам."""
    rows: list[dict[str, Any]] = []
    for s in seasons.itertuples():
        part = df[df.kind.eq(s.kind) & df.period.eq(s.period)]
        part = part.assign(group=part.well.map(lambda w: group_of.get(str(w), 'Без группы')))
        for name, g in part.groupby('group', sort=True):
            if groups and name not in groups:
                continue
            rows += [{'kind': s.kind, 'period': s.period, 'group': name, **r}
                     for r in _month_rows(_daily(g), s.start, s.end)]
    return pd.DataFrame(rows, columns=['kind', 'period', 'group', 'month', 'moy', 'days', 'volume', 'mean', 'max', 'partial'])
