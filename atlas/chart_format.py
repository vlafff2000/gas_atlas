"""Оформление выгружаемых графиков.

Общее для всех графиков (поля формы ``fmt_angle``, ``fmt_title``, ``fmt_legend``): наклон подписей оси X (auto, 0, 30, 45,
60, 90), шапка графика (show/hide), положение легенды (bottom/top/right/hide).

Для наборов данных (поле ``fmt_<модуль>_series``): JSON-список правил ``[{"match": "фрагмент названия", "color": "#rrggbb",
"width": 2, "marker": 0, "hide": true}]``. Правило действует на все ряды, в названии (или группе легенды) которых есть фрагмент:
``width`` — толщина линии, пт; ``marker`` — размер маркеров (0 — без маркеров); ``color`` — цвет; ``hide`` — убрать набор
с графика. Пустое поле не меняет ничего; несколько подходящих правил применяются по порядку.
Оси (поле ``fmt_<модуль>_axes``): JSON ``{"y": {"min": 0, "max": 150, "major": 25, "minor": 5}, "y2": {...}, "x": {...}}``;
для оси X-дат границы — даты (``"2006-07-01"`` или ``"01.07.2006"``), деления — ``{"unit": "year"|"month"|"day", "n": 1}``:
``{"x": {"min": "2006-01-01", "max": "2026-01-01", "major": {"unit": "year", "n": 1}, "minor": {"unit": "month", "n": 3}}}``.
Пустое значение — автоматически. Рисует ``atlas.engine.core.export.figure_bytes`` (сетка делений начинается с нижней границы).
Отдельные графики (поле ``fmt_overrides``): JSON ``{"<имя графика>": {"series": [правила], "axes": {...}}}`` — то же, что выше, но для одного
графика из семейства; правила наборов данных идут после правил типа (перекрывают их), оси заменяют оси типа по каждой оси отдельно.
Сетка и оси для всех графиков (поля ``fmt_grid``, ``fmt_grid_width``, ``fmt_grid_color``, ``fmt_minor_grid``, ``fmt_minor_grid_color``,
``fmt_minor_grid_width``; жирный и курсив — ``fmt_axis_title_bold``, ``fmt_axis_title_italic``, ``fmt_tick_bold``, ``fmt_tick_italic``):
те же правила и проверки, что у «Любой график» (``atlas/chart_style.py``); попадают в ``layout.meta['style']`` и рисуются
``atlas.engine.core.export_style``.
Оформление накладывается на уже построенный график (как подписи, ``chart_labels``), пересчёта не требует.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Mapping

from .chart_style import clean_axis, clean_chart, clean_look

ANGLES = ('auto', '0', '30', '45', '60', '90')
LEGENDS = ('bottom', 'top', 'right', 'hide')
COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


# что из вида ряда «Любого графика» доступно в правилах наборов данных вкладок экспорта
SERIES_LOOK = ('dash', 'shape', 'markerColor', 'opacity', 'hollow', 'marker_border', 'marker_border_width', 'valueLabels', 'label_position',
               'label_decimals', 'label_size', 'label_angle', 'legend_name', 'hatch', 'hatch_color')


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
        if rule.get('look'):        # полный вид ряда, как в «Любом графике»: штрих, форма маркера, подписи данных, штриховка, имя в легенде
            look = clean_look(rule['look'], len(out) + 1)
            look = {k: v for k, v in look.items() if k in SERIES_LOOK}
            if look:
                item['look'] = look
        out.append(item)
    return out


UNITS = ('year', 'month', 'day')


def _date(value: Any, name: str) -> str:
    text = str(value).strip()
    for fmt in ('%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(text, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    raise FormatError('%s: дата вида дд.мм.гггг' % name)


def _step(value: Any, name: str, dates: bool) -> Any:
    if not dates:
        return number(value, name, 1e-9, 1e12)
    if not isinstance(value, dict):
        raise FormatError('%s: укажите единицу и количество' % name)
    unit = str(value.get('unit') or '')
    if unit not in UNITS:
        raise FormatError('%s: год, месяц или день' % name)
    n = int(number(value.get('n'), name + ' (количество)', 1, 10000))
    return {'unit': unit, 'n': n}


def parse_axes(text: Any) -> Dict[str, Dict[str, Any]]:
    """Ручные границы и деления осей (см. описание модуля); пустые поля пропускаются."""
    if not str(text or '').strip():
        return {}
    try:
        raw = json.loads(text) if isinstance(text, str) else dict(text)
    except ValueError:
        raise FormatError('Оси: неверный формат') from None
    if not isinstance(raw, dict):
        raise FormatError('Оси: неверный формат')
    out: Dict[str, Dict[str, Any]] = {}
    for axis, label in (('x', 'ось X'), ('y', 'ось Y'), ('y2', 'дополнительная ось Y')):
        spec = raw.get(axis)
        if not isinstance(spec, dict):
            continue
        dates = bool(spec.get('dates'))
        item: Dict[str, Any] = {}
        for key, title in (('min', 'минимум'), ('max', 'максимум')):
            value = spec.get(key)
            if value not in (None, ''):
                item[key] = _date(value, '%s, %s' % (label, title)) if dates else number(value, '%s, %s' % (label, title), -1e12, 1e12)
        for key, title in (('major', 'основное деление'), ('minor', 'дополнительное деление')):
            value = spec.get(key)
            if value not in (None, '') and not (dates and isinstance(value, dict) and not value.get('n')):
                item[key] = _step(value, '%s, %s' % (label, title), dates)
        if 'min' in item and 'max' in item and not item['min'] < item['max']:
            raise FormatError('%s: минимум должен быть меньше максимума' % label)
        if item:
            item['dates'] = dates
            out[axis] = item
    return out


def parse_overrides(text: Any) -> Dict[str, Dict[str, Any]]:
    """Свои настройки отдельных графиков: ``{имя графика: {'series': [...], 'axes': {...}}}``; пустые пропускаются."""
    if not str(text or '').strip():
        return {}
    try:
        raw = json.loads(text) if isinstance(text, str) else dict(text)
    except ValueError:
        raise FormatError('Отдельные графики: неверный формат') from None
    if not isinstance(raw, dict) or len(raw) > 500:
        raise FormatError('Отдельные графики: неверный формат или больше 500 графиков')
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        item: Dict[str, Any] = {}
        series, axes = parse_series(spec.get('series')), parse_axes(spec.get('axes'))
        if series:
            item['series'] = series
        if axes:
            item['axes'] = axes
        if item:
            out[str(name)] = item
    return out


def merge(cfg: Mapping[str, Any], own: Mapping[str, Any]) -> Dict[str, Any]:
    """Настройки типа графиков + свои настройки одного графика (они сильнее)."""
    out = dict(cfg)
    if own.get('series'):
        out['series'] = list(cfg.get('series', [])) + list(own['series'])
    if own.get('axes'):
        out['axes'] = {**cfg.get('axes', {}), **own['axes']}
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
    style = style_of(form)
    if style:
        out['style'] = style
        where = (style.get('chart') or {}).get('legend')      # положение легенды из полной панели, если не задано полем fmt_legend
        if where and 'legend' not in out and where != 'bottom':
            out['legend'] = where
    return out


STYLE_CHART = ('grid', 'grid_width', 'grid_color', 'minor_grid', 'minor_grid_color', 'minor_grid_width', 'legend_columns')
STYLE_TEXT = ('title_bold', 'title_italic', 'tick_bold', 'tick_italic')


def parse_style(text: Any) -> Dict[str, Dict[str, Any]]:
    """Поле ``fmt_style``: JSON ``{"chart": {...оформление графика...}, "axes": {...оформление всех осей...}}``."""
    if not str(text or '').strip():
        return {'chart': {}, 'axes': {}}
    try:
        doc = json.loads(text) if isinstance(text, str) else dict(text)
    except ValueError:
        raise FormatError('Оформление: неверный формат') from None
    if not isinstance(doc, dict):
        raise FormatError('Оформление: неверный формат')
    return {'chart': dict(doc.get('chart') or {}), 'axes': dict(doc.get('axes') or {})}


def style_of(form: Mapping[str, Any]) -> Dict[str, Any]:
    """Сетка графика и жирный/курсив подписей осей из общих полей формы; пустые поля не передаются."""
    whole = parse_style(form.get('fmt_style'))       # полная панель «Формат»: те же поля, что у «Любого графика»
    raw = {key: form.get('fmt_' + key) for key in STYLE_CHART}
    if raw['legend_columns'] in (0, '0'):
        raw['legend_columns'] = None    # 0 = «авто»
    chart = clean_chart({**whole['chart'], **{k: v for k, v in raw.items() if v not in (None, '')}})
    own = {key: form.get('fmt_axis_' + key if key.startswith('title') else 'fmt_' + key) for key in STYLE_TEXT}
    text = clean_axis({**whole['axes'], **{k: v for k, v in own.items() if v not in (None, '')}}, 'общие')
    out: Dict[str, Any] = {}
    if chart:
        out['chart'] = chart
    if text:
        out['text'] = text
    return out


def _merged_style(old: Any, style: Mapping[str, Any]) -> Dict[str, Any]:
    """Оформление графика: прежнее (от конструктора) + общие поля выгрузки (они сильнее); flags подписей — на оси X, Y и Y2."""
    out = dict(old or {})
    out['chart'] = {**(out.get('chart') or {}), **style.get('chart', {})}
    axes = {name: dict(spec) for name, spec in (out.get('axes') or {}).items()}
    for name in ('x', 'y', 'y2'):
        axes[name] = {**axes.get(name, {}), **style.get('text', {})}
    out['axes'] = axes
    return out


def configs(form: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Настройки по модулям: общие + правила наборов данных этого модуля; ключ ``'*'`` — общие для модулей без правил.
    Ошибки значений — до построения графиков."""
    base = common(form)
    found: Dict[str, Dict[str, Any]] = {}
    for key, value in form.items():
        if not key.startswith('fmt_'):
            continue
        for suffix, field, parse in (('_series', 'series', parse_series), ('_axes', 'axes', parse_axes)):
            if key.endswith(suffix) and len(key) > len('fmt_') + len(suffix):
                module, parsed = key[len('fmt_'):-len(suffix)], parse(value)
                if parsed:
                    found.setdefault(module, dict(base))[field] = parsed
    if base:
        found['*'] = base
    return found


def for_module(found: Mapping[str, Dict[str, Any]], module: str) -> Dict[str, Any]:
    return dict(found.get(module) or found.get('*') or {})


def apply(figure, cfg: Mapping[str, Any]):
    """Копия графика с оформлением из ``cfg``."""
    fig = copy.deepcopy(figure)
    meta = dict(fig.layout.meta) if isinstance(fig.layout.meta, dict) else {}
    look: Dict[str, Any] = {f: str(cfg[f]) for f in ('title', 'angle', 'legend') if f in cfg}
    if cfg.get('axes'):
        look['axes'] = cfg['axes']
    if look:
        meta['format'] = look
    if cfg.get('style'):
        meta['style'] = _merged_style(meta.get('style'), cfg['style'])
    if look or cfg.get('style'):
        fig.layout.meta = meta
    rules = cfg.get('series', [])
    for trace in fig.data:
        line = trace.type in (None, 'scatter')
        mode = (trace.mode or '') if line else ''     # у столбцов и ящиков поля ``mode`` нет: цвет и скрытие к ним применяются, толщина и маркеры — нет
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
        _look(trace, [r['look'] for r in rules if r['match'] in name and r.get('look')], own)
        if own:
            tmeta = dict(trace.meta) if isinstance(trace.meta, dict) else {}
            tmeta['own'] = sorted(own)
            trace.meta = tmeta
    return fig


def _look(trace, looks: List[Dict[str, Any]], own: set) -> None:
    """Вид ряда из правил (штрих, маркер, прозрачность, подписи, штриховка, имя в легенде) — теми же значениями, что в ``render.py``."""
    if not looks:
        return
    from .render import LOOK_DASH, SYMBOLS, labels_meta
    look: Dict[str, Any] = {}
    for one in looks:
        look.update(one)
    if trace.type in (None, 'scatter'):
        if 'dash' in look:
            trace.line.dash = LOOK_DASH[look['dash']]
        marked = 'markers' in (trace.mode or '')
        if marked and ('shape' in look or 'hollow' in look):
            symbol = str(trace.marker.symbol or 'circle').replace('-open', '')
            symbol = SYMBOLS[look['shape']] if 'shape' in look else symbol
            trace.marker.symbol = symbol + ('-open' if look.get('hollow') else '')
        if marked and 'markerColor' in look:
            trace.marker.color = look['markerColor']
        if marked and ('marker_border' in look or 'marker_border_width' in look):
            trace.marker.line = {'color': look.get('marker_border') or look.get('markerColor') or trace.marker.color,
                                 'width': look.get('marker_border_width', 1)}
        if 'opacity' in look:
            trace.opacity = look['opacity']
            own.add('alpha')
    tmeta = dict(trace.meta) if isinstance(trace.meta, dict) else {}
    tmeta.update(labels_meta(look))
    tmeta.update({k: look[k] for k in ('hatch', 'hatch_color') if k in look})
    if tmeta != (trace.meta if isinstance(trace.meta, dict) else {}):
        trace.meta = tmeta
    if look.get('legend_name'):
        trace.name = look['legend_name']
