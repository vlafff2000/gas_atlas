"""Преемственность цветов групп: ряд графика, названный как группа объекта, получает её сквозной цвет.

Модули могут задать цвет сами (``Series.color``); здесь добираются ряды без цвета, чтобы группа выглядела одинаково на любом графике.
Ряды сезонов, видов и т. п. (имя — не группа) не затрагиваются; ручной цвет ряда в настройках графика сильнее.
"""
from __future__ import annotations

import dataclasses

from .contract import Chart, Result
from .group_colors import _known, colors_for, group_key


def paint(result: Result) -> Result:
    known = {group_key(g) for g in _known}
    if not known:
        return result
    charts = []
    for chart in result.charts:
        names = {s.group or s.name for s in chart.series if not s.color}
        groups = [n for n in names if group_key(n) in known]
        if not groups:
            charts.append(chart)
            continue
        colors = colors_for(groups)
        series = [dataclasses.replace(s, color=colors[s.group or s.name]) if not s.color and (s.group or s.name) in colors else s
                  for s in chart.series]
        charts.append(dataclasses.replace(chart, series=series))
    return dataclasses.replace(result, charts=charts)
