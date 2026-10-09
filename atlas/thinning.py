"""Прореживание линий графика при выдаче в браузер — без потери того, что видно и на что можно нажать.

Принципы (docs/ATLAS6.md, «Большие данные»):

* Метод М4: на каждую корзину по порядку точек оставляются первая, последняя, минимальная, максимальная точки
  и первый пропуск (разрыв линии, исключённая точка). Линия, нарисованная по такой выборке, совпадает с линией по
  всем точкам при том числе корзин, что умещается в ширину графика; пики и провалы не теряются.
* Прореживается только то, что уходит на экран. Результат модуля (``Result``) всегда содержит все точки: из него
  делаются выгрузки PNG / SVG / PDF, таблицы CSV / XLSX и щелчки «исключить точку».
* При увеличении интерфейс запрашивает видимое окно (``window``): внутри окна точек обычно мало и они отдаются все.
* Каждая прореженная серия помечена (``total`` > число отданных точек), интерфейс показывает «показано N из M».
* Облака точек (``kind='points'``), столбцы и ящики не прореживаются: у них нет порядка по оси X.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Sequence

import numpy as np
import pandas as pd

CHART_POINTS = 30000     # бюджет точек на график (по всем прореживаемым линиям)
SERIES_CAP = 4000        # больше точек на одну линию экран не различит; ниже порога сборки LTTB в ECharts (5000)
SERIES_FLOOR = 40        # даже у сотни кривых каждая сохраняет форму
RAW_LIMIT = 200_000      # в режимах «Замеры» и «Исключать точки» окно отдаётся целиком, пока точек не больше этого

_FULL = contextvars.ContextVar('atlas_full_resolution', default=False)


@contextmanager
def full_resolution():
    """Модули строят серии без собственного прореживания (выгрузка графика, окно увеличения)."""
    token = _FULL.set(True)
    try:
        yield
    finally:
        _FULL.reset(token)


def is_full() -> bool:
    return _FULL.get()


def screen_decimate(frame: pd.DataFrame, column: str, limit: int = 5000) -> pd.DataFrame:
    """Прореживание 5.8 (``charts.decimate``) для экрана; в ``full_resolution`` — все точки."""
    from atlas.engine.modules.charts import decimate
    return frame if is_full() else decimate(frame, column, limit)


# ---------- числовая ось ----------

def axis_numbers(x: Any) -> np.ndarray | None:
    """Значения X как числа (даты — миллисекунды с 1970 г., как у интерфейса); None, если порядка нет."""
    values = x.to_numpy() if isinstance(x, (pd.Series, pd.Index)) else np.asarray(x)
    if values.dtype.kind == 'M':
        return values.astype('datetime64[ms]').astype('int64').astype(float)
    if values.dtype.kind in 'iuf':
        return values.astype(float)
    if values.dtype == object and len(values):
        try:
            return pd.to_datetime(pd.Series(values)).to_numpy().astype('datetime64[ms]').astype('int64').astype(float)
        except (ValueError, TypeError):
            try:
                return values.astype(float)
            except (ValueError, TypeError):
                return None
    return None


def ordered(xs: np.ndarray) -> bool:
    return len(xs) < 2 or bool(np.all(np.diff(xs[np.isfinite(xs)]) >= 0)) and bool(np.isfinite(xs).all())


def thinnable(series: Any, xs: np.ndarray | None) -> bool:
    """Линия с упорядоченной осью X: только такую можно прореживать, не искажая рисунок."""
    return series.kind == 'line' and xs is not None and ordered(xs)


# ---------- М4 ----------

def m4_indices(y: Sequence[float], limit: int) -> np.ndarray:
    """Индексы точек, оставляемые при лимите ``limit`` (отсортированы). ``len(result) <= max(limit, 5)``."""
    values = np.asarray(y, dtype=float)
    n = len(values)
    if n <= limit:
        return np.arange(n)
    buckets = max(1, (max(limit, 5) - 2) // 5)
    keep = {0, n - 1}
    finite = np.isfinite(values)
    for chunk in np.array_split(np.arange(n), buckets):
        if not len(chunk):
            continue
        ok = chunk[finite[chunk]]
        if len(ok):
            part = values[ok]
            keep.update((int(ok[0]), int(ok[-1]), int(ok[np.argmin(part)]), int(ok[np.argmax(part)])))
        gap = chunk[~finite[chunk]]
        if len(gap):
            keep.add(int(gap[0]))
    return np.fromiter(sorted(keep), dtype=int)


def shares(sizes: Sequence[int], budget: int, floor: int = SERIES_FLOOR, cap: int = SERIES_CAP) -> int:
    """Наибольший лимит на линию L, при котором сумма min(размер, L) укладывается в бюджет (неиспользованное — длинным линиям)."""
    sizes = sorted(int(s) for s in sizes)
    if not sizes or sum(sizes) <= budget:
        return cap
    lo, hi = floor, cap
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if sum(min(s, mid) for s in sizes) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return lo


def plan(chart: Any, budget: int = CHART_POINTS) -> dict[int, np.ndarray]:
    """Для каждой прореживаемой серии графика — числа оси X (индекс серии → X). Остальные серии не трогаем.

    Линии одной стопки (``Series.stack``) складываются по номеру точки, поэтому прореживаются только вместе и с
    общими индексами; стопка с разными X у серий не прореживается вовсе."""
    out: dict[int, np.ndarray] = {}
    for i, s in enumerate(chart.series):
        if s.kind != 'line' or len(s.x) < 2:
            continue
        xs = axis_numbers(s.x)
        if thinnable(s, xs):
            out[i] = xs
    for members in stacks(chart, out).values():
        first = out[members[0]]
        if any(len(out[i]) != len(first) or not np.array_equal(out[i], first) for i in members[1:]):
            for i in members:
                del out[i]
    return out


def stacks(chart: Any, candidates: dict[int, np.ndarray]) -> dict[tuple[str, str], list[int]]:
    """Серии-кандидаты, сгруппированные по стопке (ключ — имя стопки и ось); серии без стопки не входят."""
    groups: dict[tuple[str, str], list[int]] = {}
    for i in candidates:
        s = chart.series[i]
        if s.stack:
            groups.setdefault((s.stack, s.axis), []).append(i)
    return groups


def shared_indices(ys: Sequence[Sequence[float]], limit: int) -> np.ndarray:
    """Общие индексы для серий одной стопки: объединение М4 каждой серии с лимитом ``limit // k``.

    Каждая серия сохраняет свои пики и разрывы, а сумма по стопке на оставленных датах совпадает с суммой по
    всем точкам (серии отданы по одним и тем же индексам)."""
    per = max(limit // max(1, len(ys)), 5)
    keep: set[int] = set()
    for y in ys:
        keep.update(int(k) for k in m4_indices(y, per))
    return np.fromiter(sorted(keep), dtype=int)


def limits(chart: Any, candidates: dict[int, np.ndarray], budget: int = CHART_POINTS,
           sizes: dict[int, int] | None = None) -> int:
    """Лимит точек на линию для графика: бюджет минус то, что прореживать нельзя."""
    sizes = sizes or {i: len(s.x) for i, s in enumerate(chart.series)}
    fixed = sum(n for i, n in sizes.items() if i not in candidates)
    return shares([sizes[i] for i in candidates], max(budget - fixed, SERIES_FLOOR * max(1, len(candidates))))


def screen_indices(chart: Any, budget: int = CHART_POINTS) -> dict[int, np.ndarray]:
    """Какие точки каждой прореживаемой серии уходят на экран целиком (индекс серии → индексы). Без прореживания серии нет в словаре."""
    candidates = plan(chart, budget)
    if not candidates:
        return {}
    limit = limits(chart, candidates, budget)
    out = {}
    grouped = set()
    for members in stacks(chart, candidates).values():
        grouped.update(members)
        if len(candidates[members[0]]) > limit:
            keep = shared_indices([np.asarray(chart.series[i].y, dtype=float) for i in members], limit)
            for i in members:
                out[i] = keep
    for i in candidates:
        s = chart.series[i]
        if i not in grouped and len(s.x) > limit:
            out[i] = m4_indices(np.asarray(s.y, dtype=float), limit)
    return out


def window_indices(chart: Any, x0: float, x1: float, raw: bool = False, budget: int = CHART_POINTS,
                   raw_limit: int = RAW_LIMIT) -> dict[int, tuple[np.ndarray, int]]:
    """Индексы точек каждой прореживаемой серии в окне [x0, x1] (с соседними точками по краям, чтобы линия дошла до краёв).

    ``raw`` — отдать все точки окна, если их на графике не больше ``raw_limit``. Иначе — М4 по бюджету внутри окна.
    Для каждой серии: (индексы, число точек окна до прореживания)."""
    candidates = plan(chart, budget)
    spans: dict[int, tuple[int, int]] = {}
    for i, xs in candidates.items():
        lo = max(int(np.searchsorted(xs, x0, side='left')) - 1, 0)
        hi = min(int(np.searchsorted(xs, x1, side='right')), len(xs) - 1)
        spans[i] = (lo, hi)
    sizes = {i: len(chart.series[i].x) for i in range(len(chart.series))}
    sizes.update({i: hi - lo + 1 for i, (lo, hi) in spans.items()})
    total = sum(sizes.values())
    limit = None if raw and total <= raw_limit else limits(chart, candidates, budget, sizes)
    out = {}
    shared: dict[int, np.ndarray] = {}
    stacked = set()
    for members in stacks(chart, candidates).values():
        stacked.update(members)
        lo, hi = spans[members[0]]
        if limit is not None and hi - lo + 1 > limit:
            keep = lo + shared_indices([np.asarray(chart.series[i].y, dtype=float)[lo:hi + 1] for i in members], limit)
            for i in members:
                shared[i] = keep
    for i, (lo, hi) in spans.items():
        part = np.arange(lo, hi + 1)
        inside = len(part)
        if i in shared:
            part = shared[i]
        elif limit is not None and inside > limit and i not in stacked:
            part = lo + m4_indices(np.asarray(chart.series[i].y, dtype=float)[lo:hi + 1], limit)
        out[i] = (part, inside)
    return out
