"""Автоопределение сезонов отбора и закачки по накопленному расходу объекта (когда в таблице нет колонок «Сезон»/«Год»).

Сезон вида — непрерывный отрезок дней, когда накопленный объём этого вида растёт. Пока кривая идёт горизонтально
(расхода нет или он ничтожен) — это нейтральный период или сезон противоположного вида. Для каждого вида кривая
считается отдельно, поэтому рост закачки при плоском отборе (и наоборот) отделяет сезоны сам, без отдельного правила.
Чистая математика над датами и расходом: интерфейса и настроек здесь нет.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SMOOTH_DAYS = 7          # сглаживание суточного расхода объекта: единичные пропуски и нули не рвут сезон
TYPICAL_QUANTILE = 0.75  # «типичный» расход сезона — верхняя четверть положительных дней, а не максимум-выброс
DEFAULT_GAP_DAYS = 14
DEFAULT_SHARE = 10.0     # день активен, если сглаженный расход не меньше этой доли (%) типичного

KINDS = ('withdrawal', 'injection')


def detect_runs(dates: pd.Series, q: pd.Series, gap_days: int = DEFAULT_GAP_DAYS,
                share: float = DEFAULT_SHARE) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Сезоны одного вида: [(первый день, последний день)] по суммарному суточному расходу объекта."""
    q = pd.Series(np.asarray(q, dtype=float))
    dates = pd.Series(pd.to_datetime(np.asarray(dates)).normalize())
    keep = (q > 0).to_numpy()
    if not keep.any():
        return []
    total = q[keep].groupby(dates[keep].to_numpy()).sum()
    calendar = pd.date_range(total.index.min(), total.index.max())
    daily = total.reindex(calendar, fill_value=0.0)
    smooth = daily.rolling(SMOOTH_DAYS, center=True, min_periods=1).mean()
    positive = smooth[smooth > 0]
    active = (smooth >= positive.quantile(TYPICAL_QUANTILE) * share / 100.0).to_numpy()

    edges = np.flatnonzero(np.diff(np.concatenate(([0], active.astype(int), [0]))))
    runs = [[int(a), int(b) - 1] for a, b in zip(edges[::2], edges[1::2])]
    merged: list[list[int]] = []
    for run in runs:                    # короткая «полка» внутри сезона — не нейтральный период
        if merged and run[0] - merged[-1][1] - 1 < gap_days:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    values = daily.to_numpy()
    out = []
    for a, b in merged:
        if b - a + 1 < gap_days:        # слишком короткий всплеск — не сезон
            continue
        days = np.flatnonzero(values[a:b + 1] > 0)    # границы — по реальному расходу, а не по сглаживанию
        out.append((calendar[a + days[0]], calendar[a + days[-1]]))
    return out


def run_label(kind: str, start: pd.Timestamp) -> str:
    """Подпись сезона как в 5.8: отбор «2023-2024» (по началу сезона), закачка — год начала."""
    if kind == 'injection':
        return str(start.year)
    first = start.year if start.month >= 7 else start.year - 1
    return f'{first}-{first + 1}'


def labeler(df: pd.DataFrame, gap_days: int = DEFAULT_GAP_DAYS, share: float = DEFAULT_SHARE):
    """Функция ``(date, kind) -> подпись`` для строк таблицы эксплуатации; вне сезонов — «Вне сезона ГГГГ»."""
    runs = {}
    for kind in KINDS:
        part = df[df.kind.eq(kind)]
        found = detect_runs(part.date, part.q, gap_days, share) if len(part) else []
        runs[kind] = (np.array([a for a, _ in found], dtype='datetime64[ns]'),
                      np.array([b for _, b in found], dtype='datetime64[ns]'),
                      [run_label(kind, a) for a, _ in found])

    def label(date: pd.Series, kind: pd.Series) -> pd.Series:
        day = date.dt.normalize()
        out = 'Вне сезона ' + date.dt.year.astype(str)
        for k, (starts, ends, names) in runs.items():
            if not names:
                continue
            at = day.to_numpy().astype('datetime64[ns]')
            i = np.searchsorted(starts, at, side='right') - 1
            inside = (i >= 0) & (at <= ends[np.maximum(i, 0)]) & kind.eq(k).to_numpy()
            out = out.where(~inside, pd.Series(np.array(names, dtype=object)[np.maximum(i, 0)], index=out.index))
        return out

    return label
