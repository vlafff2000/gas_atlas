"""Выгрузка ГГХ в Word: страница на скважину — график, под ним таблица значений, подпись «Рисунок В.N – Результаты ГГХИ …».

Страница, как в референсе отчёта: А4 альбомная, поля 2 см (снизу 1,5), график по центру шириной 16,5 см (рисунок
Matplotlib: оси, значки и цвета как в скрипте построения), таблица во всю ширину листа с цветными названиями параметров,
подпись Times New Roman 12 пт по центру. Таблица — настоящая таблица Word (правится руками), не картинка.
Если замеров много, таблица делится на две части, а график уменьшается, чтобы страница не растекалась.
Файл пишется «вручную» (zip + XML), как отчёт 5.8 (``atlas/engine/core/documents.py``): новых зависимостей нет.
"""
from __future__ import annotations

import io
import struct
import zipfile
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd

from .modules._ggh import GAS, PARAMS, TICKS, caption, cell, gas_axis, rows_for, well_horizon

COLORS = {key: color for key, (_, color, _) in PARAMS.items()}
# ключ → маркер Matplotlib (как в скрипте: o s ^ v d p, газонасыщенность — звезда)
MARKERS = {'hc': 'o', 'he': 's', 'h2': '^', 'n2': 'v', 'o2': 'd', 'co2': 'p', 'gas': '*'}
SIZES = {'hc': 4, 'he': 4, 'h2': 4, 'n2': 4, 'o2': 4, 'co2': 4, 'gas': 5}
FIG_INCHES = (11.0, 7.0)
CM = 360000                    # EMU в сантиметре
PAGE = (29.7, 21.0)            # А4 альбомная, см
MARGINS = dict(top=2.0, bottom=1.5, left=2.0, right=2.0)
GRAPH_CM = 16.5
GRAPH_CM_SPLIT = 13.0          # график на странице с двумя частями таблицы
SPLIT_AFTER = 28               # больше дат — таблица в две части
FIRST_COLUMN_CM = 3.2


def figure_png(frame: pd.DataFrame, well: str, dpi: int = 200, font: str = 'times', style: dict | None = None) -> bytes:
    """График скважины как в скрипте: слева содержание, %, справа газонасыщенность, по 11 меток на каждой оси.
    ``style`` — настройки выгрузки: ``font_size`` (пт, база 12), ``look`` (``excel`` — палитра Office), общие ``title`` / ``angle`` и
    правила наборов данных ``series`` (``atlas/chart_format.py``): набор — параметр ГГХ или «Газонасыщенность»."""
    import matplotlib
    matplotlib.use('Agg')
    import numpy as np
    from matplotlib import dates as mdates
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import FuncFormatter, FixedLocator
    from atlas.engine.core.export import LOCK
    from atlas.engine.core.fonts import family_for

    style = style or {}
    k = float(style.get('font_size') or 12) / 12
    rules = style.get('series') or []
    from atlas.engine.core.export import XL_PALETTE

    def look(label: str, color: str, index: int) -> dict | None:
        """Цвет, толщина и маркер набора с учётом правил; ``None`` — набор скрыт."""
        out = {'color': XL_PALETTE[index % len(XL_PALETTE)] if style.get('look') == 'excel' else color, 'width': 1.5, 'size': None}
        for rule in rules:
            if rule['match'] in label.lower():
                if rule.get('hide'):
                    return None
                out['color'] = rule.get('color', out['color'])
                out['width'] = rule.get('width', out['width'])
                out['size'] = rule.get('marker', out['size'])
        return out

    frame = frame.sort_values('date')
    dates = mdates.date2num(pd.to_datetime(frame.date).dt.to_pydatetime())
    with LOCK, matplotlib.rc_context({'font.family': family_for(font), 'axes.unicode_minus': False}):
        fig = Figure(figsize=FIG_INCHES, facecolor='white')
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        ax.set_ylabel('Содержание, %', fontsize=14 * k, fontweight='bold')
        ax.set_ylim(0, 100)
        ax.set_yticks(np.linspace(0, 100, TICKS))
        ax.tick_params(axis='both', labelsize=12 * k)
        ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
        for index, (key, (label, color, _)) in enumerate(PARAMS.items()):
            y = pd.to_numeric(frame[key], errors='coerce').to_numpy(dtype=float) if key in frame else np.full(len(frame), np.nan)
            ok = ~np.isnan(y)
            shown = look(label, color, index)
            if ok.any() and shown:
                size = shown['size'] if shown['size'] is not None else SIZES[key]
                ax.plot(dates[ok], y[ok], color=shown['color'], marker=MARKERS[key] if size > 0 else None, markersize=size, linewidth=shown['width'], linestyle='-')
        gas = pd.to_numeric(frame.gas, errors='coerce').to_numpy(dtype=float) if 'gas' in frame else np.full(len(frame), np.nan)
        ok = ~np.isnan(gas)
        shown = look(GAS[1], GAS[2], len(PARAMS))
        if ok.any() and shown:
            ax2 = ax.twinx()
            ax2.set_ylabel('Газонасыщенность, см³/л', fontsize=14 * k, fontweight='bold')
            ax2.tick_params(axis='both', labelsize=12 * k)
            low, high = gas_axis(pd.Series(gas[ok]))
            ax2.set_ylim(low, high)
            ax2.yaxis.set_major_locator(FixedLocator(np.linspace(low, high, TICKS)))
            ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{int(round(v))}' if abs(v) >= 0.5 else '0'))
            size = shown['size'] if shown['size'] is not None else SIZES['gas']
            ax2.plot(dates[ok], gas[ok], color=shown['color'], marker=MARKERS['gas'] if size > 0 else None, markersize=size, linewidth=shown['width'], linestyle='-')
        ax.set_xlabel('Год', fontsize=14 * k, fontweight='bold', labelpad=10)
        first, last = pd.to_datetime(frame.date).min().year, pd.to_datetime(frame.date).max().year
        ticks = [mdates.date2num(pd.Timestamp(year=y, month=1, day=1).to_pydatetime()) for y in range(first, last + 1)]
        ax.set_xticks(ticks)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        angle = float(style['angle']) if style.get('angle') not in (None, 'auto') else 45 if len(ticks) > 10 else 0
        for label in ax.get_xticklabels():
            label.set_rotation(angle)
            label.set_ha('right' if 0 < angle < 90 else 'center')
            label.set_fontsize(12 * k)
        if len(dates) > 1:
            ax.set_xlim(dates[0] - 180, dates[-1] + 180)
        if style.get('title') != 'hide':
            ax.set_title(f'Скважина №{well}', fontsize=16 * k, fontweight='bold', pad=20)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=dpi, facecolor='white', bbox_inches='tight')   # как в скрипте: без пустых полей
    return buf.getvalue()


# ---------- Word ----------
def _run(text: str, size: float = 12, bold: bool = False, color: str = '') -> str:
    props = ('<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="Times New Roman" w:cs="Times New Roman"/>'
             + ('<w:b/>' if bold else '') + (f'<w:color w:val="{color.lstrip("#").upper()}"/>' if color else '')
             + f'<w:sz w:val="{int(size * 2)}"/><w:szCs w:val="{int(size * 2)}"/>')
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _cell(text: str, width: int, size: float, fill: str, bold: bool = False, color: str = '', left: bool = False) -> str:
    align = 'left' if left else 'center'
    return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>'
            f'<w:vAlign w:val="center"/></w:tcPr><w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
            f'<w:jc w:val="{align}"/></w:pPr>{_run(text, size, bold, color)}</w:p></w:tc>')


def _table(headers: list[str], rows: list[tuple[str, str, str, list[str]]], size: float) -> str:
    """Таблица значений: заголовок серый, первый столбец — цвет параметра, чередующиеся строки."""
    usable = int((PAGE[0] - MARGINS['left'] - MARGINS['right']) * 567)
    first = int(FIRST_COLUMN_CM * 567)
    each = (usable - first) // max(1, len(headers))
    grid = f'<w:gridCol w:w="{first}"/>' + f'<w:gridCol w:w="{each}"/>' * len(headers)
    border = ''.join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="333333"/>'
                     for s in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="{first + each * len(headers)}" w:type="dxa"/><w:jc w:val="center"/>'
           f'<w:tblBorders>{border}</w:tblBorders><w:tblLayout w:type="fixed"/>'
           '<w:tblCellMar><w:top w:w="20" w:type="dxa"/><w:left w:w="30" w:type="dxa"/><w:bottom w:w="20" w:type="dxa"/>'
           f'<w:right w:w="30" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
    head = _cell('Параметр', first, size, 'E8E8E8', True) + ''.join(_cell(h, each, size, 'E8E8E8', True) for h in headers)
    out.append(f'<w:tr><w:trPr><w:cantSplit/></w:trPr>{head}</w:tr>')
    for i, (key, label, color, values) in enumerate(rows):
        fill = 'FFFFFF' if i % 2 == 0 else 'F9F9F9'
        body = _cell(label, first, size, 'F0F0F0', True, color, True) + ''.join(_cell(v, each, size, fill) for v in values)
        out.append(f'<w:tr><w:trPr><w:cantSplit/></w:trPr>{body}</w:tr>')
    out.append('</w:tbl>')
    return ''.join(out)


def _chunks(n: int) -> list[range]:
    if n <= SPLIT_AFTER:
        return [range(n)]
    half = (n + 1) // 2
    return [range(0, half), range(half, n)]


def _font_size(columns: int) -> float:
    return 9 if columns <= 12 else 8 if columns <= 18 else 7 if columns <= 24 else 6.5


def well_page(index: int, frame: pd.DataFrame, well: str, horizon: str, png: bytes, number: int, section: str, ids: dict) -> tuple[str, bytes, str]:
    """XML одной страницы, PNG графика и его имя в архиве. ``ids`` — счётчик идентификаторов рисунков документа."""
    frame = frame.sort_values('date').reset_index(drop=True)
    headers = [pd.Timestamp(v).strftime('%m.%Y') for v in frame.date]
    rows = [(key, label, color, [cell(key, v) for v in values]) for key, label, color, values in rows_for(frame)]
    parts = _chunks(len(headers))
    width_cm = GRAPH_CM if len(parts) == 1 else GRAPH_CM_SPLIT
    w_px, h_px = struct.unpack('>II', png[16:24])      # размеры PNG: после обрезки полей пропорции не равны размеру фигуры
    ratio = h_px / w_px
    cx, cy = int(width_cm * CM), int(width_cm * ratio * CM)
    ids['n'] += 1
    rid, name = f'rIdImg{index}', f'media/ggh{index}.png'
    title = caption(number, well, horizon, section)
    paragraph_break = '<w:pageBreakBefore/>' if index > 1 else ''
    drawing = (f'<w:p><w:pPr>{paragraph_break}<w:keepNext/><w:spacing w:before="0" w:after="120"/><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
               f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
               f'<wp:docPr id="{ids["n"]}" name="График {escape(well)}" descr="{escape(title, {chr(34): "&quot;"})}"/>'
               '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
               f'<pic:nvPicPr><pic:cNvPr id="{ids["n"]}" name="ggh{index}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
               f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
               f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
               '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    tables = []
    for k, part in enumerate(parts):
        cols = list(part)
        size = _font_size(len(cols))
        tables.append(_table([headers[i] for i in cols], [(key, label, color, [values[i] for i in cols]) for key, label, color, values in rows], size))
        if k < len(parts) - 1:
            tables.append('<w:p><w:pPr><w:spacing w:before="0" w:after="60"/></w:pPr></w:p>')
    cap = (f'<w:p><w:pPr><w:spacing w:before="120" w:after="480"/><w:jc w:val="center"/></w:pPr>{_run(title)}</w:p>')
    return drawing + ''.join(tables) + cap, png, name


def build_docx(items: list[dict[str, Any]], start: int = 1, section: str = 'В', dpi: int = 200, font: str = 'times',
               progress=None, style: dict | None = None) -> bytes:
    """``items`` — ``{'well', 'frame'}`` по скважинам (порядок сохраняется); горизонт берётся из данных скважины."""
    if not items:
        raise ValueError('Нет скважин для выгрузки: выберите скважины с данными ГГХ.')
    ids = {'n': 0}
    body, media, rels = [], [], []
    for i, item in enumerate(items, 1):
        frame, well = item['frame'], str(item['well'])
        horizon = item.get('horizon') or well_horizon(frame)
        xml, png, name = well_page(i, frame, well, horizon, figure_png(frame, well, dpi, font, style), start + i - 1, section, ids)
        body.append(xml)
        media.append((name, png))
        rels.append(f'<Relationship Id="rIdImg{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{name}"/>')
        if progress:
            progress(i / len(items))
    namespaces = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                  'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                  'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
                  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                  'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
    w, h = int(PAGE[0] * 567), int(PAGE[1] * 567)
    mar = {k: int(v * 567) for k, v in MARGINS.items()}
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {namespaces}><w:body>' + ''.join(body)
                + f'<w:sectPr><w:pgSz w:w="{w}" w:h="{h}" w:orient="landscape"/><w:pgMar w:top="{mar["top"]}" w:right="{mar["right"]}" '
                  f'w:bottom="{mar["bottom"]}" w:left="{mar["left"]}" w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml', document)
        z.writestr('word/styles.xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="Times New Roman" w:cs="Times New Roman"/>'
                   '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="ru-RU"/></w:rPr></w:rPrDefault>'
                   '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
                   '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style></w:styles>')
        z.writestr('word/_rels/document.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + ''.join(rels) + '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        for name, png in media:
            z.writestr('word/' + name, png)
    return buf.getvalue()
