"""Единый экспорт результата любого модуля.

Графики: ``Chart`` → фигура Plotly → ``app.core.export.figure_bytes`` (тот же статический рендер
через Matplotlib, что в 5.8: SVG / PDF / PNG, 300–1200 DPI, без браузера и сети).
Таблицы: ``Table`` → XLSX с подписями столбцов, как на экране.
"""
from __future__ import annotations

import pandas as pd

from app.core.config import COLORS
from app.core.export import csv_bytes, figure_bytes, safe_name, xlsx_bytes

from .contract import Chart, Table

SYMBOLS = {'circle': 'circle', 'square': 'square', 'diamond': 'diamond', 'triangle': 'triangle-up'}
FORMATS = {'svg': 'image/svg+xml', 'pdf': 'application/pdf', 'png': 'image/png'}
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def axis_title(label: str, unit: str) -> str:
    return f'{label}, {unit}' if unit else label


# Палитра графиков Атласа 6 (web/src/chartTheme.ts): модули отдают цвета 5.8, выгрузка заменяет их по номеру,
# как экран, — цвета серий в файле совпадают с тем, что видно в окне.
PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#8a5a14']
LEGACY = {old.lower(): new for old, new in zip(COLORS, PALETTE)}


def series_color(color: str) -> str:
    return LEGACY.get(color.lower(), color)


def group_colors(chart: Chart) -> dict[str, str]:
    groups = list(dict.fromkeys(s.group or s.name for s in chart.series))
    return {g: PALETTE[i % len(PALETTE)] for i, g in enumerate(groups)}


def to_plotly(chart: Chart):
    import plotly.graph_objects as go
    palette = group_colors(chart)
    fig = go.Figure()
    for s in chart.series:
        color = series_color(s.color) if s.color else palette[s.group or s.name]
        if s.kind == 'box':
            # Пять чисел ящика как значения: квартили по ним совпадают, усы — крайние значения в пределах 1,5 IQR.
            first = True
            for category, stats in zip(s.x, s.y):
                if stats is None:
                    continue
                fig.add_trace(go.Box(x=[str(category)] * len(stats), y=list(stats), name=s.name,
                                     showlegend=s.legend and first, marker_color=color, boxpoints=False))
                first = False
        elif s.kind == 'bar':
            fig.add_trace(go.Bar(x=[str(v) for v in s.x], y=list(s.y), name=s.name, showlegend=s.legend,
                                 marker_color=color))
        elif s.kind == 'line':
            dash = s.dash or ('dash' if s.dashed else 'solid')
            extra = {}
            if s.markers:
                extra['marker'] = {'color': 'white' if s.hollow else color, 'symbol': SYMBOLS[s.symbol], 'size': 6,
                                   'line': {'color': color, 'width': 1.8 if s.hollow else 0}}
            fig.add_trace(go.Scatter(x=list(s.x), y=list(s.y), mode='lines+markers' if s.markers else 'lines',
                                     name=s.name, showlegend=s.legend, yaxis='y2' if s.axis == 'y2' else 'y',
                                     connectgaps=False, line={'color': color, 'dash': dash, 'width': s.width or 2},
                                     **extra))
        else:
            symbol = SYMBOLS[s.symbol] + ('-open' if s.hollow else '')
            fig.add_trace(go.Scatter(x=list(s.x), y=list(s.y), mode='markers', name=s.name, showlegend=s.legend,
                                     marker={'color': color, 'symbol': symbol, 'size': 9,
                                             'opacity': s.opacity,
                                             'line': {'color': color, 'width': 2 if s.hollow else 0}}))
    module = chart.id.split('-', 1)[0]
    fig.update_layout(title={'text': chart.title}, meta={'module': module}, barmode='group')
    axes = [(fig.layout.xaxis, chart.x), (fig.layout.yaxis, chart.y)]
    if chart.y2 is not None:
        fig.update_layout(yaxis2={'overlaying': 'y', 'side': 'right', 'showgrid': False})
        axes.append((fig.layout.yaxis2, chart.y2))
    for axis, spec in axes:
        axis.title = {'text': axis_title(spec.label, spec.unit)}
        axis.type = {'time': 'date', 'log': 'log', 'category': 'category'}.get(spec.scale, 'linear')
        if spec.scale == 'category' and spec.categories:
            axis.categoryorder = 'array'
            axis.categoryarray = list(spec.categories)
        if spec.from_zero and spec.scale != 'category':
            axis.rangemode = 'tozero'
        if spec.step and spec.scale in ('value', 'log'):
            axis.dtick = spec.step
        if spec.minimum is not None and spec.maximum is not None and spec.scale == 'value':
            axis.range = [spec.minimum, spec.maximum]
        if spec.inverse:
            axis.autorange = 'reversed'
    return fig


def chart_file(chart: Chart, fmt: str, dpi: int) -> tuple[bytes, str, str]:
    if fmt not in FORMATS:
        raise ValueError('Формат графика: svg, pdf или png')
    return figure_bytes(to_plotly(chart), fmt, dpi), f'{safe_name(chart.title)}.{fmt}', FORMATS[fmt]


def table_frame(table: Table) -> pd.DataFrame:
    keys = [c.key for c in table.columns]
    return table.frame[keys].rename(columns={c.key: axis_title(c.label, c.unit) for c in table.columns})


def tables_file(tables: list[Table], name: str) -> tuple[bytes, str, str]:
    content = xlsx_bytes({t.title: table_frame(t) for t in tables})
    return content, f'{safe_name(name)}.xlsx', XLSX


def table_csv(table: Table) -> tuple[bytes, str, str]:
    """CSV как в 5.8: разделитель «;», запятая в дробях, UTF-8 с BOM — открывается в Excel."""
    return csv_bytes(table_frame(table)), f'{safe_name(table.title)}.csv', 'text/csv; charset=utf-8'
