"""Автоподбор границ и делений шкал Y для всех графиков — одно место для экрана, предпросмотра и файлов.

Арифметика — ``atlas/axis_fit.py`` (круглые шаги, одно число делений на все шкалы графика, «от нуля или нет», общая нулевая
линия); здесь — что о шкале известно по графику: размах её рядов (стопки — суммы), обязателен ли нуль (столбцы, области,
стопки), режим шкалы (``Axis.style['fit']``: ``auto`` / ``zero`` / ``data``; ``Axis.from_zero`` — то же, что ``zero``) и что
задано вручную или модулем. Подбор — подсказка: заданные границы и шаг не трогаются, подбирается только незаданное.

Подобранное записывается в ``Axis.minimum`` / ``maximum`` / ``step`` и в ``Axis.auto`` (значения, число делений, причина,
подсказка о выбросе ``hints`` — шкала выбросы не отсекает, а только сообщает о них и предлагает пределы).
Поле, равное записанному в ``Axis.auto``, считается подобранным: повторный подбор (после оформления, вида с экрана) его
пересчитывает, а изменённое кем-то — оставляет как ручное. Не подбираются: логарифмическая и категорийная шкалы, шкалы с
ящиками, тепловые карты."""
from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np

from .axis_fit import MODES, Need, fit_axes
from .contract import Axis, Chart

FIELDS = (('minimum', 'min'), ('maximum', 'max'), ('step', 'step'))


def _floats(values: Any) -> np.ndarray:
    """Значения ряда числами; пропуски и нечисловое — NaN."""
    try:
        out = np.asarray(values, dtype=float)
        return out if out.ndim == 1 else np.array([], dtype=float)
    except (TypeError, ValueError):
        return np.array([float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else math.nan for v in values], dtype=float)


def extent(chart: Chart, name: str) -> tuple[float, float, bool] | None:
    """Наименьшее и наибольшее значения шкалы (стопки — суммы) и признак «нуль обязателен» (столбцы, области, стопки).
    ``None`` — на шкале ящики (подбор не нужен); без чисел — (nan, nan, признак)."""
    lo, hi, anchor = math.inf, -math.inf, False
    stacks: dict[tuple[str, bool], np.ndarray] = {}
    for s in chart.series:
        if (s.axis or 'y') != name:
            continue
        if s.kind == 'box':
            return None
        anchor = anchor or s.kind == 'bar' or bool(s.fill) or bool(s.stack)
        y = _floats(s.y)
        y = np.where(np.isfinite(y), y, np.nan)
        if not y.size or np.isnan(y).all():
            continue
        lo, hi = min(lo, float(np.nanmin(y))), max(hi, float(np.nanmax(y)))
        if s.stack:
            for negative in (False, True):
                part = np.where(y < 0, y, 0.0) if negative else np.where(y >= 0, y, 0.0)
                if not part.any():
                    continue
                total = stacks.get((s.stack, negative), np.zeros(0))
                if total.size < part.size:
                    total = np.concatenate([total, np.zeros(part.size - total.size)])
                total[:part.size] += part
                stacks[(s.stack, negative)] = total
    for total in stacks.values():
        lo, hi = min(lo, float(total.min())), max(hi, float(total.max()))
    return (lo, hi, anchor) if lo <= hi else (math.nan, math.nan, anchor)


OUTLIER_MIN_POINTS = 12       # меньше точек — о выбросах судить рано
OUTLIER_FENCE = 3.0           # «далёкий выброс» по Тьюки: дальше трёх межквартильных размахов от квартилей
OUTLIER_SHARE = 0.4           # подсказка, только если без выбросов данные заняли бы меньше 40 % нынешнего размаха
OUTLIER_COUNT = 3             # столько выбросов — ещё выбросы; больше (и больше 0,5 % точек) — уже свойство данных


def outlier_hint(chart: Chart, name: str, need: Need) -> dict[str, Any] | None:
    """Подсказка о единичных выбросах, сжимающих остальные данные шкалы: сколько их, какие, какую долю поля занимает остальное
    и какими стали бы пределы без них. Шкала при этом накрывает ВСЕ точки: решение (задать пределы, исключить точку) — за инженером."""
    parts = [_floats(s.y) for s in chart.series if (s.axis or 'y') == name and s.kind in ('line', 'points') and not s.stack]
    values = np.concatenate(parts) if parts else np.array([])
    values = values[np.isfinite(values)]
    if values.size < OUTLIER_MIN_POINTS or need.lo is None or need.hi is None or not need.hi > need.lo:
        return None
    q1, q3 = np.percentile(values, [25, 75])
    spread = max(float(q3 - q1), (need.hi - need.lo) * 1e-6)
    inside = (values >= q1 - OUTLIER_FENCE * spread) & (values <= q3 + OUTLIER_FENCE * spread)
    count = int(values.size - inside.sum())
    if not 0 < count <= max(OUTLIER_COUNT, values.size * 0.005):
        return None
    core = values[inside]
    lo, hi = float(core.min()), float(core.max())
    share = (hi - lo) / (need.hi - need.lo)
    if share >= OUTLIER_SHARE:
        return None
    fit = fit_axes([dataclasses.replace(need, lo=lo, hi=hi, minimum=None, maximum=None, step=None)])[0]
    if fit is None:
        return None
    far = values[~inside]
    order = np.argsort(-np.abs(far - (lo + hi) / 2))
    return {'kind': 'outlier', 'count': count, 'values': [float(v) for v in far[order][:3]], 'share': round(share, 4),
            'min': fit.minimum, 'max': fit.maximum}


def _manual(axis: Axis) -> dict[str, float | None]:
    """Границы и шаг, заданные вручную или модулем (не равные тому, что подобрал автомат)."""
    auto = axis.auto or {}
    out = {}
    for attr, key in FIELDS:
        value = getattr(axis, attr)
        if key == 'step' and not value:
            value = None
        out[attr] = None if value is None or (key in auto and auto[key] == value) else float(value)
    return out


def mode_of(axis: Axis) -> str:
    mode = (axis.style or {}).get('fit')
    return mode if mode in MODES else 'zero' if axis.from_zero else 'auto'


def need_of(chart: Chart, name: str) -> Need | None:
    """Что нужно шкале ``name`` от подбора; ``None`` — шкалу не трогаем."""
    axis = chart.axis_at(name)
    if axis.scale != 'value' or axis.style.get('min') is not None or axis.style.get('max') is not None:
        return None
    found = extent(chart, name)
    if found is None:
        return None
    lo, hi, anchor = found
    empty = math.isnan(lo)
    return Need(None if empty else lo, None if empty else hi, anchor, mode_of(axis), inverse=bool(axis.inverse), **_manual(axis))


def auto_chart(chart: Chart) -> Chart:
    """Копия графика с подобранными границами и шагом каждой шкалы Y, либо тот же график, если менять нечего."""
    if chart.heat is not None:
        return chart
    names = chart.axis_names()
    needs = [need_of(chart, name) for name in names]
    if all(n is None or n.lo is None for n in needs) and not any(chart.axis_at(name).auto for name in names):      # нет чисел и нечего снимать
        return chart
    changes: dict[str, Axis] = {}
    for name, need, fit in zip(names, needs, fit_axes(needs)):
        axis = chart.axis_at(name)
        manual = _manual(axis)
        if need is None:
            if axis.auto is None:
                continue
            fit = None              # шкала перестала подбираться (стала логарифмической): подобранное раньше снимается
        if fit is None:
            fresh = dataclasses.replace(axis, auto=None, **{attr: manual[attr] for attr, _key in FIELDS})
        else:
            auto: dict[str, Any] = {key: getattr(fit, attr) for attr, key in FIELDS if manual[attr] is None}
            auto.update(n=fit.n, zero=fit.zero, why=fit.why, lo=need.lo, hi=need.hi, anchor=need.anchor)      # type: ignore[union-attr]
            hint = outlier_hint(chart, name, need) if all(v is None for v in manual.values()) else None      # type: ignore[arg-type]
            if hint:
                auto['hints'] = [hint]
            fresh = dataclasses.replace(axis, minimum=fit.minimum, maximum=fit.maximum, step=fit.step, auto=auto)
        if fresh != axis:
            changes[name] = fresh
    return dataclasses.replace(chart, **changes) if changes else chart


def apply(result: Any) -> Any:
    """Результат раздела с подобранными шкалами на каждом графике; без графиков — тот же объект."""
    charts = getattr(result, 'charts', None)
    if not charts:
        return result
    fresh = [auto_chart(c) for c in charts]
    return result if all(a is b for a, b in zip(fresh, charts)) else dataclasses.replace(result, charts=fresh)
