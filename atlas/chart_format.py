"""Оформление выгружаемых графиков — отдельно для каждого типа (модуля): толщина линий, размер и наличие маркеров,
цвета и скрытие отдельных наборов данных, наклон подписей оси X, заголовок и положение легенды.

Поля формы ``fmt_<модуль>_<поле>``: ``width`` (толщина линий, пт), ``marker`` (размер маркеров; 0 — без маркеров),
``angle`` (наклон подписей оси X: auto, 0, 30, 45, 60, 90), ``title`` (show/hide), ``legend`` (bottom/top/right/hide),
``series`` — JSON-список правил по наборам данных ``[{"match": "фрагмент имени", "color": "#rrggbb", "width": 2,
"marker": 0, "hide": true}]``: правило действует на все ряды, в имени которых есть фрагмент; пустое поле не меняет ничего.
Оформление применяется к уже построенному графику (как подписи, ``chart_labels``), пересчёта не требует.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Mapping

FIELDS = ('width', 'marker', 'angle', 'title', 'legend', 'series')
ANGLES = ('auto', '0', '30', '45', '60', '90')
LEGENDS = ('bottom', 'top', 'right', 'hide')
COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


class FormatError(ValueError):
    pass


def number(value: Any, name: str, low: float, high: float) -> float:
    try:
        x = float(str(value).replace(',', '.'))
    except ValueError:
        raise FormatError('%s: нужно число' % name) from None
    if not low <= x <= high:
        raise FormatError('%s: от %g до %g' % (name, low, high))
    return x


def parse_series(text: Any) -> List[Dict[str, Any]]:
    if not str(text or '').strip():
        return []
    try:
        rules = json.loads(text) if isinstance(text, str) else list(text)
    except ValueError:
        raise FormatError('Наборы данных: неверный формат правил') from None
    if not isinstance(rules, list) or len(rules) > 50:
        raise FormatError('Наборы данных: не больше 50 правил')
    out = []
    for rule in rules:
        if not isinstance(rule, dict) or not str(rule.get('match', '')).strip():
            continue
        item: Dict[str, Any] = {'match': str(rule['match']).strip()[:200].lower()}
        color = str(rule.get('color') or '')
        if color:
            if not COLOR.match(color):
                raise FormatError('Цвет набора данных: вид #rrggbb')
            item['color'] = color
        if rule.get('width') not in (None, ''):
            item['width'] = number(rule['width'], 'Толщина линии набора', .2, 10)
        if rule.get('marker') not in (None, ''):
            item['marker'] = number(rule['marker'], 'Размер маркеров набора', 0, 20)
        if rule.get('hide'):
            item['hide'] = True
        out.append(item)
    return out


def configs(form: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Непустые настройки по модулям; ошибки значений — до построения графиков."""
    found: Dict[str, Dict[str, Any]] = {}
    for key, value in form.items():
        if not key.startswith('fmt_'):
            continue
        module, _, field = key[len('fmt_'):].rpartition('_')
        if field not in FIELDS or not module or value in (None, '', 'auto', 'default'):
            continue
        if field == 'width':
            value = number(value, 'Толщина линий', .2, 10)
        elif field == 'marker':
            value = number(value, 'Размер маркеров', 0, 20)
        elif field == 'angle':
            if str(value) not in ANGLES:
                raise FormatError('Наклон подписей оси X: %s' % ', '.join(ANGLES))
        elif field == 'title':
            if value not in ('show', 'hide'):
                continue
        elif field == 'legend':
            if value not in LEGENDS:
                continue
        elif field == 'series':
            value = parse_series(value)
            if not value:
                continue
        found.setdefault(module, {})[field] = value
    return found


def apply(figure, cfg: Mapping[str, Any]):
    """Копия графика с оформлением из ``cfg``."""
    fig = copy.deepcopy(figure)
    meta = dict(fig.layout.meta) if isinstance(fig.layout.meta, dict) else {}
    look = {f: str(cfg[f]) for f in ('title', 'angle', 'legend') if f in cfg}
    if look:
        meta['format'] = look
        fig.layout.meta = meta
    rules = cfg.get('series', [])
    for trace in fig.data:
        line = trace.type in (None, 'scatter')
        mode = trace.mode or ''
        width = cfg.get('width') if 'lines' in mode else None
        size = cfg.get('marker') if 'markers' in mode else None
        color = None
        name = ' '.join(str(x) for x in (trace.name, trace.legendgroup) if x).lower()
        for rule in rules:                  # правила наборов данных перекрывают настройки типа графика
            if rule['match'] not in name:
                continue
            if rule.get('hide'):
                trace.visible = False
            color = rule.get('color', color)
            if 'width' in rule and 'lines' in mode:
                width = rule['width']
            if 'marker' in rule and 'markers' in mode:
                size = rule['marker']
        own = set()
        if line:
            if width is not None:
                trace.line.width = width
                own.add('width')
            if size is not None:
                if size <= 0 and 'lines' in mode:
                    trace.mode = 'lines'
                elif size > 0:
                    trace.marker.size = size * 2
                    own.add('size')
            if color:
                trace.line.color = trace.marker.color = color
                own.add('color')
        elif color:
            trace.marker.color = color
        if own:
            tmeta = dict(trace.meta) if isinstance(trace.meta, dict) else {}
            tmeta['own'] = sorted(own)
            trace.meta = tmeta
    return fig
