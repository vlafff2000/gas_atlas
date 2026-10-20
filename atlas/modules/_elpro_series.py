"""Ряды ЭЛПРО (КРУ, давление, температура) для суточного графика «Производительность скважин».

Каждый выбранный ряд — на своей правой оси (до ``MAX_RIGHT_AXES``), со своей единицей и цветом. Часы работы берутся из
БД расходов, поэтому у них нет ЭЛПРО-источника. Пропущенные сутки ЭЛПРО остаются разрывом линии: ноль не подставляется.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..contract import Axis

EXTRAS = (('hours', 'Часы работы'), ('cru', 'КРУ, %'), ('p', 'Давление, кгс/см²'), ('t', 'Температура, °C'))
COLOR = {'hours': '#149ba5', 'cru': '#169b62', 'p': '#9955cc', 't': '#ed8b23'}
MAX_RIGHT_AXES = 4
LABEL = {'hours': 'Часы работы', 'cru': 'КРУ', 'p': 'Давление ЭЛПРО', 't': 'Температура газа'}


def picked_extras(keys) -> list[str]:
    """Выбранные ряды без повторов и неизвестных ключей; правых шкал не больше ``MAX_RIGHT_AXES``."""
    return [k for k in dict.fromkeys(keys or []) if k in LABEL][:MAX_RIGHT_AXES]


def extra_axis(key: str) -> Axis:
    """Правая ось Y для ряда: своя шкала, единица и цвет ряда."""
    if key == 'hours':
        return Axis('Часы работы', 'ч', from_zero=True, minimum=0, maximum=24, color=COLOR['hours'])
    if key == 'cru':
        return Axis('Степень открытия КРУ, %', '%', minimum=0, maximum=100, color=COLOR['cru'])
    if key == 'p':
        return Axis('Давление газа', 'кгс/см²', from_zero=True, color=COLOR['p'])
    return Axis('Температура газа, °C', color=COLOR['t'])


def daily_values(elpro: pd.DataFrame, kind: str, well: str) -> pd.DataFrame:
    """ЭЛПРО скважины по суткам: p, t, cru (0–100). Сутки без записи в таблице нет — на графике это разрыв."""
    d = elpro[elpro['kind'].eq(kind) & elpro['well'].astype(str).eq(well)]
    frame = pd.DataFrame({'date': pd.to_datetime(d['date']).dt.normalize().to_numpy(), 'p': d['p'].to_numpy(),
                          't': d['t'].to_numpy(), 'cru': d['y'].clip(0, 100).to_numpy()})
    return frame.groupby('date').mean()


def hours_values(prod: pd.DataFrame, kind: str, well: str) -> pd.DataFrame:
    """Часы работы из БД расходов по суткам (исключённая точка без часов — разрыв)."""
    d = prod[prod['kind'].eq(kind) & prod['well'].astype(str).eq(well)]
    hours = d['hours'].to_numpy() if 'hours' in d else np.full(len(d), np.nan)
    frame = pd.DataFrame({'date': pd.to_datetime(d['date']).dt.normalize().to_numpy(), 'hours': hours})
    return frame.groupby('date')[['hours']].sum(min_count=1)
