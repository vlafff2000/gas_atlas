"""Пустые наборы данных не показываются в легенде: столбцы только из нулей и ряды без единого значения.

Это подсказка, не запрет: набор остаётся на графике (его можно вернуть или убрать в «Какие ряды выгружать»), выключается
только строка легенды. Линия из нулей — данные (нулевой расход), она в легенде остаётся. Общее для экрана и файлов (``Series.legend``)."""
from __future__ import annotations

import dataclasses

import numpy as np

from .contract import Chart, Result, Series


def _values(s: Series) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in s.y], dtype=float)


def is_empty(s: Series) -> bool:
    values = _values(s)
    if not np.isfinite(values).any():
        return True
    return s.kind == 'bar' and not np.nan_to_num(values).any()


def apply_chart(chart: Chart) -> Chart:
    items: dict[str, list[Series]] = {}
    for s in chart.series:
        items.setdefault(s.group or s.name, []).append(s)
    gone = {key for key, group in items.items() if len(chart.series) > 1 and all(is_empty(s) for s in group)}
    if not gone:
        return chart
    return dataclasses.replace(chart, series=[dataclasses.replace(s, legend=False) if (s.group or s.name) in gone else s for s in chart.series])


def apply(result: Result) -> Result:
    return dataclasses.replace(result, charts=[apply_chart(c) for c in result.charts])
