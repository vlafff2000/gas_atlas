"""График выгрузки (фигура Plotly кода 5.8) → ``Chart`` Атласа 6: интерактивный предпросмотр экспорта.

Точки, по которым можно щёлкнуть, помечены в фигуре 5.8 так же, как для её собственного предпросмотра:
``trace.meta = {module, selectable}`` и ``trace.customdata[i][0]`` — идентификатор точки.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .contract import Axis, Chart, Series
from .domain import DatasetKind

_DASH = {'solid': 'solid', 'dash': 'dash', 'dot': 'dot', 'dashdot': 'dashdot', 'longdash': 'longdash'}
_SYMBOL = {'circle': 'circle', 'square': 'square', 'diamond': 'diamond', 'triangle-up': 'triangle'}


def _text(title) -> str:
    return str(getattr(title, 'text', None) or '')


def _axis(layout_axis) -> Axis:
    kind = layout_axis.type
    scale = {'date': 'time', 'log': 'log', 'category': 'category'}.get(kind, 'value')
    rng = layout_axis.range
    value = scale in ('value', 'log') and rng is not None and len(rng) == 2
    flipped = bool(value and scale == 'value' and rng[0] > rng[1])     # выровненная ось с обратным направлением: range = [верх, низ]
    if flipped:
        rng = [rng[1], rng[0]]
    return Axis(label=_text(layout_axis.title), scale=scale, inverse=flipped or layout_axis.autorange == 'reversed',
                from_zero=layout_axis.rangemode == 'tozero', step=layout_axis.dtick if scale == 'value' and isinstance(layout_axis.dtick, (int, float)) else None,
                categories=list(layout_axis.categoryarray) if scale == 'category' and layout_axis.categoryarray is not None else None,
                minimum=float(rng[0]) if value and scale == 'value' else None, maximum=float(rng[1]) if value and scale == 'value' else None)


def _values(values, scale: str) -> list[Any]:
    if values is None:
        return []
    if scale == 'time':
        return list(pd.to_datetime(list(values)))
    return list(values)


def to_chart(fig, chart_id: str = 'export-preview') -> Chart:
    layout = fig.layout
    x, y = _axis(layout.xaxis), _axis(layout.yaxis)
    y2 = _axis(layout.yaxis2) if any(t.yaxis == 'y2' for t in fig.data) else None
    series = []
    for t in fig.data:
        meta = t.meta if isinstance(t.meta, dict) else {}
        kind = type(t).__name__
        if kind not in ('Scatter', 'Bar'):
            continue
        color = ''
        for holder in (t.line, t.marker):
            if holder is not None and isinstance(holder.color, str):
                color = holder.color
                break
        if kind == 'Bar':
            mark = 'bar'
        elif t.mode == 'markers':
            mark = 'points'
        else:
            mark = 'line'
        ids = dataset = None
        if meta.get('selectable') and t.customdata is not None and meta.get('module') in {d.value for d in DatasetKind}:
            ids = [str(row[0]) if hasattr(row, '__len__') and not isinstance(row, str) else str(row) for row in t.customdata]
            dataset = DatasetKind(meta['module'])
        xs = _values(t.x, x.scale)
        series.append(Series(
            name=t.name or '', x=xs, y=list(t.y) if t.y is not None else [], kind=mark, group=t.name or '',
            dash=_DASH.get(t.line.dash if t.line is not None and t.line.dash else 'solid', 'solid') if mark == 'line' else '',
            width=float(t.line.width) if mark == 'line' and t.line is not None and t.line.width else 0.0,
            legend=t.showlegend is not False, color=color, opacity=float(t.opacity if t.opacity is not None else 1.0),
            symbol=_SYMBOL.get(str(t.marker.symbol or 'circle').replace('-open', ''), 'circle') if t.marker is not None else 'circle',
            hollow='open' in str(t.marker.symbol or '') if t.marker is not None else False,
            markers=mark == 'line' and 'markers' in (t.mode or ''), axis='y2' if t.yaxis == 'y2' else 'y',
            ids=ids, dataset=dataset))
    return Chart(id=chart_id, title=_text(layout.title), x=x, y=y, y2=y2, series=series)
