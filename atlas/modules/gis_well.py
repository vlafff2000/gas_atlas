"""ГИС и ГВК: схема скважины и планшет ГИС по глубине (рисует общий компонент WellFigure, как паспорт скважины).

Схема забоя — та же, что в паспорте скважины (``atlas.passport_card.schematic`` и ``shapes``), поверх неё по желанию пачки ГИС.
Планшет — на выбранные сезоны по одному треку: полосы интервалов с Кг (серый — Кг ниже порога газонасыщения), линия ГВК
и подпись hг эф по пачке, слева полоса перфорации. Глубины — метры от стола, как в таблицах ГИС; ГВК берётся из таблицы
(глубина) или считается: альтитуда − ГВК а.о.
В сезоне берётся последний замер скважины. Это подсказка: нужный замер выбирается сезонами вручную.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from atlas import passport_card
from ..contract import Axis, Chart, Figure
from . import gis_an_tables as seasons_of

KG_CUTOFF = 0.25      # порог газонасыщения Кг, выше которого интервал считается газонасыщенным (как hэф в «Базе ГИС»)
MAX_TRACKS = 4        # сезонов на планшете без ручного выбора: самые поздние


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _last_dates(frame: pd.DataFrame, well: str) -> pd.DataFrame:
    """Строки последнего замера скважины в каждом сезоне (столбец season уже «осень 2025»)."""
    part = frame[frame['well'] == well]
    if part.empty:
        return part
    last = part.groupby('season')['date'].transform('max')
    return part[part['date'] == last]


def construction_chart(well: str, construction: pd.DataFrame | None, bottom: pd.DataFrame | None,
                       packs: pd.DataFrame | None, with_gis: bool) -> Chart:
    """Схема забойной части скважины (конструкция из шаблона «Конструкция», отбитый забой и по желанию пачки ГИС)."""
    cons = construction[construction['well'].astype(str) == well] if construction is not None and len(construction) else pd.DataFrame()
    rows = cons.copy() if len(cons) else pd.DataFrame(columns=['element', 'top_m', 'bottom_m'])
    bottom_m = None
    if bottom is not None and len(bottom):
        b = bottom[bottom['well'].astype(str) == well].sort_values('date')
        bottom_m = _num(b.iloc[-1]['bottom_m']) if len(b) else None
    gis_rows = []
    if with_gis and packs is not None and len(packs) and {'top_m', 'bottom_m'} <= set(packs.columns):
        part = packs[packs['well'].astype(str) == well].sort_values('date', kind='stable')
        last = part.groupby(part['pack'].astype(object).where(part['pack'].notna(), 'без пачки').astype(str), sort=False).tail(1)
        for _, r in last.iterrows():
            top, low = _num(r.get('top_m')), _num(r.get('bottom_m'))
            if top is not None and low is not None:
                gis_rows.append({'element': f"Пласт, пачка «{r['pack']}»", 'top_m': top, 'bottom_m': low})
    if gis_rows:
        rows = pd.concat([rows, pd.DataFrame(gis_rows)], ignore_index=True)
    scheme = passport_card.schematic(rows, bottom_m)
    chart = Chart(f'gis-construction-{well}', f'Скважина №{well}: конструкция у забоя', Axis('', ''), Axis('Глубина', 'м', inverse=True))
    chart.figure = Figure('construction', {'well': well, 'scheme': scheme, 'gis': bool(gis_rows)})
    return chart


def _depth_row(row: pd.Series, alt: float | None) -> float | None:
    """Глубина ГВК: из таблицы; иначе альтитуда (из таблицы или «Положения и перфорации») минус ГВК а.о."""
    depth = _num(row.get('gvk_depth_m'))
    if depth is not None:
        return depth
    abs_, altitude = _num(row.get('gvk_abs_m')), _num(row.get('altitude_m'))
    altitude = altitude if altitude is not None else alt
    return None if abs_ is None or altitude is None else altitude - abs_


def _altitude(well: str, geo: pd.DataFrame | None) -> float | None:
    if geo is None or geo.empty or 'altitude' not in geo.columns:
        return None
    g = geo[geo['well'].astype(str) == well]
    return _num(g.iloc[-1]['altitude']) if len(g) else None


def _perforation(well: str, packs: pd.DataFrame, geo: pd.DataFrame | None) -> list[dict[str, float]]:
    """Перфорация в метрах от стола: из «Базы ГИС» (глубины), иначе из «Положения и перфорации» (отметки а.о. → альтитуда − отметка)."""
    if len(packs) and {'perf_top_m', 'perf_bottom_m'} <= set(packs.columns):
        for _, r in packs.iterrows():
            a, b = _num(r.get('perf_top_m')), _num(r.get('perf_bottom_m'))
            if a is not None and b is not None and b > a:
                return [{'top': a, 'bottom': b}]
    if geo is not None and len(geo) and {'perf_top', 'perf_bottom', 'altitude'} <= set(geo.columns):
        g = geo[geo['well'].astype(str) == well]
        if len(g):
            alt, a, b = (_num(g.iloc[-1][c]) for c in ('altitude', 'perf_top', 'perf_bottom'))
            if alt is not None and a is not None and b is not None:
                d1, d2 = sorted((alt - a, alt - b))
                return [{'top': d1, 'bottom': d2}]
    return []


def planshet_chart(well: str, intervals: pd.DataFrame, packs: pd.DataFrame | None, geo: pd.DataFrame | None,
                   labels: list[str]) -> Chart | None:
    """Планшет ГИС скважины по выбранным сезонам; None — по скважине нет замеров с интервалами."""
    cut = seasons_of.seasoned(intervals, keep=True)
    cut = cut[cut['season'].isin(labels)]
    last = _last_dates(cut, well)
    if last.empty:
        return None
    pk = _last_dates(seasons_of.seasoned(packs, keep=True), well) if packs is not None and len(packs) else pd.DataFrame()
    tracks, top, low = [], math.inf, -math.inf
    alt = _altitude(well, geo)
    for label in seasons_of.order(last['season'].unique()):
        part = last[last['season'] == label].sort_values('from_m')
        bars = []
        for _, r in part.iterrows():
            a, b, kg = _num(r.get('from_m')), _num(r.get('to_m')), _num(r.get('kg'))
            if a is None or b is None:
                continue
            bars.append({'top': a, 'bottom': b, 'kg': kg, 'pack': str(r['pack']), 'gas': kg is not None and kg > KG_CUTOFF})
            top, low = min(top, a), max(low, b)
        marks = []
        if len(pk):
            for _, r in pk[pk['season'] == label].iterrows():
                depth = _depth_row(r, alt)
                marks.append({'pack': str(r['pack']), 'gvk': depth, 'gvk_abs': _num(r.get('gvk_abs_m')), 'h_eff': _num(r.get('h_eff_m')),
                              'kg_avg': _num(r.get('kg_avg'))})
                if depth is not None:
                    top, low = min(top, depth), max(low, depth)
        date = part['date'].max()
        tracks.append({'title': seasons_of.name_of(label), 'date': date.strftime('%d.%m.%Y') if pd.notna(date) else '',
                       'bars': bars, 'packs': marks})
    perf = _perforation(well, pk, geo)
    for p in perf:
        top, low = min(top, p['top']), max(low, p['bottom'])
    if not math.isfinite(top) or low <= top:
        return None
    pad = max((low - top) * .05, 2.0)
    chart = Chart(f'gis-planshet-{well}', f'Скважина №{well}: планшет ГИС', Axis('Кг', 'д.ед.'), Axis('Глубина', 'м', inverse=True))
    chart.figure = Figure('planshet', {'well': well, 'top': round(top - pad, 1), 'bottom': round(low + pad, 1), 'cutoff': KG_CUTOFF,
                                         'tracks': tracks, 'perf': perf})
    return chart
