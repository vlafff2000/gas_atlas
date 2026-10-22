"""Вид графика на экране для выгрузки и копирования: личные настройки браузера поверх расчёта модуля.

Расчёт графика при выгрузке повторяется на сервере и даёт график «по умолчанию». Всё, что инженер поменял в окне
(вид рядов из «Настройки», границы осей, масштаб по времени, скрытые пункты легенды), хранится в браузере, поэтому
интерфейс присылает это в поле ``view``, а здесь оно накладывается на график перед рисованием.
Значения проверяются так же, как вид из конструктора (``atlas/chart_style.py``); лишнее отбрасывается.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Mapping

from .chart_style import clean_look
from .contract import Axis, Chart, ParamError, Series

AXES = ('y', 'y2', 'y3', 'y4', 'y5')


def series_key(s: Series) -> str:
    """Тот же ключ, что в интерфейсе (``seriesLookKey``): группа или имя, и вид ряда."""
    return f'{s.group or s.name}|{s.kind}'


def _range(raw: Any) -> tuple[float, float] | None:
    try:
        lo, hi = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return (lo, hi) if math.isfinite(lo) and math.isfinite(hi) and lo != hi else None


def _limited(axis: Axis, bounds: tuple[float, float]) -> Axis:
    lo, hi = sorted(bounds)
    style = {**axis.style, 'min': lo, 'max': hi}        # ключи min/max включают ручное оформление осей в выгрузке
    return dataclasses.replace(axis, minimum=lo, maximum=hi, style=style)


def apply_view(chart: Chart, view: Any) -> Chart:
    """График с видом, как на экране: ``view`` = {looks, ranges, x, hidden, facets}; пустой или неверный вид ничего не меняет."""
    if not isinstance(view, Mapping) or not view:
        return chart
    looks = view.get('looks') if isinstance(view.get('looks'), Mapping) else {}
    hidden = {str(k) for k in view.get('hidden') or []}
    off = {str(k) for k in view.get('facets') or []}
    def faceted_off(s: Series) -> bool:
        return any(f'{k}\u0001{v}' in off for k, v in (s.facets or {}).items())

    # пункт легенды (группа рядов) скрыт признаком, когда выключено значение признака у каждого его ряда
    by_item: dict[str, list[Series]] = {}
    for s in chart.series:
        by_item.setdefault(s.group or s.name, []).append(s)
    gone = {key for key, items in by_item.items() if off and all(s.facets for s in items) and all(faceted_off(s) for s in items)}
    series = []
    for s in chart.series:
        if (s.group or s.name) in hidden | gone:
            continue
        own = looks.get(series_key(s))
        if isinstance(own, Mapping) and own:
            try:
                look = {**(s.look or {}), **clean_look(own, len(series) + 1)}
            except ParamError:       # неверное поле вида из браузера не должно ломать выгрузку
                look = s.look
            s = dataclasses.replace(s, look=look, **({'opacity': look['opacity']} if look and 'opacity' in look else {}))
        series.append(s)
    out = dataclasses.replace(chart, series=series)
    ranges = view.get('ranges') if isinstance(view.get('ranges'), Mapping) else {}
    for name in AXES:
        bounds = _range(ranges.get(name))
        if bounds is None or name not in out.axis_names():
            continue
        out = dataclasses.replace(out, **{name: _limited(out.axis_at(name), bounds)})
    for name, axis in out.right_axes():       # цвет правой шкалы следует за цветом её рядов, как на экране
        colors = {(s.look or {}).get('color') for s in out.series if s.axis == name}
        if axis.color and len(colors) == 1 and None not in colors:
            out = dataclasses.replace(out, **{name: dataclasses.replace(axis, color=colors.pop())})
    window = _range(view.get('x'))
    if window is not None and out.x.scale in ('value', 'time'):
        out = dataclasses.replace(out, x=_limited(out.x, window))
    return out
