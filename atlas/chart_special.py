"""Выгрузка графиков с подписями внутри сегментов, выносками, таблицей под графиком и тепловых карт (PNG, PDF, SVG).

Общий экспортёр ``engine/core/export.py`` рисует только ряды Plotly. Эти графики он не передаёт: стопка превращается в группы столбцов,
подписи и выноски теряются. Поэтому такие графики рисует matplotlib напрямую, по тем же правилам, что и экран
(``web/src/ChartView.tsx``, ``HeatView.tsx``): число внутри сегмента, узкий (меньше ``NARROW`` % высоты) — выноска или точка.
"""
from __future__ import annotations

import io
import logging
from typing import Any

import numpy as np

from .contract import Chart

NARROW = 5      # узкий сегмент: число не помещается внутрь (как на экране)
SERIF = ['Times New Roman', 'Liberation Serif', 'DejaVu Serif']


def is_special(chart: Chart) -> bool:
    return chart.heat is not None or any(s.segments is not None for s in chart.series)


def _luma(color: str) -> float:
    c = color.lstrip('#')
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else (0, 0, 0)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _setup():
    import matplotlib
    matplotlib.use('Agg')
    logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)    # нет Times New Roman — берётся Liberation Serif
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': SERIF, 'font.size': 12, 'axes.spines.top': False, 'axes.spines.right': False})
    return plt


def _bytes(fig: Any, fmt: str, dpi: int) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format=fmt, dpi=dpi, bbox_inches='tight')
    return buffer.getvalue()


def figure_file(chart: Chart, fmt: str, dpi: int) -> bytes:
    from .render import group_colors, series_color
    plt = _setup()
    try:
        fig = _heat_figure(plt, chart) if chart.heat is not None else _stack_figure(plt, chart, group_colors(chart), series_color)
        return _bytes(fig, fmt, dpi)
    finally:
        plt.close('all')


def _stack_figure(plt: Any, chart: Chart, palette: dict[str, str], series_color: Any):
    bars = [s for s in chart.series if s.kind == 'bar']
    cats = list(chart.x.categories or dict.fromkeys(str(x) for s in bars for x in s.x))
    table = chart.table
    fig = plt.figure(figsize=(max(7.5, 0.9 * len(cats) + 4), 6.2 + (0.26 * (len(table.rows) + 1) if table else 0)))
    ax = fig.add_axes([0.08, 0.08 + (0.04 * len(table.rows) if table else 0.0), 0.72, 0.8])
    below = np.zeros(len(cats))
    used = [0] * len(cats)
    marks: list[tuple[int, float, str, str]] = []
    colors: list[str] = []
    for s in bars:
        color = (s.look or {}).get('color') or (series_color(s.color) if s.color else palette[s.group or s.name])
        colors.append(color)
        values = np.array([0.0 if v is None else float(v) for v in s.y])
        ax.bar(range(len(cats)), values, bottom=below, width=0.62, color=color, label=s.name, edgecolor='#222', linewidth=0.4)
        for j, (v, text) in enumerate(zip(values, s.segments or [])):
            middle = below[j] + v / 2
            if text and v >= NARROW:
                ax.text(j, middle, text, ha='center', va='center', fontsize=11, color='white' if _luma(color) < 140 else '#111')
            elif text and chart.callouts == 'dot':
                ax.text(j, middle, '●', ha='center', va='center', fontsize=7, color='white' if _luma(color) < 140 else '#111')
            elif text:
                marks.append((j, middle, text, color))
        below += values
    for j, middle, text, color in marks:
        side = 1 if used[j] % 2 == 0 else -1
        used[j] += 1
        ax.annotate(text, (j + side * 0.31, middle), (j + side * 0.5, middle), fontsize=10, ha='center', va='center',
                    bbox={'boxstyle': 'round,pad=0.25', 'fc': 'white', 'ec': color, 'lw': 1.5},
                    arrowprops={'arrowstyle': '-', 'lw': 0.7, 'color': '#888'})
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels([] if table else cats)
    ax.set_xlim(-0.6, len(cats) - 0.4 + 0.2)
    ax.set_ylabel(f'{chart.y.label}, {chart.y.unit}' if chart.y.unit else chart.y.label)
    if chart.y.maximum is not None:
        ax.set_ylim(chart.y.minimum or 0, chart.y.maximum)
    ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left', frameon=False, fontsize=11)
    ax.set_title(chart.title, fontsize=13)
    if table:
        tb = ax.table(cellText=table.cells, rowLabels=table.rows, colLabels=table.columns, loc='bottom', cellLoc='center',
                      bbox=[0, -0.06 * (len(table.rows) + 1) - 0.04, 1, 0.06 * (len(table.rows) + 1)])
        tb.auto_set_font_size(False)
        tb.set_fontsize(9)
        if table.swatches:
            for i, color in enumerate(table.colors or colors):
                tb[i + 1, -1].set_facecolor(color)
                tb[i + 1, -1].get_text().set_color('white' if _luma(color) < 140 else '#111')
    return fig


def _heat_figure(plt: Any, chart: Chart):
    from matplotlib.patches import Rectangle
    h = chart.heat
    z = np.array([[np.nan if v is None else float(v) for v in row] for row in h.values])
    top = h.maximum or float(np.nanmax(z)) if np.isfinite(z).any() else 1.0
    fig, ax = plt.subplots(figsize=(1.3 * len(h.columns) + 3.2, 0.5 * len(h.rows) + 2.2))
    image = ax.imshow(np.ma.masked_invalid(z), cmap='OrRd', vmin=0, vmax=top, aspect='auto')
    ax.set_xticks(range(len(h.columns)))
    ax.set_xticklabels(h.columns)
    ax.set_yticks(range(len(h.rows)))
    ax.set_yticklabels(h.rows)
    ax.spines[:].set_visible(False)
    ax.tick_params(length=0)
    for i, row in enumerate(h.values):
        for j, v in enumerate(row):
            text = h.texts[i][j]
            if v is None:
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, hatch='///', ec='#aaa', lw=0))
                ax.text(j, i, text or h.missing_text, ha='center', va='center', fontsize=9, color='#555')
            elif text:
                ax.text(j, i, text, ha='center', va='center', color='white' if v > top * 0.55 else '#111')
    fig.colorbar(image, ax=ax, label=h.unit)
    ax.set_title(chart.title, fontsize=13)
    return fig


def heat_frame(chart: Chart):
    """Данные тепловой карты для Excel и CSV: строка — ГСП, столбец — сезон."""
    import pandas as pd
    h = chart.heat
    frame = pd.DataFrame(h.values, columns=h.columns)
    frame.insert(0, chart.y.label, h.rows)
    return frame
