"""Выгрузка всех графиков результата разом: ZIP из PNG (по файлу на график) или один лист-плитка PNG с 1–3 графиками в ряд.

Каждый график рисуется тем же экспортёром, что и кнопка «Скачать» у графика (``render.chart_file``): цвета, подписи и подложка те же.
"""
from __future__ import annotations

import io
import zipfile
from typing import Sequence

from . import render
from .contract import Chart


def _names(charts: Sequence[Chart]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for chart in charts:
        base = render.safe_name(chart.title) or chart.id
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f'{base}_{seen[base]}')
    return out


def archive(charts: Sequence[Chart], title: str, dpi: int = 200) -> tuple[bytes, str, str]:
    """ZIP: PNG на каждый график."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for chart, name in zip(charts, _names(charts)):
            zf.writestr(f'{name}.png', render.chart_file(chart, 'png', dpi)[0])
    return buffer.getvalue(), f'{render.safe_name(title)}_PNG.zip', 'application/zip'


def sheet(charts: Sequence[Chart], title: str, cols: int = 2, dpi: int = 150) -> tuple[bytes, str, str]:
    """Один PNG: графики в сетке по ``cols`` в ряд, одного размера, белый фон."""
    from PIL import Image
    cols = min(max(int(cols), 1), 3)
    images = [Image.open(io.BytesIO(render.chart_file(chart, 'png', dpi)[0])).convert('RGB') for chart in charts]
    width, height = max(i.width for i in images), max(i.height for i in images)
    rows = -(-len(images) // cols)
    canvas = Image.new('RGB', (width * cols, height * rows), 'white')
    for k, image in enumerate(images):
        canvas.paste(image, ((k % cols) * width + (width - image.width) // 2, (k // cols) * height + (height - image.height) // 2))
    buffer = io.BytesIO()
    canvas.save(buffer, format='PNG', dpi=(dpi, dpi))
    return buffer.getvalue(), f'{render.safe_name(title)}_плитка.png', 'image/png'
