"""Ряды ЭЛПРО (КРУ, давление, температура) для суточного графика «Производительность скважин».

Каждый выбранный ряд — на своей правой оси (до ``MAX_RIGHT_AXES``), со своей единицей и цветом. Часы работы берутся из
БД расходов, поэтому у них нет ЭЛПРО-источника. Пропущенные сутки ЭЛПРО остаются разрывом линии: ноль не подставляется.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..contract import Axis

EXTRAS = (('hours', 'Часы работы'), ('cru', 'КРУ, %'), ('p', 'Давление, кгс/см²'), ('t', 'Температура, °C'),
          ('pres', 'Замеры пластового давления (Рпл из ГДИ)'))
COLOR = {'hours': '#149ba5', 'cru': '#169b62', 'p': '#9955cc', 't': '#ed8b23', 'pres': '#c2255c'}
MAX_RIGHT_AXES = 4
LABEL = {'hours': 'Часы работы', 'cru': 'КРУ', 'p': 'Давление ЭЛПРО', 't': 'Температура газа', 'pres': 'Рпл (замер ГДИ)'}


def picked_extras(keys) -> list[str]:
    """Выбранные ряды без повторов и неизвестных ключей; правых шкал не больше ``MAX_RIGHT_AXES``."""
    picked = [k for k in dict.fromkeys(keys or []) if k in LABEL]
    own = [k for k in picked if not (k == 'pres' and 'p' in picked)]       # замеры Рпл на оси давления ЭЛПРО своей шкалы не занимают
    keep = set(own[:MAX_RIGHT_AXES])
    return [k for k in picked if k in keep or (k == 'pres' and 'p' in keep)]


def extra_axis(key: str) -> Axis:
    """Правая ось Y для ряда: своя шкала, единица и цвет ряда."""
    if key == 'hours':
        return Axis('Часы работы', 'ч', from_zero=True, minimum=0, maximum=24, color=COLOR['hours'])
    if key == 'cru':
        return Axis('Степень открытия КРУ, %', '%', minimum=0, maximum=100, color=COLOR['cru'])
    if key == 'pres':
        return Axis('Пластовое давление (замеры)', 'кгс/см²', from_zero=True, color=COLOR['pres'])
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


def axis_names(extras: list[str]) -> dict[str, str]:
    """Правая ось каждого ряда (y2…). Замеры Рпл ложатся на ось давления ЭЛПРО, если она выбрана: так их видно вместе, в одном масштабе."""
    own = [k for k in extras if not (k == 'pres' and 'p' in extras)]
    names = {k: f'y{n}' for n, k in enumerate(own, start=2)}
    if 'pres' in extras and 'p' in extras:
        names['pres'] = names['p']
    return names


def pressure_points(gdi: pd.DataFrame, well: str, first, last) -> pd.DataFrame:
    """Замеры пластового давления скважины (Рпл из ГДИ) за период: дата и давление, по одному на день."""
    if gdi is None or gdi.empty or 'p_res' not in gdi:
        return pd.DataFrame(columns=['date', 'p_res'])
    d = gdi[gdi['well'].astype(str).eq(well)]
    d = d.assign(p_res=pd.to_numeric(d['p_res'], errors='coerce'), date=pd.to_datetime(d['date']).dt.normalize())
    d = d[d.p_res.notna() & d.date.between(first, last)]
    return d.groupby('date', as_index=False)['p_res'].mean()
