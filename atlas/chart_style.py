"""Ручное оформление графика конструктора: ряд, ось, график. Пустое поле — «авто» (поле в словаре не появляется).

Хранится в макете (``layout.series[].look``, ``layout.axis_style``, ``layout.chart_style``), ложится в ``Series.look``, ``Axis.style``
и ``Chart.style`` и действует одинаково на экране (``web/src/ChartView.tsx``) и в выгрузке (``atlas/render.py``,
``atlas/engine/core/export_style.py``). Ошибка значения — ``ParamError`` с понятным текстом, неизвестные поля отбрасываются.
Шрифты — из набора выгрузки (``atlas.engine.core.fonts.FONTS``).
"""
from __future__ import annotations

import re
from typing import Any, Mapping

import pandas as pd

from .contract import ParamError

FONTS = ('default', 'times', 'arial_narrow', 'calibri')
SHAPES = ('circle', 'square', 'diamond', 'triangle', 'plus', 'x', 'star')
DASHES = ('solid', 'dash', 'dot')
LEGENDS = ('bottom', 'top', 'right', 'hide')
GRIDS = ('both', 'h', 'v', 'none')
ALIGNS = ('left', 'center', 'right')
DATE_FORMATS = ('dd.MM.yyyy', 'MM.yyyy', 'yyyy', 'dd.MM')
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _number(value: Any, what: str, low: float, high: float) -> float:
    try:
        x = float(str(value).strip().replace(' ', '').replace(',', '.'))
    except ValueError:
        raise ParamError(f'{what}: нужно число') from None
    if not low <= x <= high:
        raise ParamError(f'{what}: от {low:g} до {high:g}')
    return x


def _color(value: Any, what: str) -> str:
    text = str(value).strip()
    if not HEX.match(text):
        raise ParamError(f'{what}: цвет вида #rrggbb')
    return text.lower()


def _choice(value: Any, what: str, options: tuple[str, ...]) -> str:
    text = str(value).strip()
    if text not in options:
        raise ParamError(f'{what}: одно из {", ".join(options)}')
    return text


def _fill(raw: Any, what: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Общий разбор: spec — {поле: ('num', низ, верх) | ('int', низ, верх) | 'color' | 'bool' | tuple выбора | 'text'}; название — в what."""
    src = raw if isinstance(raw, Mapping) else {}
    out: dict[str, Any] = {}
    for key, kind in spec.items():
        value = src.get(key)
        if _empty(value):
            continue
        label = f'{what}, {LABELS.get(key, key)}'
        if kind == 'color':
            out[key] = _color(value, label)
        elif kind == 'bool':
            out[key] = value is True or str(value).lower() in ('1', 'true', 'да')
        elif kind == 'text':
            out[key] = str(value).strip()[:200]
        elif isinstance(kind, tuple) and kind and kind[0] == 'num':
            out[key] = _number(value, label, kind[1], kind[2])
        elif isinstance(kind, tuple) and kind and kind[0] == 'int':
            out[key] = int(_number(value, label, kind[1], kind[2]))
        else:
            out[key] = _choice(value, label, kind)
    return out


LABELS = {
    'width': 'толщина', 'size': 'размер', 'opacity': 'прозрачность', 'shape': 'форма', 'dash': 'стиль линии',
    'color': 'цвет', 'markerColor': 'цвет маркеров', 'decimals': 'знаков после запятой', 'tick_size': 'размер подписей',
    'title_size': 'размер названия', 'font': 'шрифт', 'date_format': 'формат даты', 'title_font': 'шрифт заголовка',
    'legend': 'легенда', 'legend_font': 'шрифт легенды', 'legend_size': 'размер легенды', 'grid': 'сетка', 'grid_color': 'цвет сетки',
    'background': 'фон графика', 'plot_background': 'фон области построения', 'title_color': 'цвет заголовка',
    'title_align': 'выравнивание заголовка', 'text_color': 'цвет текста',
}

LOOK = {'color': 'color', 'line': 'bool', 'width': ('num', 0.5, 12), 'dash': DASHES, 'marker': 'bool', 'shape': SHAPES,
        'size': ('num', 2, 24), 'markerColor': 'color', 'opacity': ('num', 0.05, 1), 'valueLabels': 'bool'}
AXIS_FMT = {'color': 'color', 'decimals': ('int', 0, 8), 'date_format': DATE_FORMATS, 'font': FONTS, 'tick_size': ('num', 5, 30),
            'title_size': ('num', 5, 30)}
CHART_FMT = {'title_font': FONTS, 'title_size': ('num', 6, 48), 'title_bold': 'bool', 'title_color': 'color', 'title_align': ALIGNS,
             'font': FONTS, 'text_color': 'color', 'legend': LEGENDS, 'legend_font': FONTS, 'legend_size': ('num', 5, 30),
             'grid': GRIDS, 'grid_color': 'color', 'background': 'color', 'plot_background': 'color'}


def clean_look(raw: Any, index: int) -> dict[str, Any]:
    """Вид ряда: цвет, линия (показать, толщина, стиль), маркеры (показать, форма, размер, цвет), прозрачность."""
    return _fill(raw, f'Ряд {index}', LOOK)


def clean_chart(raw: Any) -> dict[str, Any]:
    """Настройки графика: заголовок, шрифты, легенда, сетка, фон."""
    return _fill(raw, 'График', CHART_FMT)


def clean_axis(raw: Any, name: str) -> dict[str, Any]:
    """Настройки оси: границы, шаг, логарифм, обратное направление (необработанные, см. ``bound``) и оформление."""
    src = raw if isinstance(raw, Mapping) else {}
    out = _fill(src, f'Ось {name}', AXIS_FMT)
    for key in ('min', 'max', 'step'):
        if not _empty(src.get(key)):
            out[key] = str(src[key]).strip()
    for key in ('log', 'inverse', 'from_zero'):
        if src.get(key) is True or str(src.get(key)).lower() in ('1', 'true'):
            out[key] = True
    return out


def bound(text: Any, what: str, time: bool) -> float:
    """Граница оси: число (запятая допустима) или дата ``2024-05-17`` / ``17.05.2024`` для оси времени (мс, как на экране)."""
    s = str(text).strip()
    if time:
        for fmt in ('%Y-%m-%d', '%d.%m.%Y'):
            try:
                return float(pd.to_datetime(s, format=fmt).value // 1_000_000)
            except ValueError:
                pass
        raise ParamError(f'{what}: дата вида дд.мм.гггг')
    return _number(s, what, -1e15, 1e15)


def clean_axes(raw: Any) -> dict[str, dict[str, Any]]:
    src = raw if isinstance(raw, Mapping) else {}
    out = {}
    for name, title in (('x', 'X'), ('y', 'Y1'), ('y2', 'Y2'), ('y3', 'Y3'), ('y4', 'Y4'), ('y5', 'Y5')):
        item = clean_axis(src.get(name), title)
        if item:
            out[name] = item
    return out
