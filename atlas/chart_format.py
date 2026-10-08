"""Оформление выгружаемых графиков.

Общее для всех графиков (поля формы ``fmt_angle``, ``fmt_title``, ``fmt_legend``): наклон подписей оси X (auto, 0, 30, 45,
60, 90), шапка графика (show/hide), положение легенды (bottom/top/right/hide).

Для наборов данных (поле ``fmt_<модуль>_series``): JSON-список правил ``[{"match": "фрагмент названия", "color": "#rrggbb",
"width": 2, "marker": 0, "hide": true}]``. Правило действует на все ряды, в названии (или группе легенды) которых есть фрагмент:
``width`` — толщина линии, пт; ``marker`` — размер маркеров (0 — без маркеров); ``color`` — цвет; ``hide`` — убрать набор
с графика. Пустое поле не меняет ничего; несколько подходящих правил применяются по порядку.
Оформление накладывается на уже построенный график (как подписи, ``chart_labels``), пересчёта не требует.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Mapping

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
            item['width'] = number(rule['width'], 'Толщина линии набора', 0, 10)
        if rule.get('marker') not in (None, ''):
            item['marker'] = number(rule['marker'], 'Размер маркеров набора', 0, 20)
        if rule.get('hide'):
            item['hide'] = True
        out.append(item)
    return out


def common(form: Mapping[str, Any]) -> Dict[str, Any]:
    """Общие настройки всех графиков."""
    out: Dict[str, Any] = {}
    angle = form.get('fmt_angle')
    if angle not in (None, '', 'auto'):
        if str(angle) not in ANGLES:
            raise FormatError('Наклон подписей оси X: %s' % ', '.join(ANGLES))
        out['angle'] = str(angle)
    if form.get('fmt_title') == 'hide':
        out['title'] = 'hide'
    if form.get('fmt_legend') in LEGENDS and form.get('fmt_legend') != 'bottom':
        out['legend'] = form['fmt_legend']
    return out


def configs(form: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Настройки по модулям: общие + правила наборов данных этого модуля; ключ ``'*'`` — общие для модулей без правил.
    Ошибки значений — до построения графиков."""
    base = common(form)
    found: Dict[str, Dict[str, Any]] = {}
    for key, value in form.items():
        if not key.startswith('fmt_') or not key.endswith('_series'):
            continue
        module = key[len('fmt_'):-len('_series')]
        rules = parse_series(value)
        if module and rules:
            found[module] = {**base, 'series': rules}
    if base:
        found['*'] = base
    return found


def for_module(found: Mapping[str, Dict[str, Any]], module: str) -> Dict[str, Any]:
    return dict(found.get(module) or found.get('*') or {})


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
        width = size = None
        color = None
        name = ' '.join(str(x) for x in (trace.name, trace.legendgroup) if x).lower()
        for rule in rules:                  # правила наборов данных перекрывают настройки типа графика
            if rule['match'] not in name:
                continue
            if rule.get('hide'):
                trace.visible = False
            color = rule.get('color', color)
            if 'width' in rule and ('lines' in mode or rule['width'] <= 0):
                width = rule['width']
            if 'marker' in rule and 'markers' in mode:
                size = rule['marker']
        own = set()
        if line:
            if width is not None and width <= 0:      # толщина 0 — линия выключена, остаются маркеры
                trace.mode = 'markers'
                own.add('width')
            elif width is not None:
                trace.line.width = width
                own.add('width')
            if size is not None:
                if size <= 0 and trace.mode == 'markers' and width is not None and width <= 0:
                    pass
                elif size <= 0 and 'lines' in mode:
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
