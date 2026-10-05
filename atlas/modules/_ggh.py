"""Общее для графика ГГХ на экране и в Word: параметры, цвета, шкалы, таблица скважины, подпись.

Оси и цвета — как в скрипте построения и в референсе отчёта: слева «Содержание, %» от 0 до 100 (11 меток),
справа «Газонасыщенность, см³/л» от 0 до круглого максимума, кратного 10; число меток справа равно левому.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

import pandas as pd

from app.core.config import ordered

# ключ колонки → (подпись, цвет, значок на экране); порядок — как в таблице под графиком
PARAMS = {
    'hc': ('Сумма УВ', '#0000ff', 'circle'), 'he': ('He', '#ff0000', 'square'), 'h2': ('H2', '#808080', 'triangle'),
    'n2': ('N2', '#00ff00', 'triangle'), 'o2': ('O2', '#800080', 'diamond'), 'co2': ('CO2', '#ff7f00', 'diamond'),
}
GAS = ('gas', 'Газонасыщенность', '#000000', 'circle')
GAS_COLUMN = 'Газонасыщенность, см³/л'
TICKS = 11            # меток на каждой оси Y: 0, 10, …, 100 слева
MIN_POINTS = 2        # меньше замеров — скважину пропускаем (как в скрипте)


def gas_axis(values: pd.Series) -> tuple[float, float]:
    """Границы правой оси: от 0 до максимума, округлённого вверх до кратного 10 (но не меньше 10)."""
    top = float(pd.to_numeric(values, errors='coerce').max()) if len(values) else float('nan')
    if not math.isfinite(top) or top <= 0:
        return 0.0, 10.0
    return 0.0, float(max(10, math.ceil(top / 10 - 1e-9) * 10))


def well_horizon(frame: pd.DataFrame) -> str:
    """Горизонт скважины: самое частое непустое написание в её строках."""
    names = [h for h in frame.horizon.astype(str).str.strip() if h and h.lower() != 'nan'] if 'horizon' in frame else []
    return Counter(names).most_common(1)[0][0] if names else ''


def horizon_genitive(name: str) -> str:
    """«Ряжский» → «ряжского», «Окско-Серпуховский» → «окско-серпуховского» (для «… по скважине № 162 ряжского горизонта»)."""
    text = name.strip().lower()
    return re.sub(r'(ый|ий|ой)$', 'ого', text)


def caption(number: int, well: str, horizon: str, section: str = 'В') -> str:
    tail = f' {horizon_genitive(horizon)} горизонта' if horizon else ''
    return f'Рисунок {section}.{number} – Результаты ГГХИ по скважине № {well}{tail}'


def rows_for(frame: pd.DataFrame) -> list[tuple[str, str, str, list[float | None]]]:
    """Строки таблицы под графиком: (ключ, подпись, цвет, значения по датам); пустые параметры не показываются."""
    out = []
    for key, (label, color, _) in PARAMS.items():
        values = pd.to_numeric(frame[key], errors='coerce') if key in frame else pd.Series(dtype=float)
        if values.notna().any():
            out.append((key, label, color, [None if pd.isna(v) else float(v) for v in values]))
    gas = pd.to_numeric(frame['gas'], errors='coerce') if 'gas' in frame else pd.Series(dtype=float)
    if gas.notna().any():
        out.append((GAS[0], GAS[1], GAS[2], [None if pd.isna(v) else float(v) for v in gas]))
    return out


def cell(key: str, value: float | None) -> str:
    """Подпись ячейки: газонасыщенность — целое, остальное — 4 знака, пусто — пусто."""
    if value is None:
        return ''
    return f'{int(round(value))}' if key == 'gas' else f'{value:.4f}'


def wells_of(frame: pd.DataFrame, horizons: list[str] | None = None, min_points: int = MIN_POINTS) -> list[str]:
    """Скважины с достаточным числом замеров; при ``horizons`` — только этих горизонтов (по самому частому написанию)."""
    out = []
    for well in ordered(frame.well.astype(str)):
        part = frame[frame.well.astype(str) == well]
        if len(part) < min_points:
            continue
        if horizons and well_horizon(part) not in set(horizons):
            continue
        out.append(well)
    return out
