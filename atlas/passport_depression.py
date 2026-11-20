"""Депрессия по сезонам отбора: обратный пересчёт по последнему надёжному ГДИ и сравнение с предельной депрессией типа забоя.

Депрессия здесь — просто Рпл − Рзаб, кгс/см² (не квадрат). По ГДИ Δp² = a·q + b·q², Рзаб² = Рпл² − Δp²; считается на КАЖДУЮ дату замера Рпл
в сезоне (замеры по опорной сетке 1–2 раза в неделю), если скважина в эту дату работала; q — суточный расход этой даты (тыс. м³/сут), Рпл — среднее
пластовое по замерной сетке («БД давлений по замерам», среднее по эксплуатационным скважинам). Пределы (по типу забоя) и тип скважины редактируются инженером: авто-тип — подсказка. Расчёт — оценка: вне диапазона
расходов ГДИ она грубая, об этом сказано в примечании строки.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DEFAULT_TYPES = [{'key': 'reaming', 'name': 'Расширка ПЗП', 'limit': 4.1},
                 {'key': 'perf', 'name': 'Перфорированная эксплуатационная колонна', 'limit': 2.8}]
NEAR = 0.9              # от предела: «близко»
EXTRAPOLATION = 1.2     # расход сезона больше Qmax ГДИ в столько раз — оценка вне диапазона исследования


def types_of(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Типы забоя и пределы из настроек проекта (``depression_limits``), иначе значения Egor: 4,1 и 2,8 кгс/см²."""
    raw = settings.get('depression_limits')
    out = []
    for t in raw if isinstance(raw, list) else []:
        try:
            out.append({'key': str(t['key']), 'name': str(t.get('name') or t['key']), 'limit': float(t['limit'])})
        except (KeyError, TypeError, ValueError):
            continue
    return out or [dict(t) for t in DEFAULT_TYPES]


def well_type(kinds: set[str], types: list[dict[str, Any]], manual: str | None) -> str | None:
    """Тип забоя: ручной выбор главнее; иначе есть расширка — 'reaming', есть перфорация — 'perf'; прочее — не определён (предела нет)."""
    keys = {t['key'] for t in types}
    if manual in keys:
        return manual
    auto = 'reaming' if 'reaming' in kinds else 'perf' if 'perf' in kinds else None
    return auto if auto in keys else None


def depression(p_res: float, a: float, b: float, q: float) -> float | None:
    """Рпл − Рзаб по ГДИ; нет решения (Рзаб² ≤ 0) — None."""
    p_bh2 = p_res * p_res - (a * q + b * q * q)
    return float(p_res - np.sqrt(p_bh2)) if p_bh2 > 0 else None


def season_points(period: str, pressure: pd.DataFrame, daily: dict[str, list], study: dict[str, Any], limit: float | None) -> list[dict[str, Any]]:
    """Депрессия на КАЖДУЮ дату замера Рпл в сезоне (замеры по опорной сетке 1–2 раза в неделю), только если скважина в эту дату работала.

    Расход берётся на ту же дату из суточных расходов; нет записи или ноль (простой) — дата пропускается, пропуск не ноль."""
    q_by_date = {d: v for d, v, per in zip(daily.get('date', []), daily.get('volume', []), daily.get('period', []))
                 if per == period and v is not None and not pd.isna(v) and v > 0}
    p = pressure.dropna(subset=['pressure']).assign(day=lambda x: pd.to_datetime(x['date']).dt.strftime('%Y-%m-%d'))
    out = []
    for day, p_res in p.groupby('day')['pressure'].mean().items():
        q = q_by_date.get(day)
        if q is None:
            continue
        dep = depression(float(p_res), study['a'], study['b'], q)
        if dep is not None:
            out.append({'date': pd.Timestamp(day).strftime('%d.%m.%Y'), 'day': day, 'q': float(q), 'p_res': float(p_res), 'dep': dep,
                        'over': bool(limit and dep > limit)})
    return out


def season_rows(seasons: list[dict[str, Any]], gdi: list[dict[str, Any]], pressure: pd.DataFrame | None, limit: float | None,
                daily: dict[str, list] | None = None) -> list[dict[str, Any]]:
    """Сезоны отбора по порядку: депрессия на даты замеров Рпл, число и доля дат с превышением предела, максимум и статус.

    Статус: «превышен» — есть даты выше предела; «близко» — максимум не ниже 90 % предела; «норма»; без предела — «предел не задан»."""
    study = next((g for g in sorted((g for g in gdi if g.get('reliable') and g.get('a') is not None and g.get('b') is not None),
                                    key=lambda g: pd.to_datetime(g['date'], dayfirst=True))[::-1]), None)
    rows = []
    for s in sorted((s for s in seasons if s.get('kind') == 'withdrawal'), key=lambda s: str(s['period'])):
        row = {'period': str(s['period']), 'q_mean': None, 'q_max': None, 'p_res': None, 'p_date': '', 'dep_mean': None, 'dep_max': None, 'limit': limit,
               'n': 0, 'n_over': 0, 'share_over': None, 'points': [], 'status': 'нет данных', 'note': ''}
        if study is None:
            row['note'] = 'нет надёжного ГДИ для пересчёта'
        elif pressure is None or pressure.empty:
            row['note'] = 'нет замеров пластового давления (БД давлений по замерам)'
        elif not daily or not daily.get('date'):
            row['note'] = 'нет суточных расходов'
        else:
            pts = season_points(str(s['period']), pressure, daily, study, limit)
            if not pts:
                row['note'] = 'нет дат, когда есть замер Рпл и скважина работала'
            else:
                top = max(pts, key=lambda x: x['dep'])
                row.update(points=pts, n=len(pts), n_over=sum(x['over'] for x in pts), q_mean=float(np.mean([x['q'] for x in pts])),
                           q_max=max(x['q'] for x in pts), p_res=top['p_res'], p_date=top['date'], dep_mean=float(np.mean([x['dep'] for x in pts])), dep_max=top['dep'])
                row['share_over'] = row['n_over'] / row['n']
                row['note'] = f'по ГДИ {study["date"]}, дат с замером Рпл при работе скважины: {row["n"]}'
                if study.get('q_max') and row['q_max'] > EXTRAPOLATION * study['q_max']:
                    row['note'] += f': есть расходы выше Qmax ГДИ ({study["q_max"]:g}), оценка грубая'
                if not limit:
                    row['status'] = 'предел не задан'
                else:
                    row['status'] = 'превышен' if row['n_over'] else 'близко' if row['dep_max'] >= NEAR * limit else 'норма'
        rows.append(row)
    return rows
