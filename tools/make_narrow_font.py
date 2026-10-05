"""Собирает atlas/fonts/AtlasSansNarrow-*.ttf — узкий аналог Arial Narrow для Linux.

Arial Narrow — это Arial, сжатый по горизонтали примерно до 82 %. Здесь так же сжимается Liberation Sans
(метрически совместим с Arial, лицензия SIL OFL 1.1). OFL запрещает оставлять производному шрифту зарезервированное
имя «Liberation», поэтому семейство называется «Atlas Sans Narrow». Нужен только fontTools; результат лежит в git,
запускать скрипт надо лишь при смене исходных шрифтов:

    python tools/make_narrow_font.py [папка с LiberationSans-*.ttf]
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

SCALE = 0.82
FAMILY = 'Atlas Sans Narrow'
STYLES = {'Regular': 'Regular', 'Bold': 'Bold', 'Italic': 'Italic', 'BoldItalic': 'Bold Italic'}
OUT = Path(__file__).resolve().parents[1] / 'atlas' / 'fonts'


def narrow(src: Path, style: str) -> None:
    font = TTFont(str(src))
    glyphs = font.getGlyphSet()
    new = {}
    for name in font.getGlyphOrder():
        pen = TTGlyphPen(glyphs)
        glyphs[name].draw(TransformPen(pen, (SCALE, 0, 0, 1, 0, 0)))
        new[name] = pen.glyph()
    glyf = font['glyf']
    for name, glyph in new.items():
        glyf[name] = glyph
    hmtx = font['hmtx']
    for name in font.getGlyphOrder():
        advance, lsb = hmtx[name]
        hmtx[name] = (round(advance * SCALE), round(lsb * SCALE))
    for tag in ('GPOS', 'kern', 'hdmx', 'LTSH', 'VDMX', 'fpgm', 'prep', 'cvt ', 'gasp', 'DSIG', 'GDEF'):
        if tag in font:
            del font[tag]
    font['OS/2'].xAvgCharWidth = round(font['OS/2'].xAvgCharWidth * SCALE)
    full = f'{FAMILY} {style}' if style != 'Regular' else FAMILY
    ps = f"{FAMILY.replace(' ', '')}-{style.replace(' ', '')}"
    for rec in list(font['name'].names):
        if rec.nameID in (1, 16):
            rec.string = FAMILY
        elif rec.nameID in (2, 17):
            rec.string = style
        elif rec.nameID == 4:
            rec.string = full
        elif rec.nameID == 6:
            rec.string = ps
        elif rec.nameID == 3:
            rec.string = f'{ps};narrowed-from-Liberation-Sans'
        elif rec.nameID in (7, 8, 9, 11, 12, 13, 14):
            font['name'].removeNames(nameID=rec.nameID)
    font['name'].setName('Derived from Liberation Sans (SIL OFL 1.1), horizontally scaled to 82 %.', 13, 3, 1, 0x409)
    font['name'].setName('https://openfontlicense.org', 14, 3, 1, 0x409)
    font.save(str(OUT / f'AtlasSansNarrow-{style}.ttf'))


if __name__ == '__main__':
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/usr/share/fonts/truetype/liberation')
    OUT.mkdir(parents=True, exist_ok=True)
    for style in STYLES:
        narrow(folder / f'LiberationSans-{style}.ttf', STYLES[style].replace(' ', ''))
