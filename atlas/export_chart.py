"""График выгрузки (фигура Plotly кода 5.8) → ``Chart`` Атласа 6: интерактивный предпросмотр экспорта.

Точки, по которым можно щёлкнуть, помечены в фигуре 5.8 так же, как для её собственного предпросмотра:
``trace.meta = {module, selectable}`` и ``trace.customdata[i][0]`` — идентификатор точки.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

import numpy as np
import pandas as pd

from .contract import Axis, Chart, Series
from .domain import DatasetKind
from .engine.core.export import decode_arrays

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


def format_series_label(trace) -> str:
    meta = trace.meta if isinstance(trace.meta, dict) else {}
    name = str(trace.name or '')
    if meta.get('export_format_series'):
        return meta['export_format_series']
    if meta.get('module') == 'response':
        return 'Уровень жидкости' if meta.get('metric') == 'level' else 'Пластовое давление'
    if meta.get('module') == 'gdi' and trace.legendgroup:
        role = {'расчет': 'Расчётная кривая', 'БД': 'Кривая БД', 'по коэффициентам': 'Кривая по коэффициентам'}
        group = trace.legendgroup
        suffix = name[len(group):].removeprefix(' · ') if name.startswith(group) else ''
        prefix = next((p + ' · ' for p in ('до КРС', 'после КРС') if group.startswith(p + ' · ')), '')
        return prefix + role.get(suffix, 'Замеры' if meta.get('selectable') else 'Кривая')
    return re.sub(r'^№\s*[^\s]+\s*·\s*', '', name)


def to_chart(fig, chart_id: str = 'export-preview', drawn_only: bool = False, format_keys: bool = False) -> Chart:
    """``drawn_only`` — без скрытых рядов (``visible`` False или «только в легенде»): то, что попадёт в файл."""
    layout = fig.layout
    x, y = _axis(layout.xaxis), _axis(layout.yaxis)
    if layout.xaxis.type is None and any(
        isinstance(next(iter(decode_arrays(t.x)), None), (dt.date, np.datetime64))
        for t in fig.data if getattr(t, 'x', None) is not None
    ):
        x.scale = 'time'
    right = {}
    for n, name in enumerate(('y2', 'y3', 'y4', 'y5'), start=2):      # правые шкалы подряд: без пропусков
        if not any(getattr(t, 'yaxis', None) == name for t in fig.data):
            break
        right[name] = _axis(getattr(layout, 'yaxis' + str(n)))
    y2, y3 = right.get('y2'), right.get('y3')
    y4, y5 = right.get('y4'), right.get('y5')
    series = []
    for t in fig.data:
        meta = t.meta if isinstance(t.meta, dict) else {}
        kind = type(t).__name__
        if kind not in ('Scatter', 'Scattergl', 'Bar', 'Box') or (drawn_only and t.visible in (False, 'legendonly')):
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
        elif kind == 'Box':
            if not format_keys:
                continue
            mark = 'box'
        elif t.mode == 'markers':
            mark = 'points'
        else:
            mark = 'line'
        ids = dataset = None
        if meta.get('selectable') and t.customdata is not None and meta.get('module') in {d.value for d in DatasetKind}:
            ids = [str(row[0]) if hasattr(row, '__len__') and not isinstance(row, str) else str(row) for row in decode_arrays(t.customdata)]
            dataset = DatasetKind(meta['module'])
        # Plotly 6 кодирует numpy-массивы при копировании фигуры для оформления.
        # Считать размах нужно по числам, а не по ключам словаря dtype/bdata.
        xs = _values(decode_arrays(t.x), x.scale)
        ys = list(decode_arrays(t.y)) if t.y is not None else []
        if mark == 'box':
            values = pd.to_numeric(pd.Series(ys), errors='coerce').dropna()
            xs = [xs[0] if xs else t.name or '']
            ys = [np.percentile(values, [0, 25, 50, 75, 100]).tolist() if len(values) else None]
        stack = meta.get('cat_stack') or meta.get('stack') or getattr(t, 'stackgroup', None)
        if not stack and kind == 'Bar' and layout.barmode in ('stack', 'relative'):
            stack = t.yaxis or 'y'
        series.append(Series(
            name=t.name or '', x=xs, y=ys, kind=mark, group=t.name or '',
            dash=_DASH.get(line.dash if line is not None and line.dash else 'solid', 'solid') if mark == 'line' else '',
            width=float(line.width) if mark == 'line' and line is not None and line.width else 0.0,
            legend=t.showlegend is not False, color=color, opacity=float(t.opacity if t.opacity is not None else 1.0),
            symbol=_SYMBOL.get(symbol.replace('-open', ''), 'circle'), hollow='open' in symbol,
            markers=mark == 'line' and 'markers' in (t.mode or ''), axis=t.yaxis if t.yaxis in right else 'y',
            stack=str(stack or ''), fill=bool(meta.get('fill')), ids=ids, dataset=dataset, format_label=format_series_label(t) if format_keys else ''))
    return Chart(id=chart_id, title=_text(layout.title), x=x, y=y, y2=y2, y3=y3, y4=y4, y5=y5, series=series)


def apply_branch_format(figure, doc):
    """Общий «Формат» на исходной фигуре. Сохраняем аннотации, шкалы и данные задания."""
    from copy import deepcopy
    from dataclasses import replace

    from .chart_format import _look
    from .chart_style import apply_format, merge_formats, series_key
    from .render import WIDTH_PT, style_meta, to_plotly

    fig = deepcopy(figure)
    chart = to_chart(fig, format_keys=True)
    formatted = apply_format(chart, doc)
    converted = style_meta(formatted)
    axes = {}
    for name, spec in doc.get('axes', {}).items():
        if name not in converted['axes']:
            continue
        axis = formatted.x if name == 'x' else formatted.axis_at(name)
        fields = converted['axes'][name]
        # Стиль оси поверх прежнего диапазона. Границы передаются лишь при ручном вводе.
        axes[name] = {k: v for k, v in fields.items() if k not in ('min', 'max', 'step', 'color') or k in spec}
        if 'inverse' in spec:
            axes[name]['inverse'] = axis.inverse
        if 'from_zero' in spec and axis.scale == 'value':
            axes[name]['from_zero'] = axis.from_zero

    meta = dict(fig.layout.meta) if isinstance(fig.layout.meta, dict) else {}
    meta['style'] = merge_formats(meta.get('style'), {'chart': formatted.style, 'axes': axes})
    if 'legend' in formatted.style:
        meta['format'] = {**(meta.get('format') or {}), 'legend': formatted.style['legend']}
    fig.layout.meta = meta

    looks = doc.get('series') or {}
    traces = [t for t in fig.data if t.type in ('scatter', 'scattergl', 'bar', 'box')]
    for trace, series in zip(traces, chart.series):
        look = looks.get(series_key(series))
        if not look:
            continue
        tmeta = dict(trace.meta) if isinstance(trace.meta, dict) else {}
        own = set(tmeta.get('own', ()))
        if 'color' in look:
            trace.marker.color = look['color']
            if trace.type in ('scatter', 'scattergl'):
                trace.line.color = look['color']
            own.add('color')
        if 'opacity' in look:
            trace.opacity = look['opacity']
            own.add('alpha')
        if trace.type in ('scatter', 'scattergl'):
            mode = trace.mode or 'lines'
            line = look.get('line', 'lines' in mode) and series.kind == 'line'
            marker = look.get('marker', 'markers' in mode)
            if not line and not marker:
                trace.visible = False
            else:
                trace.mode = '+'.join(part for part, enabled in (('lines', line), ('markers', marker)) if enabled)
            if 'width' in look:
                trace.line.width = round(look['width'] * WIDTH_PT, 2)
                own.add('width')
            if 'size' in look:
                trace.marker.size = look['size']
                own.add('size')
        if look.get('valueLabels') is False:
            tmeta.pop('value_labels', None)
        trace.meta = tmeta
        _look(trace, [look], own)
        trace.meta = {**trace.meta, 'own': sorted(own)}

    derived = formatted.series[len(chart.series):]
    if derived:
        fig.add_traces(list(to_plotly(replace(formatted, series=derived)).data))
    return fig


def _manual(fig, name: str, *, include_legacy=True) -> dict[str, Any]:
    """Границы и шаг шкалы, заданные инженером в оформлении выгрузки (``meta.format`` — поля формы, ``meta.style`` — модель оформления)."""
    meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
    form = (((meta.get('format') or {}).get('axes') or {}).get(name) or {}) if include_legacy else {}
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


def _keep_hand_ranges(fig):
    """График, шкалы которого не подбираются (стопка, ящики, планки погрешностей), всё равно получает границы Y, заданные
    инженером: «от 0 до 20» остаётся 0–20, а не диапазоном данных."""
    chart = to_chart(fig, drawn_only=True)
    for name in chart.axis_names():
        manual = _manual(fig, name)
        low, high = manual.get('minimum'), manual.get('maximum')
        if low is None and high is None:
            continue
        layout_axis = getattr(fig.layout, 'yaxis' + name[1:])
        current = list(layout_axis.range) if layout_axis.range is not None else [None, None]
        low, high = (low if low is not None else current[0]), (high if high is not None else current[1])
        if low is not None and high is not None and low < high:
            layout_axis.range = [low, high]
    return fig


def fit_figure(fig):
    """Шкалы Y и числовую ось X графика выгрузки подбирает та же функция, что на экране разделов и в их файлах (``atlas/axis_auto.py``):
    пакетные вкладки «Экспорта» получают те же границы, шаг и общее число делений, что интерактивный предпросмотр.

    Заданное инженером в оформлении сильнее: такая шкала участвует в подборе как ручная и остаётся как есть.
    График, размах которого по рядам оценить нельзя (ящики, планки погрешностей, стопки), и шкала, за пределы которой
    вышла бы линия уровня или подпись, не трогаются — рисуются, как раньше. Меняет и возвращает ту же фигуру."""
    from .axis_auto import auto_chart, axis_of
    from .axis_fit import DATA_LIMIT_MODES
    from .render import align_y_axes
    meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
    formatting = meta.get('style') or {}
    styles = formatting.get('axes') or {}
    chart_style = formatting.get('chart') or {}
    drawn = [t for t in fig.data if t.visible not in (False, 'legendonly')]
    if not drawn:
        return fig
    branch_fit = chart_style.get('y_fit')
    requested = branch_fit in DATA_LIMIT_MODES or any(spec.get('fit') in DATA_LIMIT_MODES for name, spec in styles.items() if name != 'x')
    special = fig.layout.barmode in ('stack', 'relative')
    for t in drawn:
        trace_meta = t.meta if isinstance(t.meta, dict) else {}
        plain = type(t).__name__ in ('Scatter', 'Bar') and not getattr(t, 'stackgroup', None) and getattr(t, 'base', None) is None
        bars = getattr(t, 'error_y', None)
        if not plain or trace_meta.get('cat_stack') or trace_meta.get('fill') or (bars is not None and (bars.array is not None or bars.value is not None)):
            special = True
    if special and not requested:
        return _keep_hand_ranges(fig)
    chart_id = 'export-response' if meta.get('module') == 'response' else 'export-preview'
    chart = to_chart(fig, chart_id, drawn_only=True, format_keys=requested and special)
    chart.style.update(chart_style)
    names = [*chart.axis_names(), 'x']
    manual = {name: _manual(fig, name, include_legacy=not branch_fit or name == 'x') for name in names}
    for name in names:
        axis = axis_of(chart, name)
        spec = styles.get(name) or {}
        mode = spec.get('fit') or (branch_fit if name != 'x' else None)
        if mode:
            axis.style['fit'] = mode
        if 'inverse' in spec:
            axis.inverse = spec['inverse']
        if 'from_zero' in spec:
            axis.from_zero = spec['from_zero']
        if spec.get('scale') == 'log':
            axis.scale = 'log'
        automatic_bounds = not manual[name] and any(k in spec for k in ('fit', 'from_zero'))
        if automatic_bounds or mode in DATA_LIMIT_MODES or (branch_fit and name != 'x'):
            axis.minimum = axis.maximum = axis.step = None
        for field, value in manual[name].items():
            setattr(axis, field, value)
    chart = auto_chart(chart)
    shared = len(chart.axis_names()) > 1 or bool(chart_style.get('y_intervals'))
    for name in names:
        axis = axis_of(chart, name)
        exact = axis.style.get('fit') in DATA_LIMIT_MODES
        branch_axis = bool(branch_fit and name != 'x' and axis.scale == 'value')
        format_grid = (name in styles or branch_axis) and axis.auto and (
            name == 'x' and axis.step or (shared or exact or branch_axis) and axis.auto.get('n'))
        if format_grid:
            spec = formatting.setdefault('axes', {}).setdefault(name, {})
            spec.update(min=axis.minimum, max=axis.maximum, step=axis.step)
        outside = axis.minimum is not None and axis.maximum is not None and any(not axis.minimum <= v <= axis.maximum for v in _levels(fig, name))
        sync = format_grid or (shared and name != 'x' and axis.auto and axis.auto.get('n') and not manual[name])
        if not axis.auto or (manual[name] and not sync) or (outside and not exact):
            axis.step = None        # такая шкала остаётся как была
    align_y_axes(fig, chart)
    x = chart.x
    if not special and x.step and x.minimum is not None and x.maximum is not None:
        count = (x.maximum - x.minimum) / x.step
        if 1 <= count <= 150 and abs(count - round(count)) < 1e-6:
            fig.layout.xaxis.range = [x.maximum, x.minimum] if x.inverse else [x.minimum, x.maximum]
            fig.layout.xaxis.tick0, fig.layout.xaxis.dtick = x.minimum, x.step
    return fig
