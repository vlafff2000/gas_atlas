"""Рисует значки ярлыков Газового атласа (tools/icons/*.png и *.ico). Нужен Pillow; готовые файлы лежат в git, при сборке архива рисовать не нужно.

    python tools/make_icons.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / 'icons'
S = 1024  # рисуем крупно и уменьшаем: гладкие края
WHITE = (255, 255, 255, 255)
SOFT = (255, 255, 255, 140)


def background(top, bottom):
    """Скруглённый квадрат с вертикальным градиентом и мягким бликом сверху."""
    grad = Image.new('RGBA', (S, S))
    px = grad.load()
    for y in range(S):
        t = y / (S - 1)
        colour = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(S):
            px[x, y] = colour
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, S - 24, S - 24), radius=220, fill=255)
    base = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    base.paste(grad, (0, 0), mask)
    gloss = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse((-200, -620, S + 200, 420), fill=(255, 255, 255, 38))
    base.alpha_composite(Image.composite(gloss, Image.new('RGBA', (S, S), (0, 0, 0, 0)), mask))
    return base


def bezier(p0, p1, p2, p3, n=24):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def flame_points(cx, cy, h):
    def P(x, y):
        return (cx + x * h, cy + y * h)
    pts = bezier(P(0.06, -0.52), P(0.0, -0.22), P(0.40, -0.06), P(0.30, 0.26))
    pts += bezier(P(0.30, 0.26), P(0.24, 0.52), P(-0.24, 0.52), P(-0.30, 0.26))
    pts += bezier(P(-0.30, 0.26), P(-0.36, 0.06), P(-0.14, -0.06), P(-0.10, -0.28))
    pts += bezier(P(-0.10, -0.28), P(-0.08, -0.38), P(0.0, -0.44), P(0.06, -0.52))
    return pts


def flame(d, cx, cy, h, fill, inner):
    """Язык пламени: внешний контур и внутренний огонёк."""
    d.polygon(flame_points(cx, cy, h), fill=fill)
    d.polygon(flame_points(cx + 0.02 * h, cy + 0.20 * h, h * 0.46), fill=inner)


def chart_base(d):
    d.line([(190, 190), (190, 820), (840, 820)], fill=SOFT, width=22, joint='curve')
    for k in range(4):
        x = 270 + k * 140
        top = (650, 580, 520, 440)[k]
        d.rounded_rectangle((x, top, x + 90, 780), radius=22, fill=(255, 255, 255, 70))


def atlas6(d):
    """Газовый атлас 6: графики и пламя."""
    chart_base(d)
    d.line([(230, 700), (400, 600), (560, 640), (780, 360)], fill=(255, 255, 255, 190), width=26, joint='curve')
    flame(d, 560, 470, 520, WHITE, (255, 150, 50, 255))


ICONS = {
    'gas_atlas_6': ((38, 150, 214), (18, 62, 140), atlas6),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (top, bottom, glyph) in ICONS.items():
        image = background(top, bottom)
        layer = Image.new('RGBA', (S, S), (0, 0, 0, 0))
        glyph(ImageDraw.Draw(layer))
        shadow = Image.new('RGBA', (S, S), (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 70), (0, 14), layer.getchannel('A'))
        image.alpha_composite(shadow)
        image.alpha_composite(layer)
        image.resize((256, 256), Image.LANCZOS).save(str(OUT / (name + '.png')))
        image.save(str(OUT / (name + '.ico')), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        print(name)


if __name__ == '__main__':
    main()
