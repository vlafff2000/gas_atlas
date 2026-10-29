"""Порядок подписей в легенде: по возрастанию для всех графиков Атласа (сезоны, годы, даты, номера скважин, группы).

Общее правило для экрана и выгрузок: ряды переставляются перед отдачей результата модуля, а данные не меняются.
Естественный порядок: «№ 9» раньше «№ 10», «2025-2026» раньше «2026-2027», «01.02.2024» раньше «15.02.2024».
Настройка проекта ``legend_order``: ``asc`` — по возрастанию (по умолчанию), ``module`` — порядок, который задал модуль.
Таблица под графиком переставляется вместе с рядами, только если её строки — это ряды графика по именам.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any

from .contract import Chart, Series

MODES = ('asc', 'module')
DEFAULT = 'asc'
_DATE = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4})')
_SEP = re.compile(r'[\s_\-]+')


def mode_of(settings: Any) -> str:
    value = (settings or {}).get('legend_order')
    return value if value in MODES else DEFAULT


def label_key(text: Any) -> tuple:
    """Ключ естественного порядка подписи. Чётные части — текст, нечётные — числа: типы на каждой позиции совпадают."""
    text = _DATE.sub(lambda m: f'{m[3]}{int(m[2]):02d}{int(m[1]):02d}', str(text).strip().casefold())
    text = _SEP.sub(' ', text)      # «ГСП-1» и «ГСП 1» — один порядок (как group_colors.group_key)
    return tuple(int(t) if i % 2 else t for i, t in enumerate(re.split(r'(\d+)', text)))


def series_key(s: Series) -> tuple:
    facets = s.facets or {}
    return (label_key(s.group or s.name), label_key(s.name), tuple(label_key(facets[k]) for k in sorted(facets)))


def apply(value: Any, mode: str = DEFAULT) -> Any:
    """Копия графика с рядами в выбранном порядке; остальное (таблицы, данные, исходный объект) не меняется."""
    if mode == 'module' or not isinstance(value, Chart) or len(value.series) < 2:
        return value
    order = sorted(range(len(value.series)), key=lambda i: series_key(value.series[i]))     # sorted устойчива: равные ключи — как были
    if order == list(range(len(order))):
        return value
    chart = dataclasses.replace(value, series=[value.series[i] for i in order])
    table = value.table
    if table is not None and table.swatches and table.rows == [s.name for s in value.series]:
        colors = [table.colors[i] for i in order] if len(table.colors) == len(order) else table.colors
        chart.table = dataclasses.replace(table, rows=[table.rows[i] for i in order],
                                          cells=[table.cells[i] for i in order], colors=colors)
    return chart
