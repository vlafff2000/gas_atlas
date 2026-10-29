"""Данные графика Plotly в таблицу: что выгружать вместе с картинкой (XLSX и CSV в архиве, пакете и «Любом графике»)."""
import numpy as np
import pandas as pd

from .export import csv_bytes, decode_arrays, xlsx_bytes

COLUMNS = ['График', 'Ряд', 'X', 'Y', 'Z', 'Подпись']


def _list(value):
    if value is None:return []
    return list(np.asarray(value).tolist()) if not isinstance(value,(list,tuple)) else list(value)


def _text(trace, n):
    t = trace.get('text') or trace.get('hovertext')
    if isinstance(t, (list, tuple)) and len(t) == n:return [None if v is None else str(v) for v in t]
    return [None] * n


def figure_table(fig, title=None):
    """Длинная таблица «график, ряд, X, Y, Z, подпись» по всем видимым рядам; тепловые карты — по ячейкам."""
    data = decode_arrays(fig.to_dict()).get('data', [])
    name = str(title if title is not None else (fig.layout.title.text or ''))
    rows = []
    for trace in data:
        if trace.get('visible') in (False, 'legendonly'):continue
        series = str(trace.get('name') or '')
        z = trace.get('z')
        if z is not None and trace.get('type') in ('heatmap', 'contour', 'surface', 'heatmapgl'):
            xs, ys = _list(trace.get('x')), _list(trace.get('y'))
            for j, line in enumerate(z):
                for i, v in enumerate(line):
                    rows.append((name, series, xs[i] if i < len(xs) else i, ys[j] if j < len(ys) else j, v, None))
            continue
        xs, ys = _list(trace.get('x')), _list(trace.get('y'))
        n = max(len(xs), len(ys))
        if not n:continue
        xs = xs + [None] * (n - len(xs))
        ys = ys + [None] * (n - len(ys))
        rows.extend((name, series, x, y, None, t) for x, y, t in zip(xs, ys, _text(trace, n)))
    frame = pd.DataFrame(rows, columns=COLUMNS)
    for col in ('X', 'Y', 'Z'):
        converted = pd.to_numeric(frame[col], errors='coerce')
        if converted.notna().sum() == frame[col].notna().sum():frame[col] = converted
        elif col == 'X':
            dates = pd.to_datetime(frame[col], errors='coerce', format='ISO8601')
            if dates.notna().sum() == frame[col].notna().sum():frame[col] = dates
    return frame.dropna(axis=1, how='all') if len(frame) else frame


def figure_data_bytes(fig, fmt):
    """XLSX (лист «Данные») или CSV (; и запятая, UTF-8 с BOM) с данными графика."""
    table = figure_table(fig)
    if fmt == 'csv':return csv_bytes(table)
    if fmt == 'xlsx':return xlsx_bytes({'Данные': table})
    raise ValueError('Данные графика: xlsx или csv')
