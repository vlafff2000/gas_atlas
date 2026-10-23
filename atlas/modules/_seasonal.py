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
    """Год цикла для пары «закачка — отбор»: год начала закачки и год начала отбора того же года (с июля)."""
    return start.year if kind == 'injection' or start.month >= 7 else start.year - 1


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
