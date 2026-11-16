"""Столбцы по группам скважин в общем ядре графиков: одна категория на оси X — одна группа — один цвет группы.

Модуль даёт один ряд столбцов, где категории — названия групп. Здесь он раскладывается в ряды стопки «по одному на группу»
(в каждой категории виден один столбец): цвет берётся из сквозной палитры групп (``atlas/group_colors.py``, с ручными
цветами инженера), порядок категорий не меняется, подписи и подсказки остаются у своей группы. Так столбцы групп одинаково
выглядят на экране и во всех файлах, а ручной цвет группы действует и на них.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Sequence

from .contract import Series
from .group_colors import NO_GROUP, colors_for, group_key

STACK = 'by-group'


def is_group_bars(chart) -> bool:
    return chart.x.scale == 'category' and bool(chart.x.categories)


def _at(values: Sequence[Any] | None, i: int, blank: Any) -> list[Any] | None:
    return None if values is None else [v if j == i else blank for j, v in enumerate(values)]


def split_bars(series: Series, colors: dict[str, str] | None = None) -> list[Series]:
    """Ряд столбцов с категориями-группами → по ряду на группу (стопка ``by-group``, легенда не нужна: подписи на оси)."""
    cats = [str(c) for c in series.x]
    palette = colors if colors is not None else colors_for([c for c in cats if group_key(c) != group_key(NO_GROUP)])
    out = []
    for i, name in enumerate(cats):
        y = [v if j == i else None for j, v in enumerate(series.y)]
        out.append(dataclasses.replace(
            series, name=name, x=cats, y=y, group=name, color=palette.get(name, '') or colors_for([name])[name], stack=STACK, legend=False,
            labels=_at(series.labels, i, ''), captions=_at(series.captions, i, ''), segments=_at(series.segments, i, ''),
            ids=None if series.ids is None else list(series.ids), values=_at(series.values, i, None)))
    return out


def split_group_bars(chart, known: set[str]):
    """Единственный ряд столбцов без цвета, у которого все категории — группы объекта: раскладывается по группам (``split_bars``).
    Остальные графики (несколько рядов, стопка, цвет задан модулем, категории не группы) остаются как есть."""
    series = [s for s in chart.series if s.kind == 'bar']
    if chart.x.scale != 'category' or len(chart.series) != 1 or len(series) != 1:
        return chart
    s = series[0]
    cats = [str(c) for c in s.x]
    if s.color or s.stack or s.segments or len(cats) < 1 or any(group_key(c) not in known for c in cats):
        return chart
    return dataclasses.replace(chart, series=split_bars(s))
