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
    tick_color = layout_axis.tickfont.color if layout_axis.tickfont is not None and layout_axis.showline else None
    return Axis(label=_text(layout_axis.title), scale=scale, inverse=flipped or layout_axis.autorange == 'reversed', color=tick_color or '',
                from_zero=layout_axis.rangemode == 'tozero', step=layout_axis.dtick if scale == 'value' and isinstance(layout_axis.dtick, (int, float)) else None,
                categories=list(layout_axis.categoryarray) if scale == 'category' and layout_axis.categoryarray is not None else None,
                minimum=float(rng[0]) if value and scale == 'value' else None, maximum=float(rng[1]) if value and scale == 'value' else None)


def _values(values, scale: str) -> list[Any]:
    if values is None:
        return []
    if scale == 'time':
        return list(pd.to_datetime(list(values)))
    return list(values)


def to_chart(fig, chart_id: str = 'export-preview', drawn_only: bool = False) -> Chart:
    """``drawn_only`` — без скрытых рядов (``visible`` False или «только в легенде»): то, что попадёт в файл."""
    layout = fig.layout
    x, y = _axis(layout.xaxis), _axis(layout.yaxis)
    right = {}
    for n, name in enumerate(('y2', 'y3', 'y4', 'y5'), start=2):      # правые шкалы подряд: без пропусков
        if not any(t.yaxis == name for t in fig.data):
            break
        right[name] = _axis(getattr(layout, 'yaxis' + str(n)))
    y2, y3 = right.get('y2'), right.get('y3')
    y4, y5 = right.get('y4'), right.get('y5')
    series = []
    for t in fig.data:
        meta = t.meta if isinstance(t.meta, dict) else {}
        kind = type(t).__name__
        if kind not in ('Scatter', 'Bar') or (drawn_only and t.visible in (False, 'legendonly')):
            continue
        color = ''
        symbol = str(getattr(t.marker, 'symbol', None) or 'circle') if t.marker is not None else 'circle'      # у столбцов символа нет
        line = getattr(t, 'line', None)      # у столбцов (Bar) своего поля line нет
        for holder in (line, t.marker):
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
            dash=_DASH.get(line.dash if line is not None and line.dash else 'solid', 'solid') if mark == 'line' else '',
            width=float(line.width) if mark == 'line' and line is not None and line.width else 0.0,
            legend=t.showlegend is not False, color=color, opacity=float(t.opacity if t.opacity is not None else 1.0),
            symbol=_SYMBOL.get(symbol.replace('-open', ''), 'circle'), hollow='open' in symbol,
            markers=mark == 'line' and 'markers' in (t.mode or ''), axis=t.yaxis if t.yaxis in right else 'y',
            ids=ids, dataset=dataset))
    return Chart(id=chart_id, title=_text(layout.title), x=x, y=y, y2=y2, y3=y3, y4=y4, y5=y5, series=series)


def _manual(fig, name: str) -> dict[str, Any]:
    """Границы и шаг шкалы, заданные инженером в оформлении выгрузки (``meta.format`` — поля формы, ``meta.style`` — модель оформления)."""
    meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
    form = ((meta.get('format') or {}).get('axes') or {}).get(name) or {}
    style = ((meta.get('style') or {}).get('axes') or {}).get(name) or {}
    out = {}
    for field, keys in (('minimum', ('min',)), ('maximum', ('max',)), ('step', ('step', 'major'))):
        value = next((spec[k] for spec in (style, form) for k in keys if isinstance(spec.get(k), (int, float)) and not isinstance(spec.get(k), bool)), None)
        if value is not None:
            out[field] = float(value)
    return out


def _levels(fig, name: str) -> list[float]:
    """Уровни линий и подписей, привязанных к шкале (``add_hline``, ``add_vline``, ``add_annotation``): подбор не должен
    вынести их за поле."""
    side = 'x' if name == 'x' else 'y'
    out = []
    for item in fig.layout.shapes or ():
        if (getattr(item, side + 'ref') or side) == name:
            out += [v for v in (getattr(item, side + '0'), getattr(item, side + '1')) if isinstance(v, (int, float))]
    for item in fig.layout.annotations or ():
        if (getattr(item, side + 'ref') or side) == name and isinstance(getattr(item, side), (int, float)):
            out.append(getattr(item, side))
    return out


def fit_figure(fig):
    """Шкалы Y и числовую ось X графика выгрузки подбирает та же функция, что на экране разделов и в их файлах (``atlas/axis_auto.py``):
    пакетные вкладки «Экспорта» получают те же границы, шаг и общее число делений, что интерактивный предпросмотр.

    Заданное инженером в оформлении сильнее: такая шкала участвует в подборе как ручная и остаётся как есть.
    График, размах которого по рядам оценить нельзя (ящики, планки погрешностей, стопки), и шкала, за пределы которой
    вышла бы линия уровня или подпись, не трогаются — рисуются, как раньше. Меняет и возвращает ту же фигуру."""
    from .axis_auto import auto_chart, axis_of
    from .render import align_y_axes
    drawn = [t for t in fig.data if t.visible not in (False, 'legendonly')]
    if not drawn or fig.layout.barmode in ('stack', 'relative'):
        return fig
    for t in drawn:
        meta = t.meta if isinstance(t.meta, dict) else {}
        plain = type(t).__name__ in ('Scatter', 'Bar') and not getattr(t, 'stackgroup', None) and getattr(t, 'base', None) is None
        bars = getattr(t, 'error_y', None)
        if not plain or meta.get('cat_stack') or meta.get('fill') or (bars is not None and (bars.array is not None or bars.value is not None)):
            return fig
    chart = to_chart(fig, drawn_only=True)
    names = [*chart.axis_names(), 'x']
    manual = {name: _manual(fig, name) for name in names}
    for name in names:
        axis = axis_of(chart, name)
        for field, value in manual[name].items():
            setattr(axis, field, value)
    chart = auto_chart(chart)
    for name in names:
        axis = axis_of(chart, name)
        outside = axis.minimum is not None and axis.maximum is not None and any(not axis.minimum <= v <= axis.maximum for v in _levels(fig, name))
        if manual[name] or not axis.auto or outside:
            axis.step = None        # такая шкала остаётся как была
    align_y_axes(fig, chart)
    x = chart.x
    if x.step and x.minimum is not None and x.maximum is not None:
        count = (x.maximum - x.minimum) / x.step
        if 1 <= count <= 150 and abs(count - round(count)) < 1e-6:
            fig.layout.xaxis.range = [x.maximum, x.minimum] if x.inverse else [x.minimum, x.maximum]
            fig.layout.xaxis.dtick = x.step
    return fig
