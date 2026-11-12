"""Автоподбор границ и делений шкал Y для всех графиков — одно место для экрана, предпросмотра и файлов.

Арифметика — ``atlas/axis_fit.py`` (круглые шаги, одно число делений на все шкалы графика, «от нуля или нет», общая нулевая
линия); здесь — что о шкале известно по графику: размах её рядов (стопки — суммы), обязателен ли нуль (столбцы, области,
стопки), режим шкалы (``Axis.style['fit']``: ``auto`` / ``zero`` / ``data``; ``Axis.from_zero`` — то же, что ``zero``) и что
задано вручную или модулем. Подбор — подсказка: заданные границы и шаг не трогаются, подбирается только незаданное.

Подобранное записывается в ``Axis.minimum`` / ``maximum`` / ``step`` и в ``Axis.auto`` (значения, число делений, причина).
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
    if all(n is None or n.lo is None for n in needs):          # нет чисел ни на одной шкале: подбирать нечего
        return chart
    changes: dict[str, Axis] = {}
    for name, need, fit in zip(names, needs, fit_axes(needs)):
        axis = chart.axis_at(name)
        if need is None:
            continue
        manual = _manual(axis)
        if fit is None:
            fresh = dataclasses.replace(axis, auto=None, **{attr: manual[attr] for attr, _key in FIELDS})
        else:
            auto: dict[str, Any] = {key: getattr(fit, attr) for attr, key in FIELDS if manual[attr] is None}
            auto.update(n=fit.n, zero=fit.zero, why=fit.why, lo=need.lo, hi=need.hi, anchor=need.anchor)
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
