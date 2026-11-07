"""События на оси времени для графиков: смена режима (начало отбора и закачки), ГДИ, ГИС, КРС и шаблонирование скважин.

Только выбор данных: сезоны уже размечены импортом 5.8 (колонка ``period``), даты ГДИ — набор ``gdi``.
КРС — таблица ``krs_works`` (в ней только год ремонта: отметка ставится на 1 июля этого года), ГИС — замеры «Базы ГИС»,
шаблонирование — строки замеров забоя с диаметром шаблона или методом «шаблон».
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from ..contract import Event

EVENT_LIMIT = 400        # больше отметок на графике не читается: оставляем равномерную выборку


def _within(date: pd.Timestamp, start, end) -> bool:
    return (start is None or date >= start) and (end is None or date <= end)


def regime_events(production: pd.DataFrame | None, start=None, end=None) -> list[Event]:
    """Начало каждого периода отбора и закачки по объекту (первая дата периода в данных) и пиковые окна (если заданы)."""
    if production is None or production.empty or 'period' not in production:
        return []
    first = production.groupby(['kind', 'period'], sort=False, observed=True).date.min()
    out = []
    for (kind, period), date in first.items():
        if pd.isna(date) or not _within(date, start, end):
            continue
        word = 'закачки' if kind == 'injection' else 'отбора'
        out.append(Event(date, f'Начало {word} · {period}', 'regime'))
    for first, last in production.attrs.get('_atlas_peaks', ()):
        if _within(first, start, end):
            out.append(Event(first, f'Пик · {first:%d.%m.%Y}–{last:%d.%m.%Y}' if last != first else f'Пик · {first:%d.%m.%Y}', 'peak'))
    return sorted(out, key=lambda e: e.x)[:EVENT_LIMIT]


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


def _pick(frame: pd.DataFrame | None, wells: Iterable[str], start, end) -> pd.DataFrame | None:
    if frame is None or frame.empty or 'well' not in frame or 'date' not in frame:
        return None
    d = frame[frame.well.astype(str).isin({str(w) for w in wells})]
    d = d[d.date.notna()]
    if start is not None:
        d = d[d.date >= start]
    if end is not None:
        d = d[d.date <= end]
    return d.sort_values('date')


def _thin(d: pd.DataFrame) -> pd.DataFrame:
    return d.iloc[::-(-len(d) // EVENT_LIMIT)] if len(d) > EVENT_LIMIT else d


def gis_events(observations: pd.DataFrame | None, wells: Iterable[str], start=None, end=None) -> list[Event]:
    """Замеры ГИС («База ГИС») выбранных скважин: одно событие на скважину и день."""
    d = _pick(observations, wells, start, end)
    if d is None:
        return []
    d = _thin(d.drop_duplicates(['well', 'date']))
    return [Event(r.date, f'ГИС · № {r.well}', 'gis', str(r.well)) for r in d.itertuples(index=False)]


def annotation_events(annotations: pd.DataFrame | None, wells: Iterable[str], start=None, end=None) -> list[Event]:
    """Пометки отчётов ГИС («Аннотации» базы ГИС: ремонт, остановка, ГВК не достигнут…): одно событие на скважину, дату и вид. Только подсказка."""
    d = _pick(annotations, wells, start, end)
    if d is None or 'kind' not in d:
        return []
    d = _thin(d.drop_duplicates(['well', 'date', 'kind']))
    return [Event(r.date, f'ГИС: {str(r.kind).strip()} · № {r.well}', 'gis', str(r.well)) for r in d.itertuples(index=False)]


def template_events(bottom: pd.DataFrame | None, wells: Iterable[str], start=None, end=None) -> list[Event]:
    """Шаблонирование: замеры забоя, где указан диаметр шаблона или метод содержит «шаблон»."""
    d = _pick(bottom, wells, start, end)
    if d is None:
        return []
    mark = pd.Series(False, index=d.index)
    if 'tool_diameter_mm' in d:
        mark |= pd.to_numeric(d['tool_diameter_mm'], errors='coerce').notna()
    if 'method' in d:
        mark |= d['method'].astype(str).str.contains('шаблон', case=False, na=False)
    d = _thin(d[mark].drop_duplicates(['well', 'date']))
    return [Event(r.date, f'Шаблонирование · № {r.well}', 'template', str(r.well)) for r in d.itertuples(index=False)]


def krs_events(works: pd.DataFrame | None, wells: Iterable[str], start=None, end=None) -> list[Event]:
    """Капитальные ремонты: в таблице только год, поэтому отметка стоит на 1 июля года ремонта (подпись говорит об этом)."""
    if works is None or works.empty or 'well' not in works or 'year' not in works:
        return []
    d = works[works.well.astype(str).isin({str(w) for w in wells})].copy()
    d['year'] = pd.to_numeric(d['year'], errors='coerce')
    d = d[d.year.notna()]
    d['date'] = pd.to_datetime(d.year.astype(int).astype(str) + '-07-01')
    d = _pick(d, wells, start, end)
    if d is None:
        return []
    out = []
    for r in _thin(d).itertuples(index=False):
        kind = str(getattr(r, 'work_type', '') or '').strip()
        kind = '' if kind in ('', 'nan') else f': {kind}'
        out.append(Event(r.date, f'КРС {int(r.year)}{kind} · № {r.well} (в данных только год)', 'repair', str(r.well)))
    return out


def krs_plan_events(plan: pd.DataFrame | None, wells: Iterable[str], start=None, end=None) -> list[Event]:
    """Ремонты «с даты по дату» из справки КРС (``krs_plan``: дата начала и окончания) — те же строки, что в таблице 7.1
    («В таблицу 7.1» = «Да», у инженера главнее ручное значение; текущий ремонт ТР в таблицу 7.1 не входит).
    Нет даты окончания — отметка начала; нет даты начала — события нет. Попадает в окно, если интервал пересекает его."""
    if plan is None or plan.empty or 'well' not in plan or 'start' not in plan:
        return []
    if 'in_table' in plan:
        plan = plan[plan['in_table'].eq('Да')]
    if 'kind' in plan:
        plan = plan[plan['kind'].ne('ТР')]
    d = plan[plan.well.astype(str).isin({str(w) for w in wells}) & plan['start'].notna()].copy()
    ends = pd.to_datetime(d['end'], errors='coerce') if 'end' in d else pd.Series(pd.NaT, index=d.index)
    last = ends.fillna(d['start'])
    keep = pd.Series(True, index=d.index)
    if start is not None:
        keep &= last >= start
    if end is not None:
        keep &= d['start'] <= end
    d, ends = d[keep].sort_values('start'), ends[keep]
    out = []
    for (index, r), stop in zip(d.iterrows(), ends.loc[d.index]):
        kind = str(r.get('kind', '') or '').strip()
        kind = '' if kind in ('', 'nan') else f' {kind}'
        state = str(r.get('status', '') or '').strip()
        state = '' if state in ('', 'nan') else f' ({state})'
        span = f'{r["start"]:%d.%m.%Y}–{stop:%d.%m.%Y}' if pd.notna(stop) else f'с {r["start"]:%d.%m.%Y}'
        out.append(Event(r['start'], f'КРС{kind}: {span}{state} · № {r["well"]}', 'repair', str(r['well']), stop if pd.notna(stop) else None))
    return out[:EVENT_LIMIT]


def on_cumulative(events: list[Event], data: pd.DataFrame) -> list[Event]:
    """Переводит события-даты в накопленный объём объекта на эту дату (ось X графика «Q / накопленный объем»).

    Накопленный объём считается по сезонам (``data.period``), поэтому событие ставится на кривую сезона, в чьи даты оно
    попало; вне показанных сезонов отметки нет. Накопленный объём по объекту, не по скважине, — как сама ось.
    """
    if not events or data.empty:
        return []
    seasons = []
    for _, g in data.drop_duplicates(['period', 'date']).groupby('period', sort=False):
        g = g.sort_values('date')
        seasons.append((g.date.iloc[0], g.date.iloc[-1], g.date.to_numpy(), g.cumulative.to_numpy()))
    out = []
    for e in events:
        date = pd.Timestamp(e.x)
        for first, last, dates, cumulative in seasons:
            if first <= date <= last:
                i = int(dates.searchsorted(date.to_datetime64()))
                out.append(Event(float(cumulative[min(i, len(cumulative) - 1)]), e.label, e.kind, e.well))
                break
    return sorted(out, key=lambda e: e.x)
