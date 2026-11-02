"""Автоподбор границ шкалы Y для всех графиков: круглые деления, все точки внутри, без лишнего пустого места.

Ядро — ``atlas.engine.modules.charts.tight_axis`` (шаг 1, 2, 5 · 10^k, начало на сетке шага). Это подсказка: подбор касается только
шкалы, у которой границы не заданы ни модулем, ни вручную; всё, что инженер ввёл сам (границы, шаг, «от нуля»), главнее.
Не трогаются: столбцы, области, стопки, ящики, тепловые карты, логарифмическая и категорийная шкалы, оси с заданным шагом,
графики с несколькими шкалами Y (их выравнивает сетка на 5 делений в интерфейсе и выгрузке)."""
from __future__ import annotations

import dataclasses
import math
from typing import Any

from .contract import Axis, Chart
from .engine.modules.charts import tight_axis


def _values(chart: Chart) -> list[float] | None:
    """Значения рядов шкалы Y или None, если автоподбор к графику не применим."""
    out: list[float] = []
    for s in chart.series:
        if s.kind in ('bar', 'box') or s.stack or s.fill or s.step:
            return None
        out.extend(float(v) for v in s.y if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))
    return out


def auto_chart(chart: Chart) -> Chart:
    """Копия графика с подобранными границами шкалы Y, либо тот же график, если подбор не нужен."""
    y: Axis = chart.y
    if chart.heat is not None or chart.y2 is not None or y.scale != 'value' or y.from_zero or y.step or y.style.get('min') is not None \
            or y.style.get('max') is not None or y.minimum is not None or y.maximum is not None:
        return chart
    values = _values(chart)
    if not values:
        return chart
    bounds = tight_axis(values, lower=0 if min(values) >= 0 else None)
    if bounds is None:
        return chart
    return dataclasses.replace(chart, y=dataclasses.replace(y, minimum=bounds[0], maximum=bounds[1]))


def apply(result: Any) -> Any:
    """Результат раздела с подобранными границами на каждом графике; без графиков — тот же объект."""
    charts = getattr(result, 'charts', None)
    if not charts:
        return result
    fresh = [auto_chart(c) for c in charts]
    return result if all(a is b for a, b in zip(fresh, charts)) else dataclasses.replace(result, charts=fresh)
