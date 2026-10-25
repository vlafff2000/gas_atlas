"""Word «ГИС и ГВК»: страница на скважину — рисунок (ГВК а.о., hг эф, Кг ср.взв по пачкам) и таблица изменения ГВК.

По образцу ГГХ (``atlas/ggh_report.py``): А4 альбомная, рисунок по ширине, таблица под ним, подпись с номером.
Данные — таблица пачек «База ГИС» (gis_packs). Весенние замеры отмечены треугольником, как на экране.
"""
from __future__ import annotations

import io
from typing import Any

import pandas as pd

from . import parallel
from .ggh_report import CM, GRAPH_CM, MARGINS, PAGE, _font_size, _run, _table, package
from .modules.gis import METRICS, SPRING

NAMESPACES = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
              'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
              'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
              'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
HEADERS = ['Замеров', 'Первый', 'ГВК первый, м', 'Последний', 'ГВК последний, м', 'Δ, м', 'м/год']


def figure_png(frame: pd.DataFrame, well: str, dpi: int = 200, font: str = 'times') -> bytes:
    """Три графика друг под другом с общей осью дат: линия на пачку, весенние замеры — треугольниками."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import dates as mdates
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from atlas.engine.core.export import LOCK
    from atlas.engine.core.fonts import family_for

    with LOCK, matplotlib.rc_context({'font.family': family_for(font), 'axes.unicode_minus': False}):
        fig = Figure(figsize=(11, 9), facecolor='white')
        FigureCanvasAgg(fig)
        axes = fig.subplots(len(METRICS), 1, sharex=True)
        for ax, key in zip(axes, METRICS):
            column, label, unit, _ = METRICS[key]
            for pack, part in frame.groupby('pack', sort=True):
                part = part[part[column].notna()]
                if part.empty:
                    continue
                line = ax.plot(part['date'], part[column], marker='o', linewidth=1.5, label=str(pack))[0]
                spring = part[part['season'].astype(str) == SPRING]
                ax.plot(spring['date'], spring[column], linestyle='none', marker='^', markersize=7, color=line.get_color())
            ax.set_ylabel(f'{label}, {unit}', fontsize=11)
            ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
        axes[0].legend(fontsize=10, loc='best')
        axes[0].set_title(f'Скважина №{well}', fontsize=14, fontweight='bold')
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=dpi, facecolor='white', bbox_inches='tight')
    return buf.getvalue()


def change_rows(frame: pd.DataFrame) -> list[tuple[str, str, str, list[str]]]:
    """Строка на пачку: замеров, первый и последний замер, изменение ГВК и скорость (м/год)."""
    rows = []
    for pack, part in frame[frame['gvk_abs_m'].notna()].sort_values('date').groupby('pack', sort=True):
        first, last = part.iloc[0], part.iloc[-1]
        years = (last['date'] - first['date']).days / 365.25
        delta = last['gvk_abs_m'] - first['gvk_abs_m']
        rate = f'{delta / years:.2f}' if years > 0 else '—'
        values = [str(len(part)), f'{first["date"]:%m.%Y}', f'{first["gvk_abs_m"]:.2f}', f'{last["date"]:%m.%Y}',
                  f'{last["gvk_abs_m"]:.2f}', f'{delta:+.2f}', rate]
        rows.append(('pack', str(pack), '', values))
    return rows


def well_page(index: int, frame: pd.DataFrame, well: str, png: bytes, number: int, ids: dict) -> tuple[str, bytes, str]:
    """XML страницы, PNG рисунка и имя файла в архиве."""
    width_cm = GRAPH_CM
    w_px, h_px = _png_size(png)
    cx, cy = int(width_cm * CM), int(width_cm * h_px / w_px * CM)
    ids['n'] += 1
    rid, name = f'rIdImg{index}', f'media/gis{index}.png'
    title = f'Рисунок {number} — Скважина №{well}: ГВК, hг эф и Кг ср.взв по пачкам'
    page_break = '<w:pageBreakBefore/>' if index > 1 else ''
    drawing = (f'<w:p><w:pPr>{page_break}<w:keepNext/><w:spacing w:before="0" w:after="120"/><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
               f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
               f'<wp:docPr id="{ids["n"]}" name="График {well}" descr="{title}"/>'
               '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
               f'<pic:nvPicPr><pic:cNvPr id="{ids["n"]}" name="gis{index}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
               f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
               f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
               '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    rows = change_rows(frame)
    tables = []
    if rows:
        size = _font_size(len(HEADERS))
        tables.append(_table(HEADERS, rows, size))
    cap = f'<w:p><w:pPr><w:spacing w:before="120" w:after="480"/><w:jc w:val="center"/></w:pPr>{_run(title)}</w:p>'
    return drawing + ''.join(tables) + cap, png, name


def _png_size(png: bytes) -> tuple[int, int]:
    import struct
    return struct.unpack('>II', png[16:24])


def build_docx(items: list[dict[str, Any]], start: int = 1, dpi: int = 200, font: str = 'times') -> bytes:
    """``items`` — ``{'well', 'frame'}`` по скважинам (порядок сохраняется): frame — строки пачек одной скважины."""
    if not items:
        raise ValueError('Нет скважин для выгрузки: выберите скважины с данными ГИС.')
    ids = {'n': 0}
    body, media, rels = [], [], []
    frames = [item['frame'].sort_values('date').reset_index(drop=True) for item in items]
    # рисунки независимы: рисуем процессами (PXG_WORKERS), страницы собираем подряд
    pngs = parallel.map_figures(figure_png, [(frame, str(item['well']), dpi, font) for frame, item in zip(frames, items)])
    for i, (item, frame, figure) in enumerate(zip(items, frames, pngs), 1):
        well = str(item['well'])
        xml, png, name = well_page(i, frame, well, figure, start + i - 1, ids)
        body.append(xml)
        media.append((name, png))
        rels.append(f'<Relationship Id="rIdImg{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{name}"/>')
    w, h = int(PAGE[0] * 567), int(PAGE[1] * 567)
    mar = {k: int(v * 567) for k, v in MARGINS.items()}
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NAMESPACES}><w:body>' + ''.join(body)
                + f'<w:sectPr><w:pgSz w:w="{w}" w:h="{h}" w:orient="landscape"/><w:pgMar w:top="{mar["top"]}" w:right="{mar["right"]}" '
                  f'w:bottom="{mar["bottom"]}" w:left="{mar["left"]}" w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>')
    return package(document, media, rels)
