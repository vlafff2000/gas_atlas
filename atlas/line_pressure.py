"""Давление в магистрали из «БД по учету газа» по суткам отбора: ряд на выбор и среднее за сезон.

Нужно, чтобы признак «расход на 1 % КРУ упал» не относили к скважине, когда он вызван работой системы сбора газа. Какой столбец считать
магистральным давлением, выбирает инженер; по умолчанию вход КЦ от ГИС-Касимов. Ряд — подсказка, решение за инженером."""
from __future__ import annotations

import pandas as pd

from atlas.engine.core.gas_db_import import PRESSURES

DEFAULT = 'p_gis_in'


def options(gas_db: pd.DataFrame | None) -> list[tuple[str, str]]:
    """Ряды давления, которые есть в загруженной БД: (ключ, подпись); пластовое среднее не магистраль и в список не входит."""
    if gas_db is None:
        return []
    return [(k, label) for k, (label, _) in PRESSURES.items() if k != 'p_res_mean' and k in gas_db.columns and gas_db[k].notna().any()]


def daily(gas_db: pd.DataFrame | None, key: str | None) -> pd.Series | None:
    """Суточное давление в сутки отбора, кгс/см² (индекс — дата); нет БД или ряда — None."""
    key = key or DEFAULT
    if gas_db is None or key not in gas_db.columns or 'kind' not in gas_db.columns:
        return None
    d = gas_db[gas_db['kind'].eq('withdrawal')]
    s = pd.Series(pd.to_numeric(d[key], errors='coerce').to_numpy(), index=pd.to_datetime(d['date']).dt.normalize()).dropna()
    return s[~s.index.duplicated(keep='last')].sort_index() if len(s) else None


def season_mean(series: pd.Series | None, start: pd.Timestamp | None, end: pd.Timestamp | None, min_days: int = 5) -> float | None:
    """Среднее давление за сезон; суток с замером меньше ``min_days`` — None (пропуск, не ноль)."""
    if series is None or start is None or end is None:
        return None
    part = series[(series.index >= start) & (series.index <= end)]
    return float(part.mean()) if len(part) >= min_days else None
