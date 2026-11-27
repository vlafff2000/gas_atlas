"""Давление ЭЛПРО скважины против группы, расходов и пластового давления: аномалии изменения давления на шлейфе.

Давление ЭЛПРО — давление на шлейфе по скважине до входа газа в коллектор (кгс/см², абс.). Здесь оно сопоставляется с тем же давлением по группе
(медиана по остальным скважинам группы), с суточным расходом скважины, группы и объекта и со средним пластовым по замерам. Пороги фиксированы и
описаны в подсказке; результат — подсказка с причиной, решает инженер. Пропуск суток ЭЛПРО — не ноль, в расчёт такие сутки не входят.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

WINDOW = 7              # сутки: давление и расход сглаживаются медианой за неделю
BASE = 28               # сутки до окна, с которыми сравнивается неделя
MIN_BASE = 14           # минимум суток с данными в базе сравнения
P_SHIFT = 2.0           # кгс/см²: сдвиг недельной медианы давления ЭЛПРО к базе, начиная с которого это аномалия
Q_SHIFT = 15.0          # %: сдвиг расхода, который показываем как значимый
JOIN_DAYS = 7           # соседние аномальные сутки с разрывом не больше этого — один эпизод
SAME = 0.5              # доля сдвига скважины, после которой группа/пластовое «двигаются вместе» с ней

HOW_TO_READ = (
    'Давление ЭЛПРО — на шлейфе скважины до входа газа в коллектор. Сравнивается медиана за 7 суток с медианой за 28 суток перед ней: '
    f'сдвиг от {P_SHIFT:g} кгс/см² — аномалия.',
    'Двигается вместе с группой — общий шлейф или режим коллектора, не скважина. Двигается вместе с пластовым — следует за падением пласта. '
    'Только у этой скважины — сопротивление в скважине или на её шлейфе (песок, забой, ПЗП, штуцер).',
    'Расходы скважины, группы и объекта даны как изменение медианы за 7 суток к базе, в процентах. Сутки без записи ЭЛПРО не считаются.')


def _med(x: pd.Series) -> pd.Series:
    return x.rolling(WINDOW, min_periods=max(3, WINDOW // 2)).median()


def _shift(x: pd.Series) -> pd.Series:
    """Недельная медиана минус медиана предыдущих 28 суток (база закончилась до начала недели)."""
    base = x.rolling(BASE, min_periods=MIN_BASE).median().shift(WINDOW)
    return _med(x) - base


def _rel(x: pd.Series) -> pd.Series:
    base = x.rolling(BASE, min_periods=MIN_BASE).median().shift(WINDOW)
    return ((_med(x) / base.where(base != 0) - 1) * 100).replace([np.inf, -np.inf], np.nan)


def series(elpro: pd.DataFrame | None, production: pd.DataFrame | None, pressure: pd.DataFrame | None, well: str, group_of: dict[str, str]) -> pd.DataFrame:
    """Суточные ряды скважины: p, grp_p (медиана давления ЭЛПРО по другим скважинам группы), q, grp_q, obj_q (тыс. м³/сут), p_res (замеры Рпл, только даты замеров)."""
    if elpro is None or elpro.empty or not {'p', 'well', 'date'} <= set(elpro.columns):
        return pd.DataFrame()
    e = elpro[elpro['kind'].eq('withdrawal')] if 'kind' in elpro else elpro
    e = e.assign(well=e['well'].astype(str), date=pd.to_datetime(e['date']).dt.normalize(), p=pd.to_numeric(e['p'], errors='coerce')).dropna(subset=['p'])
    e = e[e.p > 0]
    mine = e[e.well.eq(well)].groupby('date').p.mean()
    if mine.empty:
        return pd.DataFrame()
    group = group_of.get(well, '')
    peers = [w for w in e.well.unique() if w != well and group and group_of.get(w, '') == group]
    index = pd.date_range(mine.index.min(), mine.index.max())
    out = pd.DataFrame({'p': mine.reindex(index)})
    out['grp_p'] = e[e.well.isin(peers)].groupby(['date', 'well']).p.mean().groupby('date').median().reindex(index) if peers else np.nan
    for col in ('q', 'grp_q', 'obj_q'):
        out[col] = np.nan
    if production is not None and not production.empty and {'well', 'date', 'q'} <= set(production.columns):
        d = production[production['kind'].eq('withdrawal')] if 'kind' in production else production
        d = d.assign(well=d['well'].astype(str), date=pd.to_datetime(d['date']).dt.normalize())
        wide = d.pivot_table(index='date', columns='well', values='q', aggfunc='sum').reindex(index) / 1000
        has = wide.notna().any(axis=1)                      # день без записи в БД расходов — пропуск, не ноль
        if well in wide:
            out['q'] = wide[well].where(has)
        gw = [w for w in wide.columns if group and group_of.get(w, '') == group]
        out['grp_q'] = wide[gw].sum(axis=1, min_count=1).where(has) if gw else np.nan
        out['obj_q'] = wide.sum(axis=1, min_count=1).where(has)
    out['p_res'] = np.nan
    if pressure is not None and not pressure.empty:
        pr = pressure.dropna(subset=['pressure']).assign(date=lambda x: pd.to_datetime(x['date']).dt.normalize()).groupby('date').pressure.mean()
        out.loc[out.index.intersection(pr.index), 'p_res'] = pr.reindex(out.index.intersection(pr.index))
    return out


def _runs(mask: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    days = list(mask[mask].index)
    out: list[list[pd.Timestamp]] = []
    for d in days:
        if out and (d - out[-1][1]).days <= JOIN_DAYS:
            out[-1][1] = d
        else:
            out.append([d, d])
    return [(a, b) for a, b in out]


def _pres_change(df: pd.DataFrame, when: pd.Timestamp) -> float | None:
    """Изменение среднего Рпл: последний замер до ``when`` минус последний замер за 28 суток до него."""
    pr = df.p_res.dropna()
    now = pr[pr.index <= when]
    before = pr[pr.index <= when - pd.Timedelta(days=BASE)]
    return float(now.iloc[-1] - before.iloc[-1]) if len(now) and len(before) else None


def episodes(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Эпизоды аномалий давления ЭЛПРО скважины с сопутствующими изменениями группы, расходов и пластового давления и вероятной причиной."""
    if df is None or df.empty:
        return []
    dp, dg = _shift(df.p), _shift(df.grp_p)
    rel = {c: _rel(df[c]) for c in ('q', 'grp_q', 'obj_q')}
    out = []
    for start, end in _runs(dp.abs() >= P_SHIFT):
        peak = dp[start:end].abs().idxmax()
        shift = float(dp[peak])
        group = None if pd.isna(dg.get(peak)) else float(dg[peak])
        pres = _pres_change(df, peak)
        same = lambda v: v is not None and abs(v) >= SAME * abs(shift) and v * shift > 0
        if same(group):
            cause = 'вместе с группой: общий шлейф или режим коллектора'
        elif same(pres):
            cause = 'вместе с пластовым давлением'
        else:
            cause = 'только у этой скважины: сопротивление в скважине или на её шлейфе'
        row = {'start': start.strftime('%d.%m.%Y'), 'end': end.strftime('%d.%m.%Y'), 'peak': peak.strftime('%d.%m.%Y'), 'dp': shift, 'dp_group': group,
               'dq': None if pd.isna(rel['q'].get(peak)) else float(rel['q'][peak]), 'dq_group': None if pd.isna(rel['grp_q'].get(peak)) else float(rel['grp_q'][peak]),
               'dq_obj': None if pd.isna(rel['obj_q'].get(peak)) else float(rel['obj_q'][peak]), 'dp_res': pres, 'cause': cause,
               'direction': 'вырастало' if shift > 0 else 'упало'}
        dq = row['dq']
        row['note'] = (f'Давление ЭЛПРО {row["direction"]} на {abs(shift):.1f} кгс/см²' +
                       (f', расход скважины {dq:+.0f} %' if dq is not None and abs(dq) >= Q_SHIFT else '') + f'; {cause}.')
        out.append(row)
    return out
