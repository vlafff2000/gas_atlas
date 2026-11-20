"""Депрессия по сезонам отбора: обратный пересчёт по последнему надёжному ГДИ и сравнение с предельной депрессией типа забоя.

Депрессия здесь — просто Рпл − Рзаб, кгс/см² (не квадрат). По ГДИ Δp² = a·q + b·q², Рзаб² = Рпл² − Δp²; q — средний и максимальный суточный
расход сезона отбора (тыс. м³/сут), Рпл — среднее пластовое по замерной сетке («БД давлений по замерам», среднее по эксплуатационным скважинам)
на начало сезона. Пределы (по типу забоя) и тип скважины редактируются инженером: авто-тип — подсказка. Расчёт — оценка: вне диапазона
расходов ГДИ она грубая, об этом сказано в примечании строки.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DEFAULT_TYPES = [{'key': 'reaming', 'name': 'Расширка ПЗП', 'limit': 4.1},
                 {'key': 'perf', 'name': 'Перфорированная эксплуатационная колонна', 'limit': 2.8}]
NEAR = 0.9              # от предела: «близко»
PRESSURE_DAYS = 60      # замер Рпл не дальше этого от начала сезона
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


def pressure_at(pressure: pd.DataFrame | None, when: Any, days: int = PRESSURE_DAYS) -> tuple[float, str] | None:
    """Среднее пластовое на ближайшую к ``when`` дату замеров (столбцы ``date`` и ``pressure``), не дальше ``days`` суток."""
    if pressure is None or pressure.empty:
        return None
    p = pressure.dropna(subset=['pressure']).copy()
    p['date'] = pd.to_datetime(p['date'])
    gap = (p.date - pd.Timestamp(when)).abs()
    if p.empty or gap.min() > pd.Timedelta(days=days):
        return None
    row = p.loc[gap.idxmin()]
    return float(row['pressure']), pd.Timestamp(row['date']).strftime('%d.%m.%Y')


def depression(p_res: float, a: float, b: float, q: float) -> float | None:
    """Рпл − Рзаб по ГДИ; нет решения (Рзаб² ≤ 0) — None."""
    p_bh2 = p_res * p_res - (a * q + b * q * q)
    return float(p_res - np.sqrt(p_bh2)) if p_bh2 > 0 else None


def season_rows(seasons: list[dict[str, Any]], gdi: list[dict[str, Any]], pressure: pd.DataFrame | None, limit: float | None) -> list[dict[str, Any]]:
    """Сезоны отбора по порядку: расход, Рпл, депрессия на среднем и максимальном расходе, предел и статус."""
    study = next((g for g in sorted((g for g in gdi if g.get('reliable') and g.get('a') is not None and g.get('b') is not None),
                                    key=lambda g: pd.to_datetime(g['date'], dayfirst=True)) [::-1]), None)
    rows = []
    for s in sorted((s for s in seasons if s.get('kind') == 'withdrawal'), key=lambda s: str(s['period'])):
        try:
            start = pd.Timestamp(int(str(s['period'])[:4]), 11, 1)
        except ValueError:
            continue
        p = pressure_at(pressure, start)
        row = {'period': str(s['period']), 'q_mean': s.get('mean_rate'), 'q_max': s.get('max_rate'), 'p_res': p[0] if p else None, 'p_date': p[1] if p else '',
               'dep_mean': None, 'dep_max': None, 'limit': limit, 'status': 'нет данных', 'note': ''}
        if study is None:
            row['note'] = 'нет надёжного ГДИ для пересчёта'
        elif p is None:
            row['note'] = f'нет среднего пластового давления ближе {PRESSURE_DAYS} суток к началу сезона'
        else:
            for key, q in (('dep_mean', s.get('mean_rate')), ('dep_max', s.get('max_rate'))):
                row[key] = depression(p[0], study['a'], study['b'], q) if q else None
            row['note'] = f'по ГДИ {study["date"]}'
            if study.get('q_max') and (s.get('max_rate') or 0) > EXTRAPOLATION * study['q_max']:
                row['note'] += f': расход выше Qmax ГДИ ({study["q_max"]:g}), оценка грубая'
            top = row['dep_max']
            if top is not None and limit:
                row['status'] = 'превышен' if top > limit else 'близко' if top >= NEAR * limit else 'норма'
            elif top is not None:
                row['status'] = 'предел не задан'
        rows.append(row)
    return rows
