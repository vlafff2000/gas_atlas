"""Сцена рисунка: элементы готового графика с постоянными именами и рамками в долях рисунка.

Рисовальщик файлов (``export.py``) помечает то, что нарисовал: ряд, подпись точки, аннотацию — меткой ``_scene`` на объекте
Matplotlib (на вид и на содержимое файла метка не влияет). После отрисовки ``collect`` находит помеченное и стандартные части
(заголовок, легенду и её пункты, оси, область построения) и возвращает список::

    {'id': 'label:сезон 2024:2024-05-17', 'kind': 'label', 'box': [x0, y0, x1, y1], 'text': '87,2', 'series': 'сезон 2024', 'point': '2024-05-17'}

``box`` — в долях рисунка, начало в левом верхнем углу (как в браузере): по сцене предпросмотр понимает, по какому элементу
щёлкнули, проверки качества находят наложения и выход за край, а ручной сдвиг элемента хранится в тех же долях.

Имена: ``plot``, ``title``, ``subtitle``, ``legend``, ``legend:<пункт>``, ``axis:<x|y|y2…>``, ``axis-title:<ось>``,
``series:<имя ряда>``, ``label:<имя ряда>:<ключ точки>``, ``annotation:<номер>``, ``annotation-text:<номер>``.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

KINDS = ('plot', 'title', 'subtitle', 'legend', 'legend-item', 'axis', 'axis-title', 'series', 'label', 'annotation', 'annotation-text')


def mark(artist: Any, name: str, /, **extra: Any) -> Any:
    """Пометить нарисованное именем элемента сцены; ``extra`` — сведения об элементе (ряд, шкала, точка, ключ оформления)."""
    artist._scene = (name, extra)
    return artist


class Names:
    """Имена рядов сцены: по имени ряда; повторное имя получает номер (``series:Дебит#2``)."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def series(self, name: Any) -> str:
        text = str(name or '')
        count = self._seen[text] = self._seen.get(text, 0) + 1
        return text if count == 1 else f'{text}#{count}'


def _kind(key: str) -> str:
    head = key.split(':', 1)[0]
    return 'legend-item' if head == 'legend' and ':' in key else head


def _union(boxes: list[Any]) -> tuple[float, float, float, float] | None:
    found = [b for b in boxes if b is not None and all(math.isfinite(v) for v in (b.x0, b.y0, b.x1, b.y1)) and (b.width > 0 or b.height > 0)]
    if not found:
        return None
    return min(b.x0 for b in found), min(b.y0 for b in found), max(b.x1 for b in found), max(b.y1 for b in found)


def _extent(artist: Any, renderer: Any) -> Any:
    try:
        return artist.get_window_extent(renderer)
    except Exception:       # объект без размера на рисунке (пустая линия, невидимая часть)
        return None


def collect(f: Any, axes: Mapping[str, Any], frame: Any = None) -> list[dict[str, Any]]:
    """Элементы рисунка ``f``. ``axes`` — оси по именам шкал: ``{'y': ax, 'y2': twin, …}`` (ось X берётся у ``axes['y']``).
    Вызывается после сохранения рисунка: расстановка уже сделана, и повторная отрисовка (она сдвигает элементы на доли пикселя)
    не нужна — сцена описывает ровно тот рисунок, что попал в файл.
    ``frame`` — часть рисунка, попавшая в файл (рамка в пикселях рисунка), если файл обрезан по содержимому; иначе весь рисунок."""
    renderer = f.canvas.get_renderer()
    frame = frame or f.bbox
    left, bottom, width, height = frame.x0, frame.y0, frame.width, frame.height
    out: list[dict[str, Any]] = []

    def add(key: str, boxes: list[Any], /, **extra: Any) -> None:
        span = _union(boxes)
        if span is None:
            return
        x0, y0, x1, y1 = span
        box = [round(float(v), 4) for v in ((x0 - left) / width, 1 - (y1 - bottom) / height, (x1 - left) / width, 1 - (y0 - bottom) / height)]
        out.append({'id': key, 'kind': _kind(key), 'box': box, **{k: v for k, v in extra.items() if v not in (None, '')}})

    main = axes['y']
    plot = main.get_window_extent(renderer)
    add('plot', [plot])
    for text in (main.title, main._left_title, main._right_title):
        if text.get_text():
            add('title', [_extent(text, renderer)], text=text.get_text())
            break
    for name, target in (('x', main), *axes.items()):
        axis = target.xaxis if name == 'x' else target.yaxis
        lo, hi = sorted(axis.get_view_interval())
        slack = (hi - lo) * 1e-6
        # подписи делений за пределами шкалы Matplotlib держит, но не рисует: в рамку оси идут только деления в пределах шкалы
        inside = [_extent(t, renderer) for t in axis.get_ticklabels()
                  if t.get_visible() and t.get_text() and lo - slack <= t.get_position()[0 if name == 'x' else 1] <= hi + slack]
        add(f'axis:{name}', inside, axis=name)
        if axis.label.get_text() and axis.label.get_visible():
            add(f'axis-title:{name}', [_extent(axis.label, renderer)], axis=name, text=axis.label.get_text())
    legends = list(f.legends) + [a.get_legend() for a in f.axes if a.get_legend() is not None]
    for legend in legends:
        add('legend', [_extent(legend, renderer)])
        handles = getattr(legend, 'legend_handles', None) or getattr(legend, 'legendHandles', [])
        seen = Names()
        for handle, text in zip(handles, legend.get_texts()):
            label = ' '.join(text.get_text().split())
            add('legend:' + seen.series(label), [_extent(handle, renderer), _extent(text, renderer)], text=label)
    groups: dict[str, tuple[list[Any], dict[str, Any]]] = {}
    for target in f.axes:
        clip = target.get_window_extent(renderer)
        for artist in target.get_children():
            tag = getattr(artist, '_scene', None)
            if tag is None or not artist.get_visible():
                continue
            key, extra = tag
            box = _extent(artist, renderer)
            if box is not None and _kind(key) in ('series', 'annotation'):      # ряд и линия уровня видны только внутри области построения
                from matplotlib.transforms import Bbox
                box = Bbox.intersection(box, clip)
            found = groups.setdefault(key, ([], dict(extra)))
            found[0].append(box)
            if hasattr(artist, 'get_text') and 'text' not in found[1]:
                found[1]['text'] = artist.get_text()
    for key, (boxes, extra) in groups.items():
        add(key, boxes, **extra)
    return out
