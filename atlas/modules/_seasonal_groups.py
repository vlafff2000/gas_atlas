"""Сезонные показатели по группам: расчёт (без интерфейса).

Всё считается по скважинам: объём группы — сумма её скважин, доля — от суммы всех групп сезона. Исключённые точки и пропуски
(«нет данных») не входят; ноль в строке — простой. Подсказки (дисбаланс, мало работала) — только подсказки с видимой причиной:
решает инженер.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from . import _seasonal as S

WELL_COLUMNS = ['kind', 'period', 'cycle', 'group', 'well', 'span', 'flow_days', 'idle_days', 'volume', 'work_pct', 'share', 'status']
GROUP_COLUMNS = ['kind', 'period', 'cycle', 'group', 'volume', 'share', 'delta_share', 'wells', 'wells_work', 'wells_idle', 'idle_days']
BALANCE_COLUMNS = ['cycle', 'group', 'injection', 'withdrawal', 'diff', 'ratio', 'hint']


def _live(frame: pd.DataFrame) -> pd.DataFrame:
    """Строки без исключённых точек и без пропусков."""
    excluded = frame.get('_excluded', pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    return frame[~excluded & frame.q.notna()]


def well_table(df: pd.DataFrame, seasons: pd.DataFrame, group_of: Mapping[str, str], work_low: float) -> pd.DataFrame:
    """Строка на скважину и сезон: суток с расходом, суток простоя (нулевой расход), объём (млн м³), доля в группе, работа в %
    от суток сезона. Статус — подсказка: простаивала весь сезон или работала меньше ``work_low`` % суток."""
    rows: list[dict[str, Any]] = []
    for s in seasons.itertuples():
        part = _live(df[df.kind.eq(s.kind) & df.period.eq(s.period)])
        for well, w in part.groupby(part.well.astype(str)):
            flow = w[w.q > 0]
            idle = int((w.q == 0).sum())
            span = int(s.span)
            work = float(len(flow)) / span * 100.0 if span else np.nan
            status = ''
            if flow.empty:
                status = 'простаивала весь сезон'
            elif work < work_low:
                status = f'работала {work:.0f} % суток сезона (порог {work_low:g} %)'
            rows.append({'kind': s.kind, 'period': s.period, 'cycle': s.cycle, 'group': group_of.get(well, 'Без группы'),
                         'well': well, 'span': span, 'flow_days': int(len(flow)), 'idle_days': idle,
                         'volume': float(flow.q.sum()) / 1e6, 'work_pct': work, 'share': np.nan, 'status': status})
    out = pd.DataFrame(rows, columns=WELL_COLUMNS)
    if out.empty:
        return out
    total = out.groupby(['kind', 'period']).volume.transform('sum')
    out['share'] = (out.volume / total * 100.0).where(total > 0)
    return out


def _season_order(seasons: pd.DataFrame) -> dict[tuple[str, str], int]:
    """Номер сезона внутри своего вида по порядку начала: 1, 2, …"""
    ordered = seasons.sort_values('start')
    number = ordered.groupby('kind').cumcount() + 1
    return {(k, p): int(n) for k, p, n in zip(ordered.kind, ordered.period, number)}


def group_table(wells: pd.DataFrame, seasons: pd.DataFrame, groups: list[str] | None = None) -> pd.DataFrame:
    """Строка на группу и сезон: объём, доля в сумме всех групп сезона, Δ доли к предыдущему сезону того же вида (п. п.),
    скважин с данными, работало, простаивало целиком, суток простоя. Доли считаются до фильтра по группам."""
    cols = GROUP_COLUMNS
    if wells.empty:
        return pd.DataFrame(columns=cols)
    g = wells.groupby(['kind', 'period', 'group']).agg(
        volume=('volume', 'sum'), wells=('well', 'nunique'), wells_work=('flow_days', lambda x: int((x > 0).sum())),
        idle_days=('idle_days', 'sum')).reset_index()
    cycle = seasons.set_index(['kind', 'period']).cycle
    g['cycle'] = [cycle.get((k, p)) for k, p in zip(g.kind, g.period)]
    total = g.groupby(['kind', 'period']).volume.transform('sum')
    g['share'] = (g.volume / total * 100.0).where(total > 0)
    g['wells_idle'] = g.wells - g.wells_work
    order = _season_order(seasons)
    by_no = {(k, n): p for (k, p), n in order.items()}
    share = {(k, p, gr): s for k, p, gr, s in zip(g.kind, g.period, g.group, g.share)}
    prev = [share.get((k, by_no.get((k, order[(k, p)] - 1)), gr), np.nan) for k, p, gr in zip(g.kind, g.period, g.group)]
    g['delta_share'] = g.share - np.array(prev, float)
    g = g.assign(_no=[order[(k, p)] for k, p in zip(g.kind, g.period)])
    g = g.sort_values(['kind', '_no', 'group']).drop(columns='_no').reset_index(drop=True)
    if groups:
        g = g[g.group.isin(groups)]
    return g[cols]


def balance_table(groups: pd.DataFrame, groups_filter: list[str] | None, tol: float) -> pd.DataFrame:
    """Закачка и отбор группы по циклам (год). Подсказка — если отбор отличается от закачки больше чем на ``tol`` %
    или одна сторона цикла без данных. Строка «Итого» — сумма выбранных групп."""
    cols = BALANCE_COLUMNS
    if groups.empty:
        return pd.DataFrame(columns=cols)
    part = groups if not groups_filter else groups[groups.group.isin(groups_filter)]
    if part.empty:
        return pd.DataFrame(columns=cols)
    pv = part.groupby(['cycle', 'group', 'kind']).volume.sum().unstack('kind')
    total = pv.groupby(level='cycle').sum(min_count=1).assign(group='Итого').reset_index().set_index(['cycle', 'group'])
    pv = pd.concat([pv, total]).reset_index()
    out = []
    for r in pv.itertuples(index=False):
        i = getattr(r, 'injection', np.nan)
        w = getattr(r, 'withdrawal', np.nan)
        ratio = w / i * 100.0 if i and not np.isnan(i) and not np.isnan(w) else np.nan
        hint = ''
        if np.isnan(i) or np.isnan(w):
            hint = 'в цикле нет ' + ('закачки' if np.isnan(i) else 'отбора') + ' — баланс не сравнивается'
        elif abs(ratio - 100.0) > tol:
            hint = f'отбор {ratio:.0f} % закачки, порог ±{tol:g} %'
        out.append({'cycle': int(r.cycle), 'group': r.group, 'injection': i, 'withdrawal': w,
                    'diff': w - i if not (np.isnan(i) or np.isnan(w)) else np.nan, 'ratio': ratio, 'hint': hint,
                    'total': r.group == 'Итого'})
    frame = pd.DataFrame(out)
    frame = frame.sort_values(['cycle', 'total', 'group']).drop(columns='total').reset_index(drop=True)
    return frame[cols]
