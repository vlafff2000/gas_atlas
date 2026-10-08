"""Выгрузка графиков в Word с настраиваемым макетом и предпросмотром страниц.

Что делает вместо ``atlas.engine.core.documents.report_docx`` (5.8 остаётся как есть):
 * график строится сразу в размер ячейки страницы, а не сжимается картинкой: подписи осей и легенда читаются;
 * лист — книжный или альбомный, формат A5…A3, любые поля, 1–3 колонки, заданное число графиков на листе;
 * подпись — настоящая подпись Word («Название объекта», поле SEQ «Рисунок»): ссылки «Вставка → Перекрёстная ссылка»,
   «Список рисунков», переход по Ctrl+щелчок; по желанию список рисунков с гиперссылками в начале документа;
 * ``preview_page`` рисует страницу так, как её уложит ``build_docx``: тот же расчёт размеров и разбивки на листы.
Файл пишется вручную (zip + XML), новых зависимостей нет.
"""
from __future__ import annotations

import io
import math
import struct
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

PAPERS = {'A4': (210.0, 297.0), 'A3': (297.0, 420.0), 'A5': (148.0, 210.0), 'Letter': (215.9, 279.4)}
FONTS = ('Times New Roman', 'Arial', 'Calibri', 'Cambria', 'Verdana', 'Tahoma', 'Georgia')
ALIGNS = {'center': 'center', 'left': 'left', 'right': 'right', 'justify': 'both'}
DPIS = (150, 200, 250, 300, 600)
PT_MM = 25.4 / 72
NUMBER_MARK = '\x00'           # на этом месте в подписи стоит поле SEQ


class LayoutError(ValueError):
    pass


@dataclass
class Layout:
    orientation: str = 'portrait'
    paper: str = 'A4'
    margin_top: float = 20.0
    margin_bottom: float = 20.0
    margin_left: float = 25.0
    margin_right: float = 15.0
    columns: int = 1
    gap: float = 4.0                 # промежуток между колонками, мм
    per_page: int = 0                # 0 — столько, сколько поместится
    width_mode: str = 'fill'         # fill — на всю ширину ячейки; mm — width_mm
    width_mm: float = 160.0
    height_mm: float = 0.0           # 0 — по пропорциям графика
    dpi: int = 300
    compress: bool = False
    caption_pos: str = 'below'
    caption_mode: str = 'field'      # field — поле SEQ; text — обычный текст
    caption_font: str = 'Times New Roman'
    caption_size: float = 12.0
    caption_bold: bool = False
    caption_italic: bool = False
    caption_align: str = 'center'
    caption_gap: float = 2.0         # между графиком и подписью, мм
    row_gap: float = 6.0             # между рядами графиков, мм
    borders: str = 'none'
    frame: bool = False
    title: bool = False
    title_text: str = ''
    list_of_figures: bool = False
    list_title: str = 'Список рисунков'
    page_numbers: bool = False
    merge: bool = False              # все модули в одном документе

    # --- геометрия, мм ---
    def page(self) -> Tuple[float, float]:
        w, h = PAPERS[self.paper]
        return (h, w) if self.orientation == 'landscape' else (w, h)

    def content(self) -> Tuple[float, float]:
        w, h = self.page()
        return w - self.margin_left - self.margin_right, h - self.margin_top - self.margin_bottom

    def cell(self) -> float:
        """Ширина места под график в ячейке."""
        w, _ = self.content()
        return w / self.columns - (self.gap if self.columns > 1 else 0)

    def image_width(self) -> float:
        return self.cell() if self.width_mode == 'fill' else min(self.width_mm, self.cell())

    def rows_per_page(self) -> int:
        return max(1, math.ceil(self.per_page / self.columns)) if self.per_page else 1

    def max_image_height(self, caption_h: float) -> float:
        """Выше этого график на листе не поместится: растягивать его нельзя, значит, строится ниже."""
        _, h = self.content()
        rows = self.rows_per_page()
        return max(30.0, (h - rows * (caption_h + self.row_gap)) / rows)


def _num(form: Mapping[str, Any], name: str, default: float, low: float, high: float, label: str) -> float:
    raw = form.get('word_' + name, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise LayoutError('%s: нужно число' % label) from None
    if not low <= value <= high:
        raise LayoutError('%s: от %g до %g' % (label, low, high))
    return value


def _choice(form: Mapping[str, Any], name: str, default: str, allowed, label: str) -> str:
    value = form.get('word_' + name, default)
    if value not in allowed:
        raise LayoutError('%s: допустимо %s' % (label, ', '.join(map(str, allowed))))
    return value


def layout_from(form: Mapping[str, Any]) -> Layout:
    """Поля формы ``word_*`` → проверенный макет. Ошибка — понятное сообщение до построения графиков."""
    d = Layout()
    f = form
    out = Layout(
        orientation=_choice(f, 'orientation', d.orientation, ('portrait', 'landscape'), 'Ориентация листа'),
        paper=_choice(f, 'paper', d.paper, tuple(PAPERS), 'Формат листа'),
        margin_top=_num(f, 'margin_top', d.margin_top, 0, 80, 'Поле сверху, мм'),
        margin_bottom=_num(f, 'margin_bottom', d.margin_bottom, 0, 80, 'Поле снизу, мм'),
        margin_left=_num(f, 'margin_left', d.margin_left, 0, 80, 'Поле слева, мм'),
        margin_right=_num(f, 'margin_right', d.margin_right, 0, 80, 'Поле справа, мм'),
        columns=int(_num(f, 'columns', d.columns, 1, 3, 'Колонок')),
        gap=_num(f, 'gap', d.gap, 0, 30, 'Промежуток между колонками, мм'),
        per_page=int(_num(f, 'per_page', d.per_page, 0, 24, 'Графиков на листе')),
        width_mode=_choice(f, 'width_mode', d.width_mode, ('fill', 'mm'), 'Ширина графика'),
        width_mm=_num(f, 'width_mm', d.width_mm, 40, 400, 'Ширина графика, мм'),
        height_mm=_num(f, 'height_mm', d.height_mm, 0, 400, 'Высота графика, мм'),
        dpi=int(_choice(f, 'dpi', d.dpi, DPIS, 'Разрешение, DPI')),
        compress=bool(f.get('word_compress', d.compress)),
        caption_pos=_choice(f, 'caption_pos', d.caption_pos, ('below', 'above'), 'Положение подписи'),
        caption_mode=_choice(f, 'caption_mode', d.caption_mode, ('field', 'text'), 'Вид подписи'),
        caption_font=_choice(f, 'caption_font', d.caption_font, FONTS, 'Шрифт подписи'),
        caption_size=_num(f, 'caption_size', d.caption_size, 6, 28, 'Размер подписи, пт'),
        caption_bold=bool(f.get('word_caption_bold', d.caption_bold)),
        caption_italic=bool(f.get('word_caption_italic', d.caption_italic)),
        caption_align=_choice(f, 'caption_align', d.caption_align, tuple(ALIGNS), 'Выравнивание подписи'),
        caption_gap=_num(f, 'caption_gap', d.caption_gap, 0, 30, 'Отступ подписи, мм'),
        row_gap=_num(f, 'row_gap', d.row_gap, 0, 60, 'Отступ между рядами, мм'),
        borders=_choice(f, 'borders', d.borders, ('none', 'thin'), 'Линии между графиками'),
        frame=bool(f.get('word_frame', d.frame)),
        title=bool(f.get('word_title', d.title)),
        title_text=str(f.get('word_title_text', d.title_text))[:200],
        list_of_figures=bool(f.get('word_list_of_figures', d.list_of_figures)),
        list_title=str(f.get('word_list_title', d.list_title))[:100] or d.list_title,
        page_numbers=bool(f.get('word_page_numbers', d.page_numbers)),
        merge=bool(f.get('word_merge', d.merge)),
    )
    content_w, content_h = out.content()
    if content_w < 60 or content_h < 60:
        raise LayoutError('Поля слишком большие: на листе не остаётся места под график')
    if out.cell() < 30:
        raise LayoutError('Колонки слишком узкие: уменьшите число колонок, промежуток или поля')
    return out


# ---------- подписи ----------

def caption_split(text_with_mark: str) -> Tuple[str, Optional[str], str]:
    """«Рисунок 1.\\x003 - …» → («Рисунок 1.», …, « - …»); без метки номера — весь текст целиком."""
    if NUMBER_MARK not in text_with_mark:
        return text_with_mark, None, ''
    before, after = text_with_mark.split(NUMBER_MARK, 1)
    return before, '', after


@dataclass
class Item:
    name: str
    before: str                      # текст подписи до номера
    number: Optional[int]            # номер рисунка (поле SEQ), None — подпись без номера
    after: str
    png: bytes = b''
    w: float = 0.0                   # размер на листе, мм
    h: float = 0.0
    module: str = ''

    @property
    def text(self) -> str:
        return self.before + ('' if self.number is None else str(self.number)) + self.after


def caption_height(layout: Layout, text: str, width: float) -> float:
    """Высота подписи в мм: число строк по ширине ячейки (запас на среднюю ширину знака) и отступ от графика."""
    per_line = max(1, int(width / (layout.caption_size * 0.5 * PT_MM * (1.07 if layout.caption_bold else 1.0))))
    lines = max(1, math.ceil(len(text) / per_line))
    return lines * layout.caption_size * 1.2 * PT_MM + layout.caption_gap


def fit(layout: Layout, aspect: float, caption_h: float) -> Tuple[float, float]:
    """Размер графика на листе (мм) по пропорциям ``высота/ширина``: ширина по макету, высота не больше, чем помещается."""
    w = layout.image_width()
    h = w * aspect
    limit = layout.max_image_height(caption_h)
    if h > limit:
        h = limit
        w = h / aspect
    return w, h


def render_png(figure, layout: Layout, caption_h: float, font: str = 'default', font_size=None, look: str = 'default') -> Tuple[bytes, float, float]:
    """PNG графика, построенный сразу в размер на листе (без сжатия картинки), и этот размер в мм."""
    from atlas.engine.core.export import figure_bytes
    inner = layout.image_width()
    limit = layout.max_image_height(caption_h)
    draw_w = min(300.0, max(80.0, inner))
    scale = inner / draw_w                                        # <1 при очень узкой колонке: лишь пропорционально уменьшаем
    want = min(layout.height_mm, limit / scale) if layout.height_mm else None
    png = figure_bytes(figure, 'png', layout.dpi, int(round(draw_w)), int(round(want)) if want else None, font=font, font_size=font_size, look=look)
    w_px, h_px = struct.unpack('>II', png[16:24])
    h = inner * h_px / w_px
    if h > limit:                                                 # слишком высокий: строим ниже, а не сжимаем
        png = figure_bytes(figure, 'png', layout.dpi, int(round(draw_w)), max(30, int(limit / scale)), font=font, font_size=font_size, look=look)
        w_px, h_px = struct.unpack('>II', png[16:24])
        h = inner * h_px / w_px
    w = inner
    if layout.compress:
        from .api_export import optimized_png
        png = optimized_png(png)
    return png, w, h


# ---------- разбивка на листы ----------

def row_height(layout: Layout, row: Sequence[Item]) -> float:
    cell = layout.cell()
    return max(it.h + caption_height(layout, it.text, cell) for it in row) + layout.row_gap


def paginate(layout: Layout, items: Sequence[Item]) -> List[List[List[int]]]:
    """Листы → ряды → индексы графиков. Заданное число на листе — точно; иначе ряды набираются по высоте (оценка)."""
    c = layout.columns
    rows = [list(range(k, min(k + c, len(items)))) for k in range(0, len(items), c)]
    if layout.per_page:
        step = layout.rows_per_page()
        return [rows[k:k + step] for k in range(0, len(rows), step)]
    pages: List[List[List[int]]] = []
    free = -1.0
    for r in rows:
        need = row_height(layout, [items[i] for i in r])
        if not pages or need > free:
            pages.append([])
            free = layout.content()[1]
        pages[-1].append(r)
        free -= need
    return pages


# ---------- Word ----------

def twips(mm: float) -> int:
    return int(round(mm * 56.6929))


def emu(mm: float) -> int:
    return int(round(mm * 36000))


def _text(value: str) -> str:
    return escape(str(value))


def _run(text: str) -> str:
    return '<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % _text(text) if text else ''


def _field(instruction: str, cached: str) -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> %s </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>%s</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
            % (instruction, _text(cached)))


class Builder:
    """Собирает XML документа: ``add_item`` на каждый график, ``finish`` — готовый zip."""

    def __init__(self, layout: Layout):
        self.l = layout
        self.body: List[str] = []
        self.media: List[Tuple[str, bytes]] = []
        self.rels: List[str] = []
        self.bookmarks: List[Tuple[str, str, int]] = []     # имя закладки, подпись, лист
        self.n = 0

    # --- части ---
    def caption_p(self, item: Item, index: int, keep_next: bool, page_break: bool = False) -> str:
        l = self.l
        name = '_Ref%09d' % (700000000 + index)
        props = '<w:pStyle w:val="Caption"/>'
        if keep_next:
            props += '<w:keepNext/>'
        if page_break:
            props += '<w:pageBreakBefore/>'
        above = l.caption_pos == 'above'
        props += '<w:spacing w:before="%d" w:after="%d"/>' % (0 if above else twips(l.caption_gap), twips(l.caption_gap) if above else 0)
        props += '<w:jc w:val="%s"/>' % ALIGNS[l.caption_align]
        label = _run(item.before)
        if item.number is not None:
            label += (_field('SEQ Рисунок \\* ARABIC', str(item.number)) if l.caption_mode == 'field' else _run(str(item.number)))
        mark = '<w:bookmarkStart w:id="%d" w:name="%s"/>%s<w:bookmarkEnd w:id="%d"/>' % (index, name, label, index)
        return '<w:p><w:pPr>%s</w:pPr>%s%s</w:p>' % (props, mark, _run(item.after))

    def picture_p(self, item: Item, index: int, keep_next: bool, page_break: bool = False) -> str:
        l = self.l
        self.n += 1
        rid, member = 'rIdImg%d' % index, 'media/chart%d.png' % index
        self.media.append((member, item.png))
        self.rels.append('<Relationship Id="%s" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                         'Target="%s"/>' % (rid, member))
        cx, cy = emu(item.w), emu(item.h)
        line = ('<a:ln w="6350"><a:solidFill><a:srgbClr val="999999"/></a:solidFill></a:ln>' if l.frame else '')
        props = ('<w:keepNext/>' if keep_next else '') + ('<w:pageBreakBefore/>' if page_break else '')
        return ('<w:p><w:pPr>%s<w:spacing w:before="0" w:after="0"/><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
                '<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="%d" cy="%d"/>'
                '<wp:docPr id="%d" name="Chart %d" descr="%s"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                '<pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="chart%d.png"/><pic:cNvPicPr/></pic:nvPicPr>'
                '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>%s</pic:spPr>'
                '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
                % (props, cx, cy, self.n, index, escape(item.text, {'"': '&quot;'}), index, rid, cx, cy, line))

    def figure_xml(self, item: Item, index: int, break_first: bool = False) -> str:
        """Рисунок и подпись; подпись сверху — перед рисунком, ``keepNext`` держит их вместе."""
        if self.l.caption_pos == 'above':
            return self.caption_p(item, index, True, break_first) + self.picture_p(item, index, False)
        return self.picture_p(item, index, True, break_first) + self.caption_p(item, index, False)

    def cell_xml(self, item: Optional[Item], index: int, width_twips: int) -> str:
        inner = self.figure_xml(item, index) if item is not None else '<w:p/>'
        return '<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>%s</w:tc>' % (width_twips, inner)

    def table(self, rows_xml: List[str]) -> str:
        l = self.l
        total = twips(l.content()[0])
        each = total // l.columns
        side = '<w:%s w:val="single" w:sz="4" w:color="BFBFBF"/>'
        borders = ''.join(side % s for s in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV')) if l.borders == 'thin' else ''
        pad_lr, pad_tb = twips(l.gap / 2), twips(l.row_gap / 2)
        return ('<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblBorders>%s</w:tblBorders>'
                '<w:tblCellMar><w:top w:w="%d" w:type="dxa"/><w:left w:w="%d" w:type="dxa"/><w:bottom w:w="%d" w:type="dxa"/>'
                '<w:right w:w="%d" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>%s</w:tblGrid>%s</w:tbl>'
                % (each * l.columns, borders, pad_tb, pad_lr, pad_tb, pad_lr, ('<w:gridCol w:w="%d"/>' % each) * l.columns, ''.join(rows_xml)))

    def para(self, text: str, style: str = '', page_break: bool = False) -> str:
        props = ('<w:pStyle w:val="%s"/>' % style if style else '') + ('<w:pageBreakBefore/>' if page_break else '')
        return '<w:p><w:pPr>%s</w:pPr>%s</w:p>' % (props, _run(text))


def build_docx(items: Sequence[Item], layout: Layout, project: str = '', errors: Optional[Sequence[Mapping[str, Any]]] = None,
               target=None, progress: Optional[Callable[[float], None]] = None):
    """Word-документ из готовых ``items`` (PNG и размеры уже посчитаны ``render_png``). Возвращает байты или ``target``."""
    if not items:
        raise ValueError('Для отчета Word выберите хотя бы один график.')
    l = layout
    b = Builder(l)
    pages = paginate(l, items)
    page_of = {i: p for p, rows in enumerate(pages, 1) for r in rows for i in r}
    front = bool(l.title or l.list_of_figures)
    cell_w = twips(l.content()[0]) // l.columns

    if l.title:
        b.body.append(b.para(l.title_text or ('Графики: ' + project if project else 'Графики'), 'Title'))
    if l.list_of_figures:
        b.body.append(b.para(l.list_title, 'ListHeading'))
        entries = []
        for i, it in enumerate(items):
            anchor = '_Ref%09d' % (700000000 + i)
            tab = '<w:r><w:tab/></w:r>' + _field('PAGEREF %s \\h' % anchor, str(page_of[i] + (1 if front else 0)))
            link = '<w:hyperlink w:anchor="%s" w:history="1"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>%s</w:hyperlink>' % (anchor, _text(it.text), tab)
            entries.append(link)
        start = '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\h \\z \\c "Рисунок" </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        for k, link in enumerate(entries):
            body = (start if k == 0 else '') + link + ('<w:r><w:fldChar w:fldCharType="end"/></w:r>' if k == len(entries) - 1 else '')
            b.body.append('<w:p><w:pPr><w:pStyle w:val="TableofFigures"/></w:pPr>%s</w:p>' % body)

    done = 0
    for p, rows in enumerate(pages):
        first_break = (p > 0 and bool(l.per_page)) or (p == 0 and front)
        if l.columns == 1:
            for r, row in enumerate(rows):
                for i in row:
                    b.body.append(b.figure_xml(items[i], i, break_first=(r == 0 and first_break)))
                    done += 1
        else:
            trs = []
            for row in rows:
                cells = [b.cell_xml(items[i], i, cell_w) for i in row] + [b.cell_xml(None, 0, cell_w)] * (l.columns - len(row))
                trs.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>%s</w:tr>' % ''.join(cells))
                done += len(row)
            if first_break:
                b.body.append('<w:p><w:pPr><w:pageBreakBefore/><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/></w:pPr>'
                              '<w:r><w:rPr><w:sz w:val="2"/></w:rPr><w:t></w:t></w:r></w:p>')
            b.body.append(b.table(trs))
        if progress:
            progress(done / len(items))
    if errors:
        b.body.append(b.para('Ошибки формирования: %d' % len(errors)))
        b.body.extend(b.para(str(e)) for e in errors)

    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
          'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
    pw, ph = l.page()
    footer_ref = '<w:footerReference w:type="default" r:id="rIdFooter"/>' if l.page_numbers else ''
    sect = ('<w:sectPr>%s<w:pgSz w:w="%d" w:h="%d"%s/><w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" w:header="%d" w:footer="%d" w:gutter="0"/></w:sectPr>'
            % (footer_ref, twips(pw), twips(ph), ' w:orient="landscape"' if l.orientation == 'landscape' else '',
               twips(l.margin_top), twips(l.margin_right), twips(l.margin_bottom), twips(l.margin_left),
               twips(min(10, l.margin_top / 2)), twips(min(10, l.margin_bottom / 2))))
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s%s</w:body></w:document>' % (ns, ''.join(b.body), sect)

    jc = ALIGNS[l.caption_align]
    font = l.caption_font
    sz = int(round(l.caption_size * 2))
    rfonts = '<w:rFonts w:ascii="{0}" w:hAnsi="{0}" w:eastAsia="{0}" w:cs="{0}"/>'.format(font)
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:docDefaults><w:rPrDefault><w:rPr>%s<w:sz w:val="%d"/><w:szCs w:val="%d"/><w:lang w:val="ru-RU"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
              '<w:pPr><w:jc w:val="%s"/></w:pPr><w:rPr>%s%s%s<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/>'
              '<w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="%d"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="ListHeading"><w:name w:val="List Heading"/><w:basedOn w:val="Normal"/>'
              '<w:pPr><w:spacing w:before="120" w:after="160"/></w:pPr><w:rPr><w:b/><w:sz w:val="%d"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="TableofFigures"><w:name w:val="table of figures"/><w:basedOn w:val="Normal"/>'
              '<w:pPr><w:tabs><w:tab w:val="right" w:leader="dot" w:pos="%d"/></w:tabs><w:spacing w:after="60"/></w:pPr></w:style>'
              '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/></w:pPr></w:style>'
              '</w:styles>') % (rfonts, sz, sz, jc, rfonts, '<w:b/>' if l.caption_bold else '', '<w:i/>' if l.caption_italic else '', sz, sz,
                                 int(sz * 1.4), int(sz * 1.2), twips(l.content()[0]))
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
             + ('<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>' if l.page_numbers else '')
             + '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + ''.join(b.rels)
            + '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            + ('<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>' if l.page_numbers else '')
            + '</Relationships>')
    footer = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>%s</w:p></w:ftr>' % _field('PAGE', '1'))
    out = io.BytesIO() if target is None else target
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', types)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml', document)
        z.writestr('word/styles.xml', styles)
        z.writestr('word/_rels/document.xml.rels', rels)
        if l.page_numbers:
            z.writestr('word/footer1.xml', footer)
        for member, png in b.media:
            z.writestr('word/' + member, png)
    return out.getvalue() if target is None else target


# ---------- предпросмотр ----------

def _font(size_px: int):
    from PIL import ImageFont
    import matplotlib
    from pathlib import Path
    path = Path(matplotlib.get_data_path()) / 'fonts' / 'ttf' / 'DejaVuSerif.ttf'
    try:
        return ImageFont.truetype(str(path), size_px)
    except OSError:
        return ImageFont.load_default()


def _wrap(draw, text: str, font, width: int) -> List[str]:
    words, lines, line = text.split(), [], ''
    for word in words:
        trial = (line + ' ' + word).strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def preview_png(layout: Layout, items: Sequence[Item], page: int, images: Mapping[int, bytes], scale: float = 3.0) -> Tuple[bytes, int]:
    """Лист ``page`` (с 1) как картинка: поля, графики из ``images`` (индекс → PNG) и подписи в тех же местах, что в Word.
    Возвращает PNG и число листов."""
    from PIL import Image, ImageDraw
    pages = paginate(layout, items)
    page = max(1, min(page, len(pages)))
    pw, ph = layout.page()
    px = lambda mm: int(round(mm * scale))
    sheet = Image.new('RGB', (px(pw), px(ph)), 'white')
    draw = ImageDraw.Draw(sheet)
    draw.rectangle([px(layout.margin_left), px(layout.margin_top), px(pw - layout.margin_right), px(ph - layout.margin_bottom)], outline='#dfe3ea')
    cap_font = _font(max(7, int(layout.caption_size * PT_MM * scale)))
    cell_w = layout.content()[0] / layout.columns
    inner = layout.cell()
    y = layout.margin_top
    for row in pages[page - 1]:
        height = row_height(layout, [items[i] for i in row]) - layout.row_gap
        for k, i in enumerate(row):
            it = items[i]
            x = layout.margin_left + k * cell_w + (cell_w - inner) / 2
            cap_h = caption_height(layout, it.text, inner)
            lines = _wrap(draw, it.text, cap_font, px(inner))
            line_h = int(layout.caption_size * 1.2 * PT_MM * scale)
            above = layout.caption_pos == 'above'
            top = y + (cap_h if above else 0)
            box = (px(x + (inner - it.w) / 2), px(top), px(x + (inner + it.w) / 2), px(top + it.h))
            data = images.get(i)
            if data:
                with Image.open(io.BytesIO(data)) as picture:
                    sheet.paste(picture.convert('RGB').resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS), (box[0], box[1]))
            else:
                draw.rectangle(box, fill='#f1f4f8', outline='#c9d1dc')
                draw.text((box[0] + 8, box[1] + 8), it.name[:40], fill='#7a8696', font=cap_font)
            if layout.frame:
                draw.rectangle(box, outline='#999999')
            ty = px(y + layout.caption_gap) if above else px(top + it.h + layout.caption_gap)
            for line in lines:
                width = draw.textlength(line, font=cap_font)
                align = layout.caption_align
                tx = px(x) + (px(inner) - width) / 2 if align == 'center' else px(x) + (px(inner) - width if align == 'right' else 0)
                draw.text((tx, ty), line, fill='black', font=cap_font)
                ty += line_h
            if layout.borders == 'thin':
                draw.rectangle([px(layout.margin_left + k * cell_w), px(y - layout.row_gap / 2), px(layout.margin_left + (k + 1) * cell_w), px(y + height + layout.row_gap / 2)], outline='#bfbfbf')
        y += height + layout.row_gap
    if layout.page_numbers:
        label = str(page)
        draw.text((px(pw / 2) - 4, px(ph - layout.margin_bottom / 2)), label, fill='#555555', font=cap_font)
    out = io.BytesIO()
    sheet.save(out, 'PNG', optimize=True)
    return out.getvalue(), len(pages)
