"""Единая модель оформления графика: ряд, ось, график. Пустое поле — «авто» (поле в словаре не появляется).

Модель одна для конструктора, «Любого графика», вида с экрана и (дальше) темы проекта и типа графика: документ
``{'chart': {...}, 'axes': {'x': {...}, 'y': {...}}, 'series': {ключ ряда: {...}}}`` (``clean_format``), уровни складываются
``merge_formats`` (последний главнее, по полям), на график накладывается ``apply_format``. Старые места хранения переводятся
в документ функциями ``format_from_*``; сами старые поля не меняются — старые проекты и макеты открываются как раньше.

Хранится в макете (``layout.series[].look``, ``layout.axis_style``, ``layout.chart_style``), ложится в ``Series.look``, ``Axis.style``
и ``Chart.style`` и действует одинаково на экране (``web/src/ChartView.tsx``) и в выгрузке (``atlas/render.py``,
``atlas/engine/core/export_style.py``). Ошибка значения — ``ParamError`` с понятным текстом, неизвестные поля отбрасываются.
Шрифты — из набора выгрузки (``atlas.engine.core.fonts.FONTS``).
"""
from __future__ import annotations

import copy
import dataclasses
import re
from typing import Any, Iterable, Mapping

import pandas as pd

from .contract import Axis, Chart, Note, ParamError, Series

FONTS = ('default', 'times', 'arial_narrow', 'calibri')
SHAPES = ('circle', 'square', 'diamond', 'triangle', 'plus', 'x', 'star')
DASHES = ('solid', 'dash', 'dot', 'dashdot', 'longdash')
LEGENDS = ('bottom', 'top', 'right', 'left', 'hide')
GRIDS = ('both', 'h', 'v', 'none')
MINOR_GRIDS = ('show', 'hide')
ALIGNS = ('left', 'center', 'right')
DATE_FORMATS = ('dd.MM.yyyy', 'MM.yyyy', 'yyyy', 'dd.MM')
TICKS = ('out', 'in', 'cross', 'none')                       # деления оси: наружу, внутрь, пересекают, нет (как в Excel)
UNITS = ('thousands', 'millions', 'billions')               # единицы отображения: подписи делятся на 10³, 10⁶, 10⁹
TITLE_PLACES = ('end', 'middle')                            # название оси Y: над осью или вдоль оси
ERROR_MODES = ('percent', 'abs')                  # погрешность: в процентах от значения или абсолютная
ERROR_STYLES = ('bars', 'band')                   # усы у каждой точки или две граничные линии
HATCHES = ('diag', 'back', 'cross', 'grid', 'dots', 'horizontal', 'vertical')   # штриховка столбцов для чёрно-белой печати
TRENDS = ('linear', 'poly', 'log', 'power', 'exp', 'moving')   # вид линии тренда
LABEL_PLACES = ('top', 'bottom', 'left', 'right', 'inside', 'center')
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
    'title_align': 'выравнивание заголовка', 'text_color': 'цвет текста', 'grid_width': 'толщина сетки',
    'minor_grid': 'доп. линии сетки', 'minor_grid_color': 'цвет доп. линий', 'minor_grid_width': 'толщина доп. линий',
    'title_bold': 'жирный', 'title_italic': 'курсив', 'tick_bold': 'жирные подписи', 'tick_italic': 'курсивные подписи',
    'marker_border': 'граница маркера', 'marker_border_width': 'толщина границы маркера', 'hollow': 'полый маркер',
    'label_position': 'положение подписей данных', 'label_decimals': 'знаков в подписях данных', 'label_size': 'размер подписей данных',
    'legend_name': 'имя в легенде', 'ticks': 'основные деления', 'minor_ticks': 'доп. деления', 'line': 'линия оси',
    'line_color': 'цвет линии оси', 'line_width': 'толщина линии оси', 'label_rotate': 'поворот подписей', 'units': 'единицы отображения',
    'title_place': 'положение названия', 'minor_step': 'доп. шаг', 'cross': 'пересечение', 'subtitle': 'подзаголовок',
    'subtitle_size': 'размер подзаголовка', 'legend_columns': 'колонок легенды', 'legend_border': 'рамка легенды',
    'legend_background': 'фон легенды', 'grid_dash': 'штрих сетки', 'minor_grid_dash': 'штрих доп. линий',
    'border_color': 'рамка рисунка', 'border_width': 'толщина рамки рисунка', 'plot_border_color': 'рамка области построения',
    'plot_border_width': 'толщина рамки области построения',
}

LOOK = {'color': 'color', 'line': 'bool', 'width': ('num', 0.5, 12), 'dash': DASHES, 'marker': 'bool', 'shape': SHAPES,
        'size': ('num', 2, 24), 'markerColor': 'color', 'opacity': ('num', 0.05, 1), 'valueLabels': 'bool',
        # модель v2: граница маркера, полый маркер, подписи данных, имя в легенде
        'marker_border': 'color', 'marker_border_width': ('num', 0, 6), 'hollow': 'bool',
        'label_position': LABEL_PLACES, 'label_decimals': ('int', 0, 8), 'label_size': ('num', 5, 30), 'legend_name': 'text',
        # линия тренда ряда (atlas/trend.py): вид, степень полинома, окно скользящего, подпись с уравнением и R², цвет и толщина
        'trend': TRENDS, 'trend_order': ('int', 2, 6), 'trend_period': ('int', 2, 60), 'trend_label': 'bool', 'trend_color': 'color',
        'trend_width': ('num', 0.5, 12),
        # штриховка столбцов (чёрно-белая печать): вид и цвет штриха
        'hatch': HATCHES, 'hatch_color': 'color',
        # погрешность (доверительный интервал): вид задания, величина, усы или граничные линии
        'err_mode': ERROR_MODES, 'err_value': ('num', 0, 1e9), 'err_style': ERROR_STYLES}
AXIS_FMT = {'color': 'color', 'decimals': ('int', 0, 8), 'date_format': DATE_FORMATS, 'font': FONTS, 'tick_size': ('num', 5, 30),
            'title_size': ('num', 5, 30), 'title_bold': 'bool', 'title_italic': 'bool', 'tick_bold': 'bool', 'tick_italic': 'bool',
            # модель v2: деления, линия оси, поворот подписей, единицы отображения, положение названия
            'ticks': TICKS, 'minor_ticks': TICKS, 'line': 'bool', 'line_color': 'color', 'line_width': ('num', 0.2, 6),
            'label_rotate': ('num', -90, 90), 'units': UNITS, 'title_place': TITLE_PLACES}
AXIS_STYLE_KEYS = tuple(k for k in AXIS_FMT if k != 'color')     # что из настроек оси ложится в ``Axis.style`` (цвет — в ``Axis.color``)
AXIS_SCALE_KEYS = ('min', 'max', 'step', 'minor_step', 'cross', 'break_from', 'break_to')  # границы и деления: текст, проверяется по виду оси (``bound``)
CHART_FMT = {'title_font': FONTS, 'title_size': ('num', 6, 48), 'title_bold': 'bool', 'title_color': 'color', 'title_align': ALIGNS,
             'font': FONTS, 'text_color': 'color', 'legend': LEGENDS, 'legend_font': FONTS, 'legend_size': ('num', 5, 30),
             'grid': GRIDS, 'grid_color': 'color', 'grid_width': ('num', 0.2, 4), 'minor_grid': MINOR_GRIDS, 'minor_grid_color': 'color',
             'minor_grid_width': ('num', 0.2, 4), 'background': 'color', 'plot_background': 'color',
             # модель v2: подзаголовок, легенда (колонки, рамка, фон), штрих сетки, рамки рисунка и области построения
             'subtitle': 'text', 'subtitle_size': ('num', 6, 48), 'legend_columns': ('int', 1, 12), 'legend_border': 'bool',
             'legend_background': 'color', 'grid_dash': DASHES, 'minor_grid_dash': DASHES, 'border_color': 'color',
             'border_width': ('num', 0.2, 6), 'plot_border_color': 'color', 'plot_border_width': ('num', 0.2, 6)}


def clean_look(raw: Any, index: int) -> dict[str, Any]:
    """Вид ряда: цвет, линия (показать, толщина, стиль), маркеры (показать, форма, размер, цвет), прозрачность."""
    return _fill(raw, f'Ряд {index}', LOOK)


ANNOTATIONS = 30
ANNOTATION_KINDS = ('hline', 'vline', 'hband', 'vband', 'text')
ANNOTATION = {'kind': ANNOTATION_KINDS, 'value': 'text', 'to': 'text', 'x': 'text', 'y': 'text', 'text': 'text', 'color': 'color',
              'width': ('num', 0.5, 8), 'dash': DASHES, 'size': ('num', 6, 36)}
ANNOTATION_NEEDS = {'hline': ('value',), 'vline': ('value',), 'hband': ('value', 'to'), 'vband': ('value', 'to'), 'text': ('x', 'y', 'text')}
ANNOTATION_TITLES = {'hline': 'линия уровня', 'vline': 'вертикальная линия', 'hband': 'горизонтальная полоса', 'vband': 'вертикальная полоса', 'text': 'подпись'}
LABELS.update({'value': 'значение', 'to': 'до', 'x': 'X', 'y': 'Y', 'text': 'текст', 'kind': 'вид', 'size': 'размер'})


def clean_annotations(raw: Any) -> list[dict[str, Any]]:
    """Аннотации графика: линии уровня, полосы и подписи в координатах данных (по основной оси Y; X — число или дата).
    Значения хранятся текстом, как границы осей; проверяются при рисовании (не разобранное пропускается)."""
    if raw is None or raw == []:
        return []
    if not isinstance(raw, (list, tuple)) or len(raw) > ANNOTATIONS:
        raise ParamError(f'Аннотации: список, не больше {ANNOTATIONS}')
    out = []
    for i, item in enumerate(raw, 1):
        a = _fill(item, f'Аннотация {i}', ANNOTATION)
        if 'kind' not in a:
            raise ParamError(f'Аннотация {i}: не задан вид ({", ".join(ANNOTATION_KINDS)})')
        missing = [LABELS.get(k, k) for k in ANNOTATION_NEEDS[a['kind']] if not a.get(k)]
        if missing:
            raise ParamError(f'Аннотация {i} ({ANNOTATION_TITLES[a["kind"]]}): не заполнено — {", ".join(missing)}')
        out.append(a)
    return out


def clean_chart(raw: Any) -> dict[str, Any]:
    """Настройки графика: заголовок, шрифты, легенда, сетка, фон, аннотации."""
    out = _fill(raw, 'График', CHART_FMT)
    notes = clean_annotations(raw.get('annotations')) if isinstance(raw, Mapping) else []
    if notes:
        out['annotations'] = notes
    return out


def clean_axis(raw: Any, name: str) -> dict[str, Any]:
    """Настройки оси: границы, шаг, логарифм, обратное направление (необработанные, см. ``bound``) и оформление."""
    src = raw if isinstance(raw, Mapping) else {}
    out = _fill(src, f'Ось {name}', AXIS_FMT)
    for key in AXIS_SCALE_KEYS:
        if not _empty(src.get(key)):
            out[key] = str(src[key]).strip()
    if ('break_from' in out) != ('break_to' in out):      # разрыв задан не до конца: пока не применяется, чтобы недописанное не мешало сохранению
        out.pop('break_from', None)
        out.pop('break_to', None)
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


def style_axis(axis: Axis, spec: Mapping[str, Any], title: str, values: Iterable[pd.Series], notes: list[Note]) -> None:
    """Ручные границы, шаги, пересечение, логарифм, направление и оформление оси (меняет ``axis``);
    то, что к оси не подходит, пропускается с заметкой. Общая для конструктора, «Любого графика» и ``apply_format``."""
    time = axis.scale == 'time'
    if 'color' in spec:
        axis.color = spec['color']
    axis.style = {**(axis.style or {}), **{k: v for k, v in spec.items() if k in AXIS_STYLE_KEYS}}
    if spec.get('inverse'):
        axis.inverse = True
    if spec.get('from_zero') and axis.scale == 'value':
        axis.from_zero = True
    low = bound(spec['min'], f'Ось {title}, минимум', time) if 'min' in spec else None
    high = bound(spec['max'], f'Ось {title}, максимум', time) if 'max' in spec else None
    if low is not None and high is not None and low >= high:
        raise ParamError(f'Ось {title}: минимум должен быть меньше максимума')
    if spec.get('log'):
        positive = all((v.dropna() > 0).all() for v in values if not pd.api.types.is_datetime64_any_dtype(v))
        if time:
            notes.append(Note(f'Ось {title}: логарифмическая шкала не применяется к датам.'))
        elif not positive or (low is not None and low <= 0):
            notes.append(Note(f'Ось {title}: логарифмическая шкала возможна только для положительных значений — оставлена линейная.'))
        else:
            axis.scale = 'log'
    axis.minimum, axis.maximum = low, high
    for key, what in (('step', 'шаг'), ('minor_step', 'доп. шаг')):
        if key not in spec:
            continue
        if axis.scale not in ('value', 'log'):
            notes.append(Note(f'Ось {title}: {what} делений задаётся для чисел; у дат деления подбираются сами.'))
            continue
        value = bound(spec[key], f'Ось {title}, {what}', False)
        if value <= 0:
            raise ParamError(f'Ось {title}, {what}: больше нуля')
        if key == 'step':
            axis.step = value
        else:
            axis.style['minor_step'] = value
    if 'break_from' in spec and 'break_to' in spec:      # разрыв оси: диапазон между значениями не показывается (экран и файлы)
        if axis.scale not in ('value', 'time'):
            notes.append(Note(f'Ось {title}: разрыв оси возможен у числовой оси и оси дат — на логарифмической и категорной не применён.'))
        else:
            lo = bound(spec['break_from'], f'Ось {title}, разрыв от', time)
            hi = bound(spec['break_to'], f'Ось {title}, разрыв до', time)
            if lo >= hi:
                raise ParamError(f'Ось {title}: начало разрыва должно быть меньше его конца')
            axis.style['break_lo'], axis.style['break_hi'] = lo, hi
    if 'cross' in spec:          # где ось пересекает соседнюю: значение этой оси (число или дата)
        axis.style['cross'] = bound(spec['cross'], f'Ось {title}, пересечение', time)


# --- Документ оформления (модель v2) ---------------------------------------------------------------------------------

FORMAT_PARTS = ('chart', 'axes', 'series')
AXIS_NAMES = ('x', 'y', 'y2', 'y3', 'y4', 'y5')


def series_key(s: Series) -> str:
    """Ключ ряда в документе — тот же, что на экране (``seriesLookKey``): группа или имя, и вид ряда."""
    return f'{s.group or s.name}|{s.kind}'


def clean_format(raw: Any) -> dict[str, Any]:
    """Проверенный документ оформления ``{'chart', 'axes', 'series'}``: пустые части не появляются, ошибка — ``ParamError``."""
    src = raw if isinstance(raw, Mapping) else {}
    out: dict[str, Any] = {}
    chart = clean_chart(src.get('chart'))
    axes = clean_axes(src.get('axes'))
    looks = src.get('series') if isinstance(src.get('series'), Mapping) else {}
    series = {}
    for i, (key, look) in enumerate(looks.items(), 1):
        one = clean_look(look, i)
        if one:
            series[str(key)[:300]] = one
    for name, part in (('chart', chart), ('axes', axes), ('series', series)):
        if part:
            out[name] = part
    return out


def merge_formats(*docs: Mapping[str, Any] | None) -> dict[str, Any]:
    """Уровни оформления (тема проекта → тип графика → график): поле более позднего уровня главнее, остальное наследуется."""
    out: dict[str, Any] = {}
    for doc in docs:
        if not doc:
            continue
        if doc.get('chart'):
            out['chart'] = {**out.get('chart', {}), **doc['chart']}
        for part in ('axes', 'series'):
            for key, value in (doc.get(part) or {}).items():
                out.setdefault(part, {})[key] = {**out.get(part, {}).get(key, {}), **value}
    return copy.deepcopy(out)


def _numbers(values: Any) -> pd.Series | None:
    """Числа ряда для проверки логарифма; у ящиков и прочих составных значений проверки нет."""
    try:
        return pd.to_numeric(pd.Series(list(values), dtype='object'), errors='coerce')
    except (TypeError, ValueError):
        return None


def apply_format(chart: Chart, doc: Mapping[str, Any] | None, notes: list[Note] | None = None) -> Chart:
    """Копия графика с оформлением документа: ``Chart.style``, ``Axis`` (через ``style_axis``) и ``Series.look`` по ключу ряда.
    Расчёт модуля не меняется; ось, которой у графика нет, пропускается."""
    if not doc:
        return chart
    notes = notes if notes is not None else []
    out = dataclasses.replace(chart, style={**chart.style, **doc.get('chart', {})}) if doc.get('chart') else chart
    names = set(out.axis_names()) | {'x'}
    for name, spec in (doc.get('axes') or {}).items():
        if name not in names:
            continue
        axis = dataclasses.replace(out.x if name == 'x' else out.axis_at(name), style=dict((out.x if name == 'x' else out.axis_at(name)).style))
        values = [v for s in out.series if name != 'x' and (s.axis or 'y') == name for v in [_numbers(s.y)] if v is not None]
        style_axis(axis, spec, 'X' if name == 'x' else name.upper(), values, notes)
        out = dataclasses.replace(out, **{name: axis})
    looks = doc.get('series') or {}
    if looks:
        series = []
        for s in out.series:
            own = looks.get(series_key(s))
            if own:
                look = {**(s.look or {}), **own}
                s = dataclasses.replace(s, look=look, **({'opacity': look['opacity']} if 'opacity' in look else {}))
            series.append(s)
        out = dataclasses.replace(out, series=series + _trends(series, notes) + _errors(series))
    return out


def _errors(series: list[Series]) -> list[Series]:
    """Интервал погрешности рядов с ``err_value``: усы (отрезок вверх и вниз от точки) или две граничные линии. Задаётся вручную
    инженером в процентах от значения или абсолютно; ряд для экрана и файлов строится одинаково (``web/src/trend.ts``)."""
    out = []
    for s in series:
        look = s.look or {}
        value = float(look.get('err_value') or 0)
        if value <= 0 or s.kind not in ('points', 'line') or s.name.startswith(('Тренд: ', 'Погрешность: ')) \
                or any(t.name.startswith('Погрешность: ' + s.name) for t in series):
            continue
        percent = look.get('err_mode', 'percent') == 'percent'
        pairs = []
        for x, y in zip(s.x, s.y):
            if isinstance(y, bool) or not isinstance(y, (int, float)) or y != y:
                continue
            pairs.append((x, y, abs(y) * value / 100 if percent else value))
        if not pairs:
            continue
        tip = f'{s.name}: ±{value:g} %' if percent else f'{s.name}: ±{value:g}'
        common = dict(kind='line', group=s.group or s.name, legend=False, axis=s.axis, color=look.get('color') or s.color, tooltip=tip)
        if look.get('err_style', 'bars') == 'band':
            for sign, word in ((1, 'верх'), (-1, 'низ')):
                out.append(Series(name=f'Погрешность: {s.name} ({word})', x=[p[0] for p in pairs], y=[p[1] + sign * p[2] for p in pairs],
                                  dash='dot', width=1.0, **common))
        else:
            xs, ys = [], []
            for x, y, e in pairs:
                xs += [x, x, x]
                ys += [y - e, y + e, None]
            out.append(Series(name=f'Погрешность: {s.name}', x=xs, y=ys, width=1.2, **common))
    return out


def _trends(series: list[Series], notes: list[Note]) -> list[Series]:
    """Линии тренда рядов, у которых в виде задан ``trend``; ряд без подходящих точек пропускается с пометкой."""
    from . import trend as trendlib
    out = []
    for s in series:
        look = s.look or {}
        kind = look.get('trend')
        if not kind or s.kind not in ('points', 'line') or s.name.startswith('Тренд: ') or any(t.name.startswith('Тренд: ' + s.name) for t in series):
            continue
        got = trendlib.fit(kind, s.x, s.y, int(look.get('trend_order', 2)), int(look.get('trend_period', 5)))
        if got is None:
            notes.append(Note(f'Тренд ряда «{s.name}» не построен: мало точек или вид не подходит к значениям (логарифм — x > 0, степень и экспонента — x и y > 0).'))
            continue
        out.append(Series(name=trendlib.label(s.name, got, bool(look.get('trend_label'))), x=got['x'], y=got['y'], kind='line', group=s.group or s.name,
                          dash='dash', width=float(look.get('trend_width', 0)) or max(s.width, 1.5), legend=False, axis=s.axis,
                          color=look.get('trend_color') or s.color, tooltip=trendlib.label(s.name, got, True)))
    return out


def format_from_layout(layout: Mapping[str, Any] | None) -> dict[str, Any]:
    """Макет конструктора → документ: оформление графика и осей. Вид рядов остаётся в рядах макета (ряд конструктора
    не имеет постоянного ключа до расчёта)."""
    src = layout if isinstance(layout, Mapping) else {}
    return clean_format({'chart': src.get('chart_style'), 'axes': src.get('axis_style')})


def format_from_view(view: Mapping[str, Any] | None) -> dict[str, Any]:
    """Вид с экрана (``view.looks`` — окно «Настройка») → документ; неверный вид из браузера не ломает выгрузку."""
    looks = view.get('looks') if isinstance(view, Mapping) and isinstance(view.get('looks'), Mapping) else {}
    out = {}
    for i, (key, look) in enumerate(looks.items(), 1):
        try:
            one = clean_look(look, i)
        except ParamError:
            continue
        if one:
            out[str(key)] = one
    return {'series': out} if out else {}


def format_from_any(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Настройки «Любого графика» (``chart`` без заголовка, ``axes``, ``view.looks``) → документ."""
    src = settings if isinstance(settings, Mapping) else {}
    chart = {k: v for k, v in (src.get('chart') or {}).items() if k != 'title'} if isinstance(src.get('chart'), Mapping) else {}
    return merge_formats(clean_format({'chart': chart, 'axes': src.get('axes')}), format_from_view(src.get('view')))


# --- Оформление в проекте: тема и типы графиков (настройка ``chart_formats``) ------------------------------------------

STORE_SERIES = 3000            # рядов со своим видом в теме проекта
STORE_TYPES = 200              # разделов (типов графиков) со своим оформлением
STORE_TEMPLATES = 100          # шаблонов оформления в проекте


def clean_store(raw: Any) -> dict[str, Any]:
    """Настройка проекта ``chart_formats = {'theme': документ, 'types': {раздел: документ}}``: тема действует на все графики,
    тип — на графики одного раздела (идёт после темы, главнее её). Ошибка поля — ``ParamError`` с понятным текстом."""
    if not isinstance(raw, Mapping) or set(raw) - {'theme', 'types', 'templates'}:
        raise ParamError('Оформление графиков: нужен словарь {theme, types, templates}')
    out: dict[str, Any] = {}
    theme = clean_format(raw.get('theme'))
    if len(theme.get('series', {})) > STORE_SERIES:
        raise ParamError(f'Оформление графиков: не больше {STORE_SERIES} рядов в теме проекта')
    if theme:
        out['theme'] = theme
    types = raw.get('types', {})
    if types is None:
        types = {}
    if not isinstance(types, Mapping) or len(types) > STORE_TYPES:
        raise ParamError(f'Оформление графиков: типы — словарь, не больше {STORE_TYPES}')
    kinds = {str(k)[:80]: d for k, v in types.items() for d in [clean_format(v)] if d}
    if kinds:
        out['types'] = kinds
    templates = raw.get('templates')
    templates = {} if templates is None else templates
    if not isinstance(templates, Mapping) or len(templates) > STORE_TEMPLATES:
        raise ParamError(f'Оформление графиков: шаблонов не больше {STORE_TEMPLATES}')
    named = {name: d for k, v in templates.items() for name in [str(k).strip()[:60]] for d in [clean_format(v)] if name and d}
    if named:
        out['templates'] = named        # шаблоны оформления: {имя: документ}; на графики сами не действуют, только переносятся на них
    return out


def format_of(settings: Mapping[str, Any] | None, module: str) -> dict[str, Any]:
    """Оформление графиков раздела по настройкам проекта: тема, затем тип (раздел)."""
    store = (settings or {}).get('chart_formats') or {}
    if not isinstance(store, Mapping):
        return {}
    return merge_formats(store.get('theme'), (store.get('types') or {}).get(module))


def apply_store(result: Any, settings: Mapping[str, Any] | None, module: str) -> Any:
    """Копия результата раздела с оформлением проекта на каждом графике; без оформления — тот же объект.
    Заметки о том, что не применилось (логарифм у неположительных и т. п.), добавляются один раз."""
    doc = format_of(settings, module)
    if not doc or not getattr(result, 'charts', None):
        return result
    notes: list[Note] = []
    charts = []
    for c in result.charts:
        try:
            charts.append(apply_format(c, doc, notes))
        except ParamError as e:       # граница не подошла к оси этого графика: график остаётся как есть
            notes.append(Note(f'Оформление проекта не применено к «{c.title}»: {e}'))
            charts.append(c)
    seen = {n.text for n in result.notes}
    extra = []
    for n in notes:
        if n.text not in seen:
            seen.add(n.text)
            extra.append(n)
    return dataclasses.replace(result, charts=charts, notes=[*result.notes, *extra])
