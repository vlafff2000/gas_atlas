"""Оформление диаграммы Excel по модели v2 (``atlas/chart_style.py``): график остаётся настоящей диаграммой Excel, которую
можно править дальше. Что openpyxl не умеет (прозрачность линий, общий шрифт диаграммы), пропускается: в Excel это правится вручную."""
from __future__ import annotations

from typing import Any, Mapping

from openpyxl.chart.axis import ChartLines, DisplayUnitsLabelList
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText, Text
from openpyxl.chart.title import Title
from openpyxl.drawing.line import LineProperties
from openpyxl.drawing.text import CharacterProperties, Font, Paragraph, ParagraphProperties, RegularTextRun, RichTextProperties

PX = 9525                                                      # EMU в пикселе (толщина линий в оформлении — px)
DASH = {'solid': 'solid', 'dash': 'dash', 'dot': 'sysDot', 'dashdot': 'dashDot', 'longdash': 'lgDash'}
TICK = {'out': 'out', 'in': 'in', 'cross': 'cross', 'none': 'none'}
LEGEND = {'bottom': 'b', 'top': 't', 'right': 'r', 'left': 'l'}
SYMBOL = {'circle': 'circle', 'square': 'square', 'diamond': 'diamond', 'triangle': 'triangle', 'plus': 'plus', 'x': 'x', 'star': 'star'}
LABEL = {'top': 't', 'bottom': 'b', 'left': 'l', 'right': 'r', 'inside': 'inEnd', 'center': 'ctr'}
UNITS = {'thousands': 'thousands', 'millions': 'millions', 'billions': 'billions'}
FONTS = {'times': 'Times New Roman', 'arial_narrow': 'Arial Narrow', 'calibri': 'Calibri'}


def _hex(color: Any) -> str | None:
    c = str(color or '').lstrip('#')
    return c.upper() if len(c) == 6 else None


def _chars(size: Any = None, bold: Any = None, italic: Any = None, color: Any = None, font: Any = None) -> CharacterProperties:
    return CharacterProperties(sz=int(float(size) * 100) if size else None, b=True if bold else None, i=True if italic else None,
                               solidFill=_hex(color), latin=Font(typeface=FONTS[font]) if font in FONTS else None)


def title_of(lines: list[tuple[str, Mapping[str, Any]]]) -> Title:
    """Название из строк с оформлением: (текст, {size, bold, italic, color, font})."""
    paragraphs = [Paragraph(pPr=ParagraphProperties(defRPr=_chars(**f)), r=[RegularTextRun(rPr=_chars(**f), t=text)]) for text, f in lines if text]
    return Title(tx=Text(rich=RichText(p=paragraphs)), overlay=False)


def _text_props(spec: Mapping[str, Any], base: Mapping[str, Any]) -> RichText | None:
    rotate = spec.get('label_rotate')
    font = _chars(spec.get('tick_size'), spec.get('tick_bold'), spec.get('tick_italic'), spec.get('color') or base.get('text_color'),
                  spec.get('font') or base.get('font'))
    if not rotate and not any((font.sz, font.b, font.i, font.solidFill, font.latin)):
        return None
    return RichText(bodyPr=RichTextProperties(rot=int(float(rotate) * 60000) if rotate else None, vert='horz'),
                    p=[Paragraph(pPr=ParagraphProperties(defRPr=font), endParaRPr=font)])


def _line(color: Any = None, width: Any = None, dash: Any = None) -> LineProperties:
    return LineProperties(solidFill=_hex(color), w=int(float(width) * PX) if width else None, prstDash=DASH.get(dash))


def _grid(on: bool, color: Any, width: Any, dash: Any) -> ChartLines | None:
    if not on:
        return None
    return ChartLines(spPr=GraphicalProperties(ln=_line(color or 'E4E9EF', width or 0.7, dash)))


def style_axis(ax, spec: Mapping[str, Any], scale: Any, base: Mapping[str, Any], title: str, grid: tuple[bool, bool] | None) -> None:
    """Деления, шкала, линия, подписи, единицы и название одной оси диаграммы."""
    if scale.minimum is not None:
        ax.scaling.min = scale.minimum
    if scale.maximum is not None:
        ax.scaling.max = scale.maximum
    if scale.step and scale.scale != 'time':
        ax.majorUnit = scale.step
    if spec.get('minor_step'):
        ax.minorUnit = spec['minor_step']
    if scale.scale == 'log':
        ax.scaling.logBase = 10
    if scale.inverse:
        ax.scaling.orientation = 'maxMin'
    if spec.get('cross') is not None:
        ax.crossesAt = spec['cross']
    if spec.get('ticks'):
        ax.majorTickMark = TICK[spec['ticks']]
    if spec.get('minor_ticks'):
        ax.minorTickMark = TICK[spec['minor_ticks']]
    if spec.get('units') in UNITS:
        ax.dispUnits = DisplayUnitsLabelList(builtInUnit=UNITS[spec['units']])
    if 'decimals' in spec and scale.scale in ('value', 'log'):
        ax.number_format = '#,##0' + ('.' + '0' * int(spec['decimals']) if int(spec['decimals']) else '')
        ax.numFmt.sourceLinked = False
    if spec.get('line') is False:
        ax.spPr = GraphicalProperties(ln=LineProperties(noFill=True))
    elif spec.get('line_color') or spec.get('line_width') or spec.get('color'):
        ax.spPr = GraphicalProperties(ln=_line(spec.get('line_color') or spec.get('color'), spec.get('line_width')))
    props = _text_props(spec, base)
    if props is not None:
        ax.txPr = props
    if title:
        ax.title = title_of([(title, {'size': spec.get('title_size'), 'bold': spec.get('title_bold'), 'italic': spec.get('title_italic'),
                                     'color': spec.get('color') or base.get('text_color'), 'font': spec.get('font') or base.get('font')})])
    if grid is not None:                       # сетка задана оформлением; иначе остаётся сетка Excel по умолчанию
        major, minor = grid
        ax.majorGridlines = _grid(major, base.get('grid_color'), base.get('grid_width'), base.get('grid_dash'))
        ax.minorGridlines = _grid(minor, base.get('minor_grid_color') or 'F0F2F5', base.get('minor_grid_width') or 0.5, base.get('minor_grid_dash'))


def style_chart(part, base: Mapping[str, Any], title: str) -> None:
    """Название и подзаголовок, легенда, фон и рамки диаграммы."""
    fmt = {'bold': base.get('title_bold', True), 'color': base.get('title_color') or base.get('text_color'), 'font': base.get('title_font') or base.get('font'),
           'size': base.get('title_size')}
    sub = {'size': base.get('subtitle_size') or 10, 'color': base.get('text_color') or '667085', 'font': base.get('font')}
    part.title = title_of([(title, fmt), (base.get('subtitle', ''), sub)])
    legend = base.get('legend')
    if legend == 'hide':
        part.legend = None
    elif part.legend is not None:
        part.legend.position = LEGEND.get(legend, 'b')
        if base.get('legend_border') or base.get('legend_background'):
            part.legend.spPr = GraphicalProperties(solidFill=_hex(base.get('legend_background')),
                                                   ln=_line('9AA4B2', 0.75) if base.get('legend_border') else LineProperties(noFill=True))
        if base.get('legend_size') or base.get('legend_font') or base.get('font'):
            font = _chars(base.get('legend_size'), None, None, base.get('text_color'), base.get('legend_font') or base.get('font'))
            part.legend.txPr = RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=font), endParaRPr=font)])
    if base.get('background') or base.get('border_color') or base.get('border_width'):
        part.graphical_properties = GraphicalProperties(
            solidFill=_hex(base.get('background')),
            ln=_line(base.get('border_color') or '888888', base.get('border_width') or 1) if base.get('border_color') or base.get('border_width') else None)
    if base.get('plot_background') or base.get('plot_border_color') or base.get('plot_border_width'):
        part.plot_area.graphicalProperties = GraphicalProperties(
            solidFill=_hex(base.get('plot_background')),
            ln=_line(base.get('plot_border_color') or '888888', base.get('plot_border_width') or 1) if base.get('plot_border_color') or base.get('plot_border_width') else None)


def style_series(one, look: Mapping[str, Any], category: bool, kind: str, color: str) -> None:
    """Линия, маркер и подписи данных одного ряда по его виду (``Series.look``)."""
    if look.get('legend_name'):
        from openpyxl.chart.series import SeriesLabel
        one.tx = SeriesLabel(v=str(look['legend_name']))
    if not category:
        line = one.graphicalProperties.line
        if kind == 'line':
            if look.get('width'):
                line.width = int(float(look['width']) * PX)
            if look.get('dash') in DASH:
                line.dashStyle = DASH[look['dash']]
            if look.get('line') is False:
                line.noFill = True
        mark = one.marker
        if look.get('marker') is False:
            mark.symbol = 'none'
        elif look.get('marker') or kind == 'points':
            mark.symbol = SYMBOL.get(look.get('shape'), mark.symbol if mark.symbol not in (None, 'none') else 'circle')
        if mark.symbol not in (None, 'none'):
            mark.size = int(look.get('size') or mark.size or 6)
            fill = _hex(look.get('markerColor')) or _hex(color)
            border = _hex(look.get('marker_border')) or fill
            mark.graphicalProperties = GraphicalProperties(solidFill='FFFFFF' if look.get('hollow') else fill,      # полый маркер — белая заливка
                                                           ln=_line(border, look.get('marker_border_width') or (1.8 if look.get('hollow') else 0.75)))
    if look.get('valueLabels'):
        decimals = look.get('label_decimals')
        font = _chars(look.get('label_size'))
        one.dLbls = DataLabelList(showVal=True, showSerName=False, showCatName=False, showLegendKey=False, showPercent=False,
                                  dLblPos=LABEL.get(look.get('label_position'), 't') if not category or look.get('label_position') else None,
                                  numFmt=('0' + ('.' + '0' * int(decimals) if decimals else '')) if decimals is not None else None,
                                  txPr=RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=font), endParaRPr=font)]) if font.sz else None)
