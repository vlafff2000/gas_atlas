"""События на оси времени для графиков: смена режима (начало отбора и закачки) и ГДИ скважин.

Только выбор данных: сезоны уже размечены импортом 5.8 (колонка ``period``), даты ГДИ — набор ``gdi``.
Данных о ремонтах в проектах пока нет; событие ``kind='repair'`` появится, когда их начнут загружать.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from ..contract import Event

EVENT_LIMIT = 400        # больше отметок на графике не читается: оставляем равномерную выборку


def _within(date: pd.Timestamp, start, end) -> bool:
    return (start is None or date >= start) and (end is None or date <= end)


def regime_events(production: pd.DataFrame | None, start=None, end=None) -> list[Event]:
    """Начало каждого периода отбора и закачки по объекту (первая дата периода в данных)."""
    if production is None or production.empty or 'period' not in production:
        return []
    first = production.groupby(['kind', 'period'], sort=False, observed=True).date.min()
    out = []
    for (kind, period), date in first.items():
        if pd.isna(date) or not _within(date, start, end):
            continue
        word = 'закачки' if kind == 'injection' else 'отбора'
        out.append(Event(date, f'Начало {word} · {period}', 'regime'))
    return sorted(out, key=lambda e: e.x)


def gdi_events(gdi: pd.DataFrame | None, wells: Iterable[str], start=None, end=None) -> list[Event]:
    """Даты ГДИ выбранных скважин: одно событие на скважину и день."""
    if gdi is None or gdi.empty:
        return []
    chosen = {str(w) for w in wells}
    d = gdi[gdi.well.astype(str).isin(chosen)]
    if start is not None:
        d = d[d.date >= start]
    if end is not None:
        d = d[d.date <= end]
    cols = ['well', 'date'] + (['method'] if 'method' in d else [])
    d = d[cols].drop_duplicates(['well', 'date']).sort_values('date')
    if len(d) > EVENT_LIMIT:
        d = d.iloc[::-(-len(d) // EVENT_LIMIT)]
    out = []
    for row in d.itertuples(index=False):
        method = getattr(row, 'method', '')
        method = '' if pd.isna(method) or not str(method).strip() else f' ({method})'
        out.append(Event(row.date, f'ГДИ{method} · № {row.well}', 'gdi', str(row.well)))
    return out
