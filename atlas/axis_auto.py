"""Автоподбор границ шкал Y для всех графиков: круглые деления, все точки внутри, без лишнего пустого места.

Ядро — ``atlas.engine.modules.charts``: ``tight_axis`` (линии и точки: шаг 1, 2, 5 · 10^k, начало на сетке шага) и ``zero_axis``
(столбцы, области, стопки: ноль на делении, верх круглый, отрицательные значения учтены). Каждая шкала считается независимо по
своим рядам, всегда по 5 делений: сетки нескольких шкал совпадают. Это подсказка: шкала, у которой границы, шаг или «от нуля»
заданы модулем или вручную, не трогается; «от нуля» задаёт только основание, верх подбирается. Не подбираются: логарифмическая и
категорийная шкалы, оси с ящиками, тепловые карты."""
from __future__ import annotations

import dataclasses
import math
from typing import Any

from .contract import Axis, Chart
from .engine.modules.charts import tight_axis, zero_axis


def _extent(chart: Chart, name: str) -> tuple[float, float, bool] | None:
    """Наименьшее и наибольшее значения шкалы (стопки — суммы) и признак «ноль обязателен» (столбцы, области); None — подбор не нужен."""
    lo, hi, zero = math.inf, -math.inf, False
    stacks: dict[tuple[str, bool], dict[int, float]] = {}
    for s in chart.series:
        if (s.axis or 'y') != name:
            continue
        if s.kind == 'box':
            return None
        zero = zero or s.kind == 'bar' or bool(s.fill) or bool(s.stack)
        for i, v in enumerate(s.y):
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                continue
            lo, hi = min(lo, float(v)), max(hi, float(v))
            if s.stack:
                part = stacks.setdefault((s.stack, v < 0), {})
                part[i] = part.get(i, 0.0) + float(v)
    for part in stacks.values():
        for total in part.values():
            lo, hi = min(lo, total), max(hi, total)
    return (lo, hi, zero) if lo <= hi else None


def _bounds(axis: Axis, extent: tuple[float, float, bool]) -> tuple[float, float] | None:
    lo, hi, zero = extent
    if axis.scale != 'value' or axis.step or axis.minimum is not None or axis.maximum is not None \
            or axis.style.get('min') is not None or axis.style.get('max') is not None:
        return None
    if zero or axis.from_zero:
        return zero_axis(lo, hi)
    return tight_axis([lo, hi], lower=0 if lo >= 0 else None)


def auto_chart(chart: Chart) -> Chart:
    """Копия графика с подобранными границами каждой шкалы Y, либо тот же график, если подбор не нужен."""
    if chart.heat is not None:
        return chart
    changes: dict[str, Axis] = {}
    for name in chart.axis_names():
        extent = _extent(chart, name)
        bounds = _bounds(chart.axis_at(name), extent) if extent else None
        if bounds:
            changes[name] = dataclasses.replace(chart.axis_at(name), minimum=bounds[0], maximum=bounds[1])
    return dataclasses.replace(chart, **changes) if changes else chart


def apply(result: Any) -> Any:
    """Результат раздела с подобранными границами на каждом графике; без графиков — тот же объект."""
    charts = getattr(result, 'charts', None)
    if not charts:
        return result
    fresh = [auto_chart(c) for c in charts]
    return result if all(a is b for a, b in zip(fresh, charts)) else dataclasses.replace(result, charts=fresh)
