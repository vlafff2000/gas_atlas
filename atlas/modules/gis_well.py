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

from atlas import gis_columns, passport_card
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
                       packs: pd.DataFrame | None, with_gis: bool, geo: pd.DataFrame | None = None, perf_mode: str = 'abs',
                       date: pd.Timestamp | None = None, artificial: bool = True, break_m: float = passport_card.BREAK_M,
                       intervals: pd.DataFrame | None = None, filling: pd.DataFrame | None = None) -> Chart:
    """Схема забойной части скважины (конструкция из шаблона «Конструкция», отбитый забой и по желанию пачки ГИС).
    ``date`` — снимок конструкции; без неё самый поздний. Забой: у последнего снимка — последний замер, у прежнего — не позже его даты."""
    cons = construction[construction['well'].astype(str) == well] if construction is not None and len(construction) else pd.DataFrame()
    latest = bool(len(cons)) and (date is None or pd.Timestamp(date) >= cons['date'].max())
    if len(cons):
        date = cons['date'].max() if date is None else pd.Timestamp(date)
        cons = cons[cons['date'] == date]
    rows = cons.copy() if len(cons) else pd.DataFrame(columns=['element', 'top_m', 'bottom_m'])
    if not artificial and len(rows):
        rows = rows[~rows['element'].astype(str).str.contains('искусствен', case=False)]      # настройка «Искусственный забой на схеме»
    resource = bool(len(cons) and 'resource' in cons and cons['resource'].fillna('').astype(str).str.strip().str.lower().eq('да').any())       # bool, не numpy: уходит в JSON
    bottom_m = None
    if bottom is not None and len(bottom):
        b = bottom[bottom['well'].astype(str) == well].sort_values('date')
        if len(b) and len(cons) and not latest:
            b = b[b['date'] <= date]
        bottom_m = _num(b.iloc[-1]['bottom_m']) if len(b) else None
    gis_rows = []
    if with_gis and packs is not None and len(packs) and {'top_m', 'bottom_m'} <= set(packs.columns):
        part = packs[packs['well'].astype(str) == well].sort_values('date', kind='stable')
        last = part.groupby(part['pack'].astype(object).where(part['pack'].notna(), 'без пачки').astype(str), sort=False).tail(1)
        for _, r in last.iterrows():
            top, low = _num(r.get('top_m')), _num(r.get('bottom_m'))
            if top is not None and low is not None:
                gis_rows.append({'element': f"Пласт, пачка «{r['pack']}»", 'top_m': top, 'bottom_m': low})
    perf_note = ''
    if not len(rows) or not rows['element'].astype(str).str.contains('перфор|фильтр', case=False).any():
        perf, perf_note = perforation(well, packs, geo, _altitude(well, geo, packs), perf_mode)
        gis_rows += [{'element': 'Перфорация', 'top_m': p['top'], 'bottom_m': p['bottom']} for p in perf]
    if gis_rows:
        rows = pd.concat([rows, pd.DataFrame(gis_rows)], ignore_index=True)
    scheme = passport_card.schematic(rows, bottom_m, break_m, gis_columns.prepare(well, intervals, filling))
    stamp = f' на {date:%d.%m.%Y}' if len(cons) else ''
    chart = Chart(f'gis-construction-{well}-{date:%Y%m%d}' if len(cons) else f'gis-construction-{well}',
                  f'Скважина №{well}: конструкция у забоя{stamp}' + (' · «Ресурс»' if resource else ''), Axis('', ''), Axis('Глубина', 'м', inverse=True))
    chart.figure = Figure('construction', {'well': well, 'scheme': scheme, 'gis': bool(gis_rows), 'perf_note': perf_note,
                                           'date': f'{date:%d.%m.%Y}' if len(cons) else '', 'resource': resource})
    return chart


def _depth_row(row: pd.Series, alt: float | None) -> float | None:
    """Глубина ГВК: из таблицы; иначе альтитуда (из таблицы или «Положения и перфорации») минус ГВК а.о."""
    depth = _num(row.get('gvk_depth_m'))
    if depth is not None:
        return depth
    abs_, altitude = _num(row.get('gvk_abs_m')), _num(row.get('altitude_m'))
    altitude = altitude if altitude is not None else alt
    return None if abs_ is None or altitude is None else altitude - abs_


def _altitude(well: str, geo: pd.DataFrame | None, packs: pd.DataFrame | None = None) -> float | None:
    """Альтитуда скважины: «Положение и перфорация», иначе «База ГИС»."""
    if geo is not None and not geo.empty and 'altitude' in geo.columns:
        g = geo[geo['well'].astype(str) == well]
        value = _num(g.iloc[-1]['altitude']) if len(g) else None
        if value is not None:
            return value
    if packs is not None and len(packs) and 'altitude_m' in packs.columns:
        part = packs[packs['well'].astype(str) == well]
        return next((a for a in (_num(v) for v in part['altitude_m']) if a is not None), None)
    return None


PERF_MODES = ('abs', 'md')
PERF_SOURCES = {'abs': 'значения — а.о. (глубина ниже моря; без знака минус тоже а.о.), MD = альтитуда − а.о.',
                'md': 'значения — MD (метры от стола), без пересчёта'}
PERF_SOURCES = {k: v.rstrip('.') + '.' for k, v in PERF_SOURCES.items()}


def _to_md(value: float, alt: float | None, mode: str) -> float | None:
    """Глубина от стола из значения перфорации; None — а.о. есть, а альтитуды для пересчёта нет.
    Значение а.о. без знака минус (положительное) — та же глубина ниже моря: ему ставится минус, как в «Картах» и ГДМ."""
    if mode == 'md':
        return value
    return None if alt is None else alt + abs(value)


def perforation(well: str, packs: pd.DataFrame | None, geo: pd.DataFrame | None, alt: float | None,
                mode: str = 'abs') -> tuple[list[dict[str, float]], str]:
    """Перфорация в метрах от стола и пояснение (откуда и как прочитано).

    Значения «Базы ГИС» (perf_top_m/perf_bottom_m) и «Положения и перфорации» (perf_top/perf_bottom) заданы в а.о. (как в файле
    «Глубины_перфораций»), поэтому по умолчанию это а.о. (положительное число — а.о. без знака минус); если файл хранит MD,
    инженер выбирает «MD»."""
    mode = mode if mode in PERF_MODES else 'abs'
    found: tuple[float, float, str] | None = None
    if packs is not None and len(packs) and {'perf_top_m', 'perf_bottom_m'} <= set(packs.columns):
        part = packs[packs['well'].astype(str) == well]
        for _, r in part.iterrows():
            a, b = _num(r.get('perf_top_m')), _num(r.get('perf_bottom_m'))
            if a is not None and b is not None and a != b:
                found = (a, b, 'База ГИС')
                break
    if found is None and geo is not None and len(geo) and {'perf_top', 'perf_bottom'} <= set(geo.columns):
        g = geo[geo['well'].astype(str) == well]
        if len(g):
            a, b = _num(g.iloc[-1]['perf_top']), _num(g.iloc[-1]['perf_bottom'])
            if a is not None and b is not None and a != b:
                found = (a, b, 'Положение и перфорация')
    if found is None:
        return [], ''
    top, low = (_to_md(v, alt, mode) for v in found[:2])
    if top is None or low is None:
        return [], f'Перфорация скв. {well} ({found[2]}) в а.о., но альтитуды нет: пересчитать в MD нельзя, перфорация не показана.'
    top, low = sorted((top, low))
    return [{'top': top, 'bottom': low}], f'Перфорация скв. {well}: {found[2]}, {PERF_SOURCES[mode]}'


def _track_notes(annotations: pd.DataFrame | None, well: str, date) -> list[dict]:
    """Пометки отчётов ГИС на дату замера трека: вид, пачка и интервал (MD, если указан). Только подсказка."""
    if annotations is None or annotations.empty or pd.isna(date):
        return []
    d = annotations[(annotations['well'].astype(str) == well) & (annotations['date'] == date)]
    out = []
    for _, r in d.iterrows():
        pack = r.get('pack')
        out.append({'kind': str(r['kind']).strip(), 'pack': '' if pack is None or pd.isna(pack) else str(pack),
                    'top': _num(r.get('from_m')), 'bottom': _num(r.get('to_m'))})
    return out


def planshet_chart(well: str, intervals: pd.DataFrame, packs: pd.DataFrame | None, geo: pd.DataFrame | None,
                   labels: list[str], axis: str = 'md', perf_mode: str = 'abs', annotations: pd.DataFrame | None = None) -> Chart | None:
    """Планшет ГИС скважины по выбранным сезонам; None — по скважине нет замеров с интервалами."""
    cut = seasons_of.seasoned(intervals, keep=True)
    cut = cut[cut['season'].isin(labels)]
    last = _last_dates(cut, well)
    if last.empty:
        return None
    pk = _last_dates(seasons_of.seasoned(packs, keep=True), well) if packs is not None and len(packs) else pd.DataFrame()
    tracks, top, low = [], math.inf, -math.inf
    alt = _altitude(well, geo, pk if len(pk) else packs)
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
                       'bars': bars, 'packs': marks, 'notes': _track_notes(annotations, well, date)})
    perf, perf_note = perforation(well, pk, geo, alt, perf_mode)
    for p in perf:
        top, low = min(top, p['top']), max(low, p['bottom'])
    if not math.isfinite(top) or low <= top:
        return None
    pad = max((low - top) * .05, 2.0)
    chart = Chart(f'gis-planshet-{well}', f'Скважина №{well}: планшет ГИС', Axis('Кг', 'д.ед.'), Axis('Глубина', 'м', inverse=True))
    chart.figure = Figure('planshet', {'well': well, 'top': round(top - pad, 1), 'bottom': round(low + pad, 1), 'cutoff': KG_CUTOFF,
                                         'tracks': tracks, 'perf': perf, 'perf_note': perf_note, 'alt': alt, 'axis': 'abs' if axis == 'abs' and alt is not None else 'md'})
    return chart
