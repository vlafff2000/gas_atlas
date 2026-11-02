"""Общая выборка строк «режим» и «сезон» для разделов с сезонами: один раз на набор данных, а не по миллиону строк на каждый запрос."""
from __future__ import annotations

import pandas as pd

_MEMO: dict[tuple, tuple[pd.DataFrame, pd.DataFrame]] = {}
LIMIT = 64


def rows_of(df: pd.DataFrame, kind: str, period: str | None = None) -> pd.DataFrame:
    """``df`` для режима (и сезона). Это общая запомненная выборка: менять её нельзя (``assign`` и фильтры создают новую таблицу)."""
    key = (id(df), len(df), kind, period)
    hit = _MEMO.get(key)
    if hit is not None and hit[0] is df:
        return hit[1]
    mask = df.kind.eq(kind)
    if period is not None:
        mask = mask & df.period.eq(period)
    part = df[mask]
    if len(_MEMO) >= LIMIT:
        _MEMO.clear()
    _MEMO[key] = (df, part)
    return part
