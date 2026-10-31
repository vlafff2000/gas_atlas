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

LINESTYLES = {'solid': '-', 'dash': '--', 'dot': ':', 'dashdot': '-.', 'longdash': (0, (8, 3))}
UNIT_DIVISOR = {'thousands': 1e3, 'millions': 1e6, 'billions': 1e9}
UNIT_MARK = {'thousands': '×10³', 'millions': '×10⁶', 'billions': '×10⁹'}
DATE_FORMATS = {'dd.MM.yyyy': '%d.%m.%Y', 'MM.yyyy': '%m.%Y', 'yyyy': '%Y', 'dd.MM': '%d.%m'}


def _family(key: Any):
    if not key:
        return None
    from .fonts import family_for
    return family_for(key)


TICK_DIRECTION = {'out': {'direction': 'out', 'length': 3.5}, 'in': {'direction': 'in', 'length': 3.5},
                  'cross': {'direction': 'inout', 'length': 6}, 'none': {'length': 0}}


def ru_format(decimals: int, divisor: float = 1.0):
    """Число по-русски: пробел между тысячами, запятая в дроби."""
    from matplotlib.ticker import FuncFormatter
    return FuncFormatter(lambda v, _: f'{v / divisor:,.{decimals}f}'.replace(',', ' ').replace('.', ','))


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
    from matplotlib.ticker import AutoMinorLocator, MultipleLocator, NullLocator
    chart = style.get('chart') or {}
    axes = style.get('axes') or {}
    general = _family(chart.get('font'))
    text_color = chart.get('text_color')

    # график: заголовок
    if any(key in chart for key in ('title_font', 'title_size', 'title_bold', 'title_color', 'title_align', 'font', 'text_color')):
        align = chart.get('title_align', 'left')
        for place in ('left', 'center', 'right'):        # у matplotlib три независимых заголовка: старый стирать, иначе названия двоятся
            ax.set_title('', loc=place)
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
        divisor = UNIT_DIVISOR.get(spec.get('units'), 1.0) if not date else 1.0
        if ('decimals' in spec or divisor != 1.0) and not date and spec.get('scale') != 'log':
            axis.set_major_formatter(ru_format(int(spec['decimals']) if 'decimals' in spec else 0 if divisor == 1.0 else 1, divisor))
        if divisor != 1.0:                      # единицы отображения: к названию оси добавляется ×10ⁿ
            label = axis.label.get_text()
            axis.label.set_text((label + ', ' if label else '') + UNIT_MARK[spec['units']])
        minor_step = spec.get('minor_step')
        if minor_step and not date and spec.get('scale') != 'log':
            lo, hi = sorted(target.get_xlim() if horizontal else target.get_ylim())
            if (hi - lo) / minor_step <= 600:
                axis.set_minor_locator(MultipleLocator(minor_step))
        side = 'bottom' if horizontal else 'right' if name != 'y' else 'left'
        if spec.get('cross') is not None and not date and spec.get('scale') != 'log':      # ось пересекает соседнюю в этом значении
            target.spines[side if horizontal or name == 'y' else 'right'].set_position(('data', spec['cross']))
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
            target.spines[side].set_color(spec['color'])
        for key, which in (('ticks', 'major'), ('minor_ticks', 'minor')):      # деления: наружу, внутрь, через ось, нет
            mark = spec.get(key)
            if mark:
                if which == 'minor' and mark != 'none' and isinstance(axis.get_minor_locator(), NullLocator) and axis.get_scale() == 'linear' and not date:
                    axis.set_minor_locator(AutoMinorLocator())      # дополнительных делений нет, пока ось их не получила
                axis.set_tick_params(which=which, **TICK_DIRECTION[mark])
        if spec.get('line') is not None:
            target.spines[side].set_visible(bool(spec['line']))
        if spec.get('line_color'):
            target.spines[side].set_color(spec['line_color'])
        if spec.get('line_width'):
            target.spines[side].set_linewidth(spec['line_width'])
        if spec.get('label_rotate'):
            params['labelrotation'] = spec['label_rotate']
        if params:
            axis.set_tick_params(**params)
        if spec.get('tick_bold') or spec.get('tick_italic'):
            for tick in axis.get_ticklabels():
                tick.set_fontweight('bold' if spec.get('tick_bold') else 'normal')
                tick.set_fontstyle('italic' if spec.get('tick_italic') else 'normal')
        if spec.get('title_place') == 'end' and not horizontal:      # название над осью, горизонтально (как на экране)
            axis.label.set_rotation(0)
            axis.label.set_horizontalalignment('left' if name == 'y' else 'right')
            axis.set_label_coords(-0.02 if name == 'y' else 1.02, 1.04)
        elif spec.get('title_place') == 'end':
            axis.set_label_coords(1.0, -0.08)
            axis.label.set_horizontalalignment('right')
        if 'title_size' in spec:
            axis.label.set_fontsize(spec['title_size'])
        if font:
            axis.label.set_fontfamily(font)
        if spec.get('title_bold'):
            axis.label.set_fontweight('bold')
        if spec.get('title_italic'):
            axis.label.set_fontstyle('italic')

    # сетка и фон
    mode = chart.get('grid') or ('both' if chart.get('grid_color') or chart.get('grid_width') else '')
    if mode:
        color = chart.get('grid_color') or '#e4e9ef'
        for axis, on in ((ax.xaxis, mode in ('both', 'v')), (ax.yaxis, mode in ('both', 'h'))):
            axis.grid(True, color=color, linewidth=chart.get('grid_width', .7), linestyle=LINESTYLES.get(chart.get('grid_dash'), '-')) if on else axis.grid(False)
    # доп. линии: между основными делениями; «Нет» у сетки убирает и их. Без доп. делений у осей — автоматические
    minor = chart.get('minor_grid')
    tuned = 'minor_grid_color' in chart or 'minor_grid_width' in chart or 'minor_grid_dash' in chart
    if minor == 'hide' or mode == 'none':
        ax.grid(False, which='minor')
    elif minor == 'show' or tuned:
        for axis, on in ((ax.xaxis, mode in ('', 'both', 'v')), (ax.yaxis, mode in ('', 'both', 'h'))):
            if minor == 'show' and isinstance(axis.get_minor_locator(), NullLocator) and axis.get_scale() == 'linear' and not (axis is ax.xaxis and date_axis):
                axis.set_minor_locator(AutoMinorLocator())
            axis.grid(on, which='minor', color=chart.get('minor_grid_color') or '#f0f2f5', linewidth=chart.get('minor_grid_width', .5),
                      linestyle=LINESTYLES.get(chart.get('minor_grid_dash'), '-'))
    if chart.get('background'):
        f.patch.set_facecolor(chart['background'])
        ax.set_facecolor(chart['background'])
    if chart.get('plot_background'):
        ax.set_facecolor(chart['plot_background'])

    if chart.get('border_color') or chart.get('border_width'):      # рамка всего рисунка
        f.patch.set_edgecolor(chart.get('border_color') or '#888888')
        f.patch.set_linewidth(chart.get('border_width', 1) * 1.5)
    if chart.get('plot_border_color') or chart.get('plot_border_width'):      # рамка области построения: все четыре стороны
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_edgecolor(chart.get('plot_border_color') or '#888888')
            spine.set_linewidth(chart.get('plot_border_width', 1))
    if chart.get('subtitle'):
        ax.annotate(mpl_text(chart['subtitle']), (0, 1), xycoords='axes fraction', xytext=(0, 2), textcoords='offset points', va='bottom',
                    fontsize=chart.get('subtitle_size', 9 * k), color=text_color or '#667085', fontfamily=general)

    # легенда (положение и «скрыть» — в meta.format, см. render.to_plotly)
    legend_font = _family(chart.get('legend_font')) or general
    for legend in f.legends:
        if chart.get('legend_border') or chart.get('legend_background'):
            legend.set_frame_on(True)
            frame = legend.get_frame()
            frame.set_edgecolor('#9aa4b2' if chart.get('legend_border') else 'none')
            frame.set_facecolor(chart.get('legend_background') or 'white')
        for text in legend.get_texts():
            if 'legend_size' in chart:
                text.set_fontsize(chart['legend_size'])
            if legend_font:
                text.set_fontfamily(legend_font)
            if text_color:
                text.set_color(text_color)
