"""Эффект ремонта «до/после»: расход и отдача скважины в сезонах отбора до и после капремонта.

Вход — «КРС: проведённые КР» (скважина, год, тип). В таблице только год, поэтому дата ремонта условная: 1-е число выбранного месяца
(по умолчанию июль — между сезонами отбора). «До» — последний сезон отбора, закончившийся до этой даты, «после» — первый, начавшийся после.
Изменение расхода показано вместе с медианой по группе за те же два сезона: так видно, что дал ремонт, а что — сезон. Отдача по ГДИ —
расход при общем ΔP² (``gdi_trend.histories``) последнего надёжного исследования до и первого после. Математика ГДИ не пересчитывается.
Вывод об эффекте делает инженер: программа не называет ремонт удачным или нет.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contract import Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Stat, Table
from ..domain import DatasetKind
from ._production import NEUTRAL_PREFIXES
from .gdi import well_key
from .gdi_trend import histories

GDI, PRODUCTION, WORKS_K = DatasetKind.GDI, DatasetKind.PRODUCTION, DatasetKind.KRS_WORKS
NOTE = ('Дата ремонта в данных — только год, поэтому берётся условная дата (месяц задаётся выше). «До» — последний сезон отбора, закончившийся '
        'до неё, «после» — первый, начавшийся после. Изменение расхода сравнивайте с медианой по группе за те же сезоны. Сезон без данных '
        'не считается нулевым, а ГДИ показано только если есть надёжные исследования по обе стороны. Вывод об эффекте — за инженером.')


def withdrawal_seasons(prod: pd.DataFrame) -> pd.DataFrame:
    """Сезоны отбора: period, start, end — по датам с расходом."""
    cols = ['period', 'start', 'end']
    if prod is None or prod.empty or 'q' not in prod:
        return pd.DataFrame(columns=cols)
    col = 'period' if 'period' in prod else 'season'
    df = prod[prod.kind.eq('withdrawal') & prod.q.gt(0) & prod[col].notna()]
    df = df[df[col].astype(str).ne('') & ~df[col].astype(str).str.startswith(NEUTRAL_PREFIXES)]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = df.groupby(col).date.agg(start='min', end='max').reset_index().rename(columns={col: 'period'})
    return out.sort_values('start').reset_index(drop=True)


def well_means(prod: pd.DataFrame) -> pd.DataFrame:
    """Средний расход (тыс. м³/сут в днях с расходом) и максимальный суточный по скважине и сезону отбора."""
    col = 'period' if 'period' in prod else 'season'
    df = prod[prod.kind.eq('withdrawal') & prod.q.gt(0) & prod[col].notna()].assign(well=lambda d: d.well.astype(str))
    g = df.groupby(['well', col]).q.agg(mean='mean', peak='max') / 1e3
    g.index.names = ['well', 'period']
    return g


def pick_periods(seasons: pd.DataFrame, year: int, month: int, count: int) -> tuple[list[str], list[str]]:
    cut = pd.Timestamp(year=int(year), month=int(month), day=1)
    before = seasons[seasons.end.lt(cut)].period.tolist()[-count:]
    after = seasons[seasons.start.ge(cut)].period.tolist()[:count]
    return before, after


def _mean(means: pd.DataFrame, well: str, periods: list[str], col: str) -> float:
    vals = [means[col].get((well, p), np.nan) for p in periods]
    vals = [v for v in vals if pd.notna(v)]
    return float(np.mean(vals)) if vals else np.nan


def effects(data: Data, params: dict[str, Any]) -> pd.DataFrame:
    works = data[WORKS_K].dropna(subset=['year']).assign(well=lambda d: d.well.astype(str), year=lambda d: d.year.astype(int))
    prod = data[PRODUCTION]
    seasons, means = withdrawal_seasons(prod), well_means(prod)
    group_of = {w: (data.mapping.get(w, {}) or {}).get('group', '') for w in set(works.well) | set(means.index.get_level_values(0))}
    hist = histories(data[GDI], params['threshold'], []) if GDI in data and not data[GDI].empty else pd.DataFrame()
    rows = []
    for _, w in works.iterrows():
        before, after = pick_periods(seasons, w.year, params['month'], int(params['seasons']))
        row = dict(well=w.well, group=group_of.get(w.well, ''), year=w.year, work_type=w.work_type, before=', '.join(before),
                   after=', '.join(after))
        for col, name in (('mean', 'q'), ('peak', 'peak')):
            b, a = _mean(means, w.well, before, col), _mean(means, w.well, after, col)
            row[f'{name}_before'], row[f'{name}_after'] = b, a
            row[f'{name}_change'] = (a - b) / b * 100 if b and np.isfinite(b) and np.isfinite(a) else np.nan
        peers = [x for x in set(means.index.get_level_values(0)) if x != w.well and group_of.get(x, '') == row['group']]
        ch = []
        for x in peers:
            b, a = _mean(means, x, before, 'mean'), _mean(means, x, after, 'mean')
            if np.isfinite(b) and np.isfinite(a) and b:
                ch.append((a - b) / b * 100)
        row['group_change'] = float(np.median(ch)) if ch and before and after else np.nan
        row['net_change'] = row['q_change'] - row['group_change'] if np.isfinite(row['q_change']) and np.isfinite(row['group_change']) else np.nan
        row['gdi_before'], row['gdi_after'], row['gdi_change'] = _gdi_effect(hist, w.well, w.year, params['month'])
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out['_k'] = out.well.map(well_key)
    return out.sort_values(['_k', 'year'], kind='stable').drop(columns='_k').reset_index(drop=True)


def _gdi_effect(hist: pd.DataFrame, well: str, year: int, month: int) -> tuple[float, float, float]:
    nan = (np.nan, np.nan, np.nan)
    if hist.empty:
        return nan
    cut = pd.Timestamp(year=int(year), month=int(month), day=1)
    ok = hist[(hist.well == well) & hist.reliable & hist.q_reference.notna() & hist.date.notna()]
    b, a = ok[ok.date.lt(cut)].sort_values('date'), ok[ok.date.ge(cut)].sort_values('date')
    if b.empty or a.empty:
        return nan
    qb, qa = float(b.iloc[-1].q_reference), float(a.iloc[0].q_reference)
    return qb, qa, (qa - qb) / qb * 100 if qb else np.nan


class RepairEffectModule(Module):
    spec = ModuleSpec(
        id='repair_effect',
        title='Эффект ремонта до и после',
        group='Авторский надзор',
        description='Расход и отдача скважины в сезонах отбора до и после капремонта, рядом с изменением по группе; вывод за инженером.',
        needs=(WORKS_K, PRODUCTION),
        optional=(GDI,),
        order=119,
        params=(
            Param('month', 'Условный месяц ремонта', 'choice', default=7, section='Выбор данных',
                  options=tuple(Option(m, n) for m, n in ((3, 'март'), (5, 'май'), (6, 'июнь'), (7, 'июль'), (8, 'август'), (9, 'сентябрь'))),
                  help='В данных КРС только год. Сезоны, закончившиеся до 1-го числа этого месяца, считаются «до», начавшиеся позже — «после».'),
            Param('seasons', 'Сезонов до и после', 'choice', default=1, section='Выбор данных',
                  options=(Option(1, '1'), Option(2, '2'), Option(3, '3')),
                  help='Сколько сезонов отбора усреднять с каждой стороны. Больше сезонов — спокойнее оценка, но чаще не хватает данных.'),
            Param('threshold', 'Порог R²', 'number', default=0.95, minimum=0.0, maximum=1.0, step=0.01, setting='r2_threshold',
                  section='Выбор данных', help='Общая настройка проекта: исследования с R² ниже порога не считаются надёжными.'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        if WORKS_K not in data or data[WORKS_K].empty:
            result.notes.append(Note('Данных КРС в проекте нет: импортируйте книгу КРС_для_Атласа.xlsx во вкладке «Импорт».'))
            return result
        if PRODUCTION not in data or data[PRODUCTION].empty:
            result.notes.append(Note('Нет данных расходов: эффект ремонта считать не из чего.'))
            return result
        table = effects(data, params)
        have = table.q_change.notna()
        result.summary = [Stat('Ремонтов', str(len(table))), Stat('С данными до и после', str(int(have.sum())),
                                                                    'Есть сезоны отбора с обеих сторон'),
                          Stat('Без данных', str(int((~have).sum())), 'Ремонт на краю данных или сезон не загружен'),
                          Stat('С ГДИ до и после', str(int(table.gdi_change.notna().sum())))]
        result.notes.append(Note(NOTE))
        result.tables.append(Table('repair-effect', 'Ремонты: расход и отдача до и после', table, [
            Column('well', 'Скважина'), Column('group', 'Группа'), Column('year', 'Год КР', kind='number', decimals=0),
            Column('work_type', 'Тип ремонта'), Column('before', 'Сезоны до'), Column('after', 'Сезоны после'),
            Column('q_before', 'Расход до', 'тыс. м³/сут', 1, 'number'), Column('q_after', 'Расход после', 'тыс. м³/сут', 1, 'number'),
            Column('q_change', 'Изменение', '%', 0, 'number'), Column('group_change', 'Медиана группы', '%', 0, 'number'),
            Column('net_change', 'Сверх группы', 'п.п.', 0, 'number'),
            Column('peak_before', 'Максимум до', 'тыс. м³/сут', 1, 'number'), Column('peak_after', 'Максимум после', 'тыс. м³/сут', 1, 'number'),
            Column('peak_change', 'Изменение максимума', '%', 0, 'number'),
            Column('gdi_before', 'Q при общем ΔP² до', 'тыс. м³/сут', 1, 'number'), Column('gdi_after', 'Q при общем ΔP² после', 'тыс. м³/сут', 1, 'number'),
            Column('gdi_change', 'Изменение отдачи по ГДИ', '%', 0, 'number')],
            note='«Сверх группы» = изменение расхода скважины − медиана изменения по группе за те же сезоны.'))
        return result
