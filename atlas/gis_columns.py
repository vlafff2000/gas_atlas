"""Колонки ГИС рядом со схемой скважины: коллектор/неколлектор, насыщение пласта и заполнение ствола.

Ядро общее для всех мест, где рисуется схема (``atlas.passport_card.schematic``): здесь только данные и фигуры в метрах от стола.
Колонка коллектора одна на скважину (последний замер каждой пачки). Насыщение пласта и ствола зависят от даты исследования:
фигуры помечены ``date`` (ISO), экран и PDF показывают выбранную дату. Ничего не подставляется: на дату без записи колонка пустая.
Правило коллектора — подсказка с видимой причиной в подсказке фигуры (``name``); решение за инженером.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

X_COLLECTOR = (-6.0, -5.1)          # колонка «коллектор / неколлектор»
X_SATURATION = (-5.0, -3.5)         # колонка «насыщение пласта» (по Кг на дату)
X_BORE = ((-.95, -.58), (.58, .95))  # насыщение ствола: полосы внутри колонны по сторонам от НКТ
SHIFT = 2.9                          # на сколько условных единиц схема сдвигается вправо ради колонок (экран и PDF)

CLAY, WATER = 'глин', 'водонасыщ'
NOT_STUDIED = ('не исследован', 'не охвачен', 'не ясно', 'влияние конструкции')
GAS_LOW, GAS_HIGH = (188, 215, 240), (232, 137, 12)      # Кг 0 → светло-голубой, Кг 1 → насыщенный оранжевый
COLORS = {'collector': '#f4c542', 'non_collector': '#9ca3af', 'water': '#2b6cb0'}
FILL_COLORS = (('газ', '#f6c244', 'газ'), ('вод', '#60a5fa', 'вода'), ('раств', '#a78bfa', 'раствор'), ('нефт', '#92400e', 'нефть'))


def _num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _text(row: pd.Series, *columns: str) -> str:
    return ' '.join(str(row[c]) for c in columns if c in row.index and pd.notna(row[c])).lower()


def classify(row: pd.Series) -> tuple[str, str]:
    """(класс, причина): ``non_collector`` (глина), ``collector`` (водонасыщен или есть Кг) или ``unknown``. Глина проверяется первой."""
    text = _text(row, 'note', 'kg_text', 'status', 'status_text')
    kg = _num(row.get('kg'))
    if CLAY in text:
        return 'non_collector', 'в отчёте глина / заглинизирован'
    if WATER in text:
        return 'collector', 'в отчёте «водонасыщен»'
    if kg is not None:
        return 'collector', f'есть Кг {kg:.2f}'
    if any(w in text for w in NOT_STUDIED):
        return 'unknown', 'в отчёте: интервал не исследован или не ясен'
    return 'unknown', 'нет ни Кг, ни пометки'


def kg_color(kg: float) -> str:
    t = min(max(kg, 0.0), 1.0)
    return '#%02x%02x%02x' % tuple(round(a + (b - a) * t) for a, b in zip(GAS_LOW, GAS_HIGH))


def fill_kind(text: str) -> tuple[str, str]:
    low = (text or '').lower()
    return next(((c, name) for key, c, name in FILL_COLORS if key in low), ('#d1d5db', (text or 'прочее')))


def _iso(v: Any) -> str:
    return pd.Timestamp(v).strftime('%Y-%m-%d')


def prepare(well: str, intervals: pd.DataFrame | None, filling: pd.DataFrame | None) -> dict[str, Any] | None:
    """Данные колонок скважины: фигуры (метры от стола) и список дат её замеров. Нет ни интервалов, ни заполнения — None."""
    shapes: list[dict[str, Any]] = []
    dates: set[str] = set()
    if intervals is not None and len(intervals) and {'well', 'date', 'from_m', 'to_m'} <= set(intervals.columns):
        part = intervals[intervals['well'].astype(str) == str(well)].copy()
        part = part[part['date'].notna()]
        if len(part):
            part['_pack'] = part['pack'].astype(object).where(part['pack'].notna(), 'без пачки').astype(str) if 'pack' in part else 'без пачки'
            last = part.groupby('_pack')['date'].transform('max')
            for _, r in part[part['date'] == last].iterrows():
                a, b = _num(r['from_m']), _num(r['to_m'])
                kind, why = classify(r)
                if a is None or b is None or kind == 'unknown':
                    continue
                shapes.append({'t': 'rect', 'x0': X_COLLECTOR[0], 'x1': X_COLLECTOR[1], 'y0': min(a, b), 'y1': max(a, b),
                               'fill': COLORS[kind], 'pattern': '', 'name': f"{'Коллектор' if kind == 'collector' else 'Неколлектор'} {min(a, b):g}–{max(a, b):g} м: {why}",
                               'col': 'collector'})
            for _, r in part.iterrows():
                a, b = _num(r['from_m']), _num(r['to_m'])
                kind, _ = classify(r)
                dates.add(_iso(r['date']))
                if a is None or b is None or kind != 'collector':
                    continue
                kg = _num(r.get('kg'))
                water = WATER in _text(r, 'note', 'kg_text', 'status', 'status_text') and CLAY not in _text(r, 'note', 'kg_text', 'status', 'status_text')
                color = COLORS['water'] if (kg is None or water) else kg_color(kg)
                label = 'водонасыщен' if kg is None or water else f'Кг {kg:.2f}'
                shapes.append({'t': 'rect', 'x0': X_SATURATION[0], 'x1': X_SATURATION[1], 'y0': min(a, b), 'y1': max(a, b), 'fill': color,
                               'pattern': '', 'name': f'{min(a, b):g}–{max(a, b):g} м: {label}', 'col': 'saturation', 'date': _iso(r['date'])})
    if filling is not None and len(filling) and {'well', 'date', 'fill'} <= set(filling.columns):
        part = filling[(filling['well'].astype(str) == str(well)) & filling['date'].notna()]
        for _, r in part.iterrows():
            day = _iso(r['date'])
            dates.add(day)
            color, name = fill_kind(str(r.get('fill') or ''))
            a, b, level = _num(r.get('from_m')), _num(r.get('to_m')), _num(r.get('level_m'))
            if a is not None and b is not None:
                lo, hi = min(a, b), max(a, b)
                what = f'Ствол {lo:g}–{hi:g} м: {name}'
            elif level is not None:
                lo, hi = level, None              # жидкость ниже уровня; нижняя граница — забой/низ окна (задаёт схема)
                what = f'Ствол: {name}, уровень {level:g} м'
            else:
                continue
            for x0, x1 in X_BORE:
                shapes.append({'t': 'rect', 'x0': x0, 'x1': x1, 'y0': lo, 'y1': hi, 'fill': color, 'pattern': '', 'name': what,
                               'col': 'bore', 'date': day})
    if not shapes:
        return None
    return {'shapes': shapes, 'dates': sorted(dates)}
