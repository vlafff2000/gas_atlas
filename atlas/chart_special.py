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
    return chart.heat is not None or chart.strips is not None or any(s.segments is not None for s in chart.series)


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


def figure_file(chart: Chart, fmt: str, dpi: int, opts: dict[str, Any] | None = None) -> bytes:
    """``opts`` — ручные настройки выгрузки (``atlas/export_any.py``): width_mm, height_mm, font, font_size, legend, table_font_size,
    table_row, table_show, segment_size; без них — прежний вид."""
    from .render import group_colors, series_color
    plt = _setup()
    o = opts or {}
    try:
        if o.get('font') and o['font'] != 'default':
            from atlas.engine.core.fonts import family_for
            plt.rcParams['font.family'] = family_for(o['font'])
        fig = _heat_figure(plt, chart) if chart.heat is not None else _strip_figure(plt, chart) if chart.strips is not None \
            else _stack_figure(plt, chart, group_colors(chart), series_color, o)
        if o.get('width_mm') and o.get('height_mm'):
            fig.set_size_inches(o['width_mm'] / 25.4, o['height_mm'] / 25.4)
        elif o.get('width_mm'):
            w, h = fig.get_size_inches()
            fig.set_size_inches(o['width_mm'] / 25.4, h * o['width_mm'] / 25.4 / w)
        return _bytes(fig, fmt, dpi)
    finally:
        plt.close('all')


def _stack_figure(plt: Any, chart: Chart, palette: dict[str, str], series_color: Any, o: dict[str, Any] | None = None):
    o = o or {}
    base = float(o.get('font_size') or 12)
    tfs = float(o.get('table_font_size') or round(base * 0.75, 1))
    row_k = float(o.get('table_row') or 1.0)
    bars = [s for s in chart.series if s.kind == 'bar']
    cats = list(chart.x.categories or dict.fromkeys(str(x) for s in bars for x in s.x))
    table = None if o.get('table_show') is False else chart.table
    legend = o.get('legend') or 'right'
    fig = plt.figure(figsize=(max(7.5, 0.9 * len(cats) + 4), 6.2 + (0.26 * row_k * (len(table.rows) + 1) if table else 0)))
    ax = fig.add_axes([0.08, 0.08 + (0.04 * row_k * len(table.rows) if table else 0.0), 0.72 if legend == 'right' else 0.9, 0.8 if legend != 'top' else 0.74])
    below = np.zeros(len(cats))
    top = max(1e-9, sum(np.array([0.0 if v is None else float(v) for v in s.y]) for s in bars if s.segments is not None).max()) \
        if any(s.segments is not None for s in bars) else 1.0
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
            if text and v / top >= NARROW / 100:
                ax.text(j, middle, text, ha='center', va='center', fontsize=float(o.get('segment_size') or base - 1), color='white' if _luma(color) < 140 else '#111')
            elif text and chart.callouts == 'dot':
                ax.text(j, middle, '●', ha='center', va='center', fontsize=7, color='white' if _luma(color) < 140 else '#111')
            elif text:
                marks.append((j, middle, text, color))
        below += values
    for s in chart.series:
        if s.kind == 'line':        # кривая поверх столбиков (максимум одновременно работавших скважин за сутки)
            ax.plot(range(len(cats)), [np.nan if v is None else float(v) for v in s.y], color=s.color or '#111827', lw=2.2, marker='D', ms=6,
                    mfc='white', mec=s.color or '#111827', mew=1.8, label=s.name, zorder=5)
    for j, middle, text, color in marks:
        side = 1 if used[j] % 2 == 0 else -1
        used[j] += 1
        ax.annotate(text, (j + side * 0.31, middle), (j + side * 0.5, middle), fontsize=base - 2, ha='center', va='center',
                    bbox={'boxstyle': 'round,pad=0.25', 'fc': 'white', 'ec': color, 'lw': 1.5},
                    arrowprops={'arrowstyle': '-', 'lw': 0.7, 'color': '#888'})
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels([] if table else cats)
    ax.set_xlim(-0.6, len(cats) - 0.4 + 0.2)
    if chart.y.unit == 'скв.':
        from matplotlib.ticker import MaxNLocator
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylabel(f'{chart.y.label}, {chart.y.unit}' if chart.y.unit else chart.y.label, fontsize=base)
    if chart.y.maximum is not None:
        ax.set_ylim(chart.y.minimum or 0, chart.y.maximum)
    from atlas.engine.core.export import sort_legend
    handles, labels = sort_legend(*ax.get_legend_handles_labels())
    if legend == 'right':
        ax.legend(handles, labels, bbox_to_anchor=(1.01, 1), loc='upper left', frameon=False, fontsize=base - 1)
    elif legend == 'top':
        ax.legend(handles, labels, bbox_to_anchor=(0, 1.02), loc='lower left', frameon=False, fontsize=base - 1, ncol=max(1, len(bars)))
    ax.tick_params(labelsize=base - 1)
    ax.set_title(chart.title, fontsize=base + 1, y=1.0 if legend != 'top' else 1.08)
    if table and table.aligned:
        _aligned_table(plt, fig, ax, table, len(cats), tfs, row_k)
    elif table:
        tb = ax.table(cellText=table.cells, rowLabels=table.rows, colLabels=table.columns, loc='bottom', cellLoc='center',
                      bbox=[0, -0.06 * row_k * (len(table.rows) + 1) - 0.04, 1, 0.06 * row_k * (len(table.rows) + 1)])
        tb.auto_set_font_size(False)
        tb.set_fontsize(tfs)
        if table.swatches:
            for i, color in enumerate(table.colors or colors):
                tb[i + 1, -1].set_facecolor(color)
                tb[i + 1, -1].get_text().set_color('white' if _luma(color) < 140 else '#111')
    return fig


def _aligned_table(plt: Any, fig: Any, ax: Any, table: Any, n: int, fs: float = 9, row_k: float = 1.0) -> None:
    """Таблица под графиком: столбцы месяцев точно под столбиками, подписи строк и «Фонд» — левее поля графика."""
    rows = len(table.rows) + 1
    pos = ax.get_position()
    height = 0.04 * row_k * rows
    tab = fig.add_axes([pos.x0, pos.y0 - height - 0.02, pos.width, height], sharex=ax)
    tab.axis('off')
    tab.set_ylim(rows, 0)
    left = ax.get_xlim()[0]
    edge = lambda y: tab.plot([left, ax.get_xlim()[1]], [y, y], color='#888', lw=0.6, clip_on=False)
    for y in range(rows + 1):
        edge(y)
    heads = table.columns
    for k, head in enumerate(heads[1:]):
        tab.text(k, 0.5, head, ha='center', va='center', fontsize=fs, fontweight='bold')
    tab.text(left - 0.05, 0.5, heads[0], ha='right', va='center', fontsize=fs, fontweight='bold', clip_on=False)
    for i, (label, cells) in enumerate(zip(table.rows, table.cells), start=1):
        tab.text(left - 0.55, i + 0.5, label, ha='right', va='center', fontsize=fs, clip_on=False)
        tab.text(left - 0.05, i + 0.5, cells[0], ha='right', va='center', fontsize=fs, fontweight='bold', clip_on=False)
        for k, v in enumerate(cells[1:]):
            tab.text(k, i + 0.5, v, ha='center', va='center', fontsize=fs)


def _strip_figure(plt: Any, chart: Chart):
    """Скважины × сезоны плитками: номер, ряд мелких квадратов (цвет ГСП; серый — нет; штриховка — ревизии не было), число сезонов."""
    from matplotlib.patches import Rectangle
    st = chart.strips
    groups = list(dict.fromkeys(st.groups))
    palette = ['#2a6f97', '#d1495b', '#3a9d5d', '#e0a100', '#7b4fa3', '#e07a1f', '#2b9aa0', '#8c5a3c', '#5b6c8f', '#a3a33a']
    color = {g: st.colors.get(g) or palette[i % len(palette)] for i, g in enumerate(groups)}
    blocks = [(g, [i for i, x in enumerate(st.groups) if x == g]) for g in groups] if st.layout == 'panels' else [('', list(range(len(st.rows))))]
    n, sq, gap = len(st.columns), 0.2, 0.03
    chip_w = 0.7 + n * (sq + gap) + 0.45                 # номер + квадраты + число
    per_row = 9
    lines = sum(-(-len(idx) // per_row) + (1 if name else 0) for name, idx in blocks)
    fig, ax = plt.subplots(figsize=(per_row * chip_w * 0.5 + 0.4, 0.42 * lines + 1.3))
    y = 0.0
    for name, idx in blocks:
        if name:
            ax.text(0, y + 0.35, name, color=color[name], fontsize=12, fontweight='bold', va='center')
            y += 0.8
        for k, i in enumerate(idx):
            x0, y0 = (k % per_row) * (chip_w + 0.15), y + (k // per_row) * 0.8
            ax.add_patch(Rectangle((x0, y0), chip_w, 0.62, fill=False, ec='#b9c4c7', lw=0.8))
            ax.text(x0 + 0.62, y0 + 0.31, st.rows[i].replace('№ ', ''), ha='right', va='center', fontsize=9, fontweight='bold')
            for j, v in enumerate(st.cells[i]):
                xs = x0 + 0.7 + j * (sq + gap)
                if v is None:
                    ax.add_patch(Rectangle((xs, y0 + 0.13), sq, 0.36, fc='#fff4d6', hatch='////', ec='#8a5a00', lw=0.8))
                else:
                    ax.add_patch(Rectangle((xs, y0 + 0.13), sq, 0.36, fc=color[st.groups[i]] if v else '#e4eaec', lw=0))
            ax.text(x0 + chip_w - 0.1, y0 + 0.31, str(st.counts[i]), ha='right', va='center', fontsize=9, color='#555')
        y += -(-len(idx) // per_row) * 0.8 + 0.2
    ax.set_xlim(-0.05, per_row * (chip_w + 0.15))
    ax.set_ylim(y, -0.2)
    ax.axis('off')
    ax.set_title(chart.title, fontsize=13)
    fig.text(0.01, 0.01, 'Квадраты слева направо: ' + ' · '.join(st.columns) + '; число справа — сколько сезонов', fontsize=9, color='#555')
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


def strips_frame(chart: Chart):
    """Данные матрицы для Excel и CSV: строка — скважина, столбец — сезон (1 — в перечне, 0 — нет, пусто — ревизии не было)."""
    import pandas as pd
    st = chart.strips
    frame = pd.DataFrame(st.cells, columns=st.columns, dtype='object')
    frame.insert(0, 'Раз', st.counts)
    frame.insert(0, 'ГСП', st.groups)
    frame.insert(0, 'Скважина', st.rows)
    return frame
