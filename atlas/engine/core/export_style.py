"""Ручное оформление графика конструктора в статическом рендере (``figure_bytes``): заголовок, шрифты, оси, сетка, фон, легенда.

Спецификация приходит в ``fig.layout.meta['style']`` = ``{'chart': {...}, 'axes': {'x': {...}, 'y': {...}, 'y2': {...}}}``
(``atlas/render.py: style_meta``; поля — ``atlas/chart_style.py``). Применяется последней, поэтому перекрывает автоматику
и вид Excel: последнее слово за инженером. Не заданное остаётся как нарисовано.
Размеры шрифтов — в пунктах рисунка; шрифты — из набора выгрузки (``fonts.FONTS``).
"""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from ...rich_text import mpl_text

DATE_FORMATS = {'dd.MM.yyyy': '%d.%m.%Y', 'MM.yyyy': '%m.%Y', 'yyyy': '%Y', 'dd.MM': '%d.%m'}


def _family(key: Any):
    if not key:
        return None
    from .fonts import family_for
    return family_for(key)


def ru_format(decimals: int):
    """Число по-русски: пробел между тысячами, запятая в дроби."""
    from matplotlib.ticker import FuncFormatter
    return FuncFormatter(lambda v, _: f'{v:,.{decimals}f}'.replace(',', ' ').replace('.', ','))


def _limit(value: float, date: bool) -> Any:
    if not date:
        return value
    from matplotlib.dates import date2num
    return date2num(pd.to_datetime(value, unit='ms').to_pydatetime())


def _set_limits(target, name: str, spec: Mapping[str, Any], date: bool) -> None:
    low, high = spec.get('min'), spec.get('max')
    if low is None and high is None:
        return
    horizontal = name == 'x'
    cur = sorted(target.get_xlim() if horizontal else target.get_ylim())
    lo = _limit(low, date) if low is not None else cur[0]
    hi = _limit(high, date) if high is not None else cur[1]
    inverted = target.xaxis_inverted() if horizontal else target.yaxis_inverted()
    pair = (hi, lo) if inverted else (lo, hi)
    (target.set_xlim if horizontal else target.set_ylim)(*pair)


def apply_style(f, ax, rights: Mapping[str, Any], style: Mapping[str, Any], title: str, k: float, base: float, date_axis: bool) -> None:
    from matplotlib.dates import DateFormatter
    from matplotlib.ticker import MultipleLocator
    chart = style.get('chart') or {}
    axes = style.get('axes') or {}
    general = _family(chart.get('font'))
    text_color = chart.get('text_color')

    # график: заголовок
    if any(key in chart for key in ('title_font', 'title_size', 'title_bold', 'title_color', 'title_align', 'font', 'text_color')):
        align = chart.get('title_align', 'left')
        ax.set_title('', loc='left')
        ax.set_title(mpl_text(title), loc=align, pad=14, fontsize=chart.get('title_size', 12 * k),
                     fontweight='bold' if chart.get('title_bold') else 'normal',
                     fontfamily=_family(chart.get('title_font')) or general or ax.title.get_fontfamily(),
                     color=chart.get('title_color') or text_color or ax.title.get_color())

    # оси
    targets = {'x': ax, 'y': ax, **dict(rights)}
    for name, spec in axes.items():
        target = targets.get(name)
        if target is None:
            continue
        axis = target.xaxis if name == 'x' else target.yaxis
        horizontal = name == 'x'
        date = horizontal and date_axis
        if spec.get('scale') == 'log' and not date:
            (target.set_xscale if horizontal else target.set_yscale)('log')
        _set_limits(target, name, spec, date)
        step = spec.get('step')
        if step and not date and spec.get('scale') != 'log':
            lo, hi = sorted(target.get_xlim() if horizontal else target.get_ylim())
            if (hi - lo) / step <= 150:
                axis.set_major_locator(MultipleLocator(step))
        if 'decimals' in spec and not date:
            axis.set_major_formatter(ru_format(int(spec['decimals'])))
        if date and spec.get('date_format') in DATE_FORMATS:
            axis.set_major_formatter(DateFormatter(DATE_FORMATS[spec['date_format']]))
        font = _family(spec.get('font')) or general
        params: dict[str, Any] = {}
        if 'tick_size' in spec:
            params['labelsize'] = spec['tick_size']
        if font:
            params['labelfontfamily'] = font
        color = spec.get('color') or text_color
        if color:
            params['labelcolor'] = color
            axis.label.set_color(color)
        if spec.get('color'):
            params['color'] = spec['color']
            side = 'bottom' if horizontal else 'right' if name != 'y' else 'left'
            target.spines[side].set_color(spec['color'])
        if params:
            axis.set_tick_params(**params)
        if 'title_size' in spec:
            axis.label.set_fontsize(spec['title_size'])
        if font:
            axis.label.set_fontfamily(font)

    # сетка и фон
    mode = chart.get('grid') or ('both' if chart.get('grid_color') else '')
    if mode:
        color = chart.get('grid_color') or '#e4e9ef'
        for axis, on in ((ax.xaxis, mode in ('both', 'v')), (ax.yaxis, mode in ('both', 'h'))):
            axis.grid(True, color=color, linewidth=.7) if on else axis.grid(False)
    if chart.get('background'):
        f.patch.set_facecolor(chart['background'])
        ax.set_facecolor(chart['background'])
    if chart.get('plot_background'):
        ax.set_facecolor(chart['plot_background'])

    # легенда (положение и «скрыть» — в meta.format, см. render.to_plotly)
    legend_font = _family(chart.get('legend_font')) or general
    for legend in f.legends:
        for text in legend.get_texts():
            if 'legend_size' in chart:
                text.set_fontsize(chart['legend_size'])
            if legend_font:
                text.set_fontfamily(legend_font)
            if text_color:
                text.set_color(text_color)
