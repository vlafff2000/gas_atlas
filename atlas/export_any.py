"""Экспорт «Любой график»: реестр графиков всех разделов и выгрузка одного графика с полной ручной настройкой.

Реестр — это результат модуля (``Result.charts``) при выбранных параметрах: графики берутся оттуда же, где их видит инженер на экране,
поэтому список не расходится с программой, а новый модуль попадает в него сам. Настройки выгрузки (``settings``) накладываются на копию
графика и проверяются так же, как вид из конструктора (``atlas/chart_style.py``); неверное поле — ``ParamError`` с понятным текстом.
Главное слово за инженером: каждое поле необязательно, пустое — «авто» (как задал модуль).
"""
from __future__ import annotations

import dataclasses
from typing import Any, Mapping

from . import chart_special, chart_view, render
from .chart_style import FONTS, bound, clean_axes, clean_chart
from .contract import Chart, Note, ParamError

DPIS = (150, 200, 250, 300, 600, 1200)
FORMATS = ('png', 'svg', 'pdf', 'xlsx', 'csv')
LOOKS = ('default', 'excel')
SIZES = {'a4-width': (170, None), 'a4-half': (170, 100), 'a4-page': (190, 120), 'a4-land': (270, 180), '16x9': (254, 143),
         '4x3': (240, 180), 'column': (85, 65), 'square': (150, 150)}


def kind_of(chart: Chart) -> str:
    """Тип графика для реестра: от него зависит, какие настройки вида действуют (обычный график рисуется общим экспортёром)."""
    if chart.heat is not None:
        return 'heat'
    if chart.strips is not None:
        return 'strips'
    if any(s.segments is not None for s in chart.series):
        return 'stack'
    return 'chart'


def describe(chart: Chart) -> dict[str, Any]:
    return {'id': chart.id, 'title': chart.title, 'kind': kind_of(chart), 'table': chart.table is not None,
            'series': len(chart.series), 'axes': chart.axis_names(), 'special': chart_special.is_special(chart)}


def _number(raw: Any, what: str, low: float, high: float) -> float | None:
    if raw in (None, '', 0):
        return None
    try:
        value = float(str(raw).replace(',', '.'))
    except ValueError:
        raise ParamError(f'{what}: нужно число') from None
    if not low <= value <= high:
        raise ParamError(f'{what}: от {low:g} до {high:g}')
    return value


def settings_of(raw: Any) -> dict[str, Any]:
    """Проверенные настройки выгрузки одного графика; размеры — мм (пресет ``size`` даёт ширину и высоту, ручные значения главнее)."""
    src = raw if isinstance(raw, Mapping) else {}
    fmt = str(src.get('format') or 'png')
    if fmt not in FORMATS:
        raise ParamError('Формат графика: ' + ', '.join(FORMATS))
    try:
        dpi = int(src.get('dpi') or 300)
    except (TypeError, ValueError):
        raise ParamError('DPI должен быть числом') from None
    if dpi not in DPIS:
        raise ParamError('DPI: ' + ', '.join(map(str, DPIS)))
    look = str(src.get('look') or 'default')
    if look not in LOOKS:
        raise ParamError('Вид графика: обычный или как в Excel')
    preset = SIZES.get(str(src.get('size') or ''), (None, None))
    width = _number(src.get('width'), 'Ширина, мм', 80, 300) or preset[0] or 220
    height = _number(src.get('height'), 'Высота, мм', 40, 400) or preset[1]
    font = str(src.get('font') or 'default')
    if font not in FONTS:
        raise ParamError('Шрифт: ' + ', '.join(FONTS))
    size = _number(src.get('font_size'), 'Размер шрифта, пт', 5, 30)
    view = src.get('view') if isinstance(src.get('view'), Mapping) else {}
    chart = dict(src.get('chart')) if isinstance(src.get('chart'), Mapping) else {}
    title = str(chart.pop('title', '') or '').strip()[:300]
    tsrc = src.get('table') if isinstance(src.get('table'), Mapping) else {}
    table = {'show': tsrc.get('show') is not False,
             'font_size': _number(tsrc.get('font_size'), 'Таблица, размер шрифта, пт', 5, 24),
             'row': _number(tsrc.get('row'), 'Таблица, высота строки (1 — как есть)', 0.5, 3)}
    segment = _number(src.get('segment_size'), 'Подписи в столбцах, пт', 5, 30)
    labels = src.get('labels') if isinstance(src.get('labels'), Mapping) else {}
    return {'format': fmt, 'dpi': dpi, 'look': look, 'width': width, 'height': height, 'font': font, 'font_size': size,
            'sized': bool(_number(src.get('width'), 'Ширина, мм', 80, 300) or preset[0]), 'table': table, 'segment_size': segment,
            'view': dict(view), 'chart': clean_chart(chart), 'title': title, 'axes': clean_axes(src.get('axes')),
            'labels': {k: str(v).strip()[:200] for k, v in labels.items() if k in chart_view.AXES + ('x',) and str(v).strip()}}


def prepared(chart: Chart, s: Mapping[str, Any]) -> tuple[Chart, list[Note]]:
    """Копия графика с видом экрана (ряды, диапазоны), ручными осями, оформлением и заголовком; сам расчёт модуля не меняется."""
    from .modules.builder import _style_axis
    notes: list[Note] = []
    out = chart_view.apply_view(chart, s['view'])
    out = dataclasses.replace(out, style={**out.style, **s['chart']}, title=s['title'] or out.title)
    names = set(out.axis_names()) | {'x'}
    for name, spec in s['axes'].items():
        if name not in names:
            continue
        axis = dataclasses.replace(out.x if name == 'x' else out.axis_at(name))
        values = []       # логарифм по значениям не проверяется: ``_style_axis`` сверяет положительность только по переданным рядам
        _style_axis(axis, spec, 'X' if name == 'x' else name.upper(), values, notes)
        out = dataclasses.replace(out, **{name: axis})
    for name, label in s['labels'].items():
        if name in names:
            axis = dataclasses.replace(out.x if name == 'x' else out.axis_at(name), label=label, unit='')
            out = dataclasses.replace(out, **{name: axis})
    return out, notes


def export(chart: Chart, raw_settings: Any) -> tuple[bytes, str, str, list[str]]:
    """Файл одного графика и заметки о том, что не применилось. Возвращает (содержимое, имя, тип, заметки)."""
    from atlas.engine.core.export import figure_bytes
    s = settings_of(raw_settings)
    out, notes = prepared(chart, s)
    if s['format'] in ('xlsx', 'csv'):
        content, name, mime = render.chart_file(out, s['format'], s['dpi'])
        return content, name, mime, [n.text for n in notes]
    if chart_special.is_special(out):
        legend = out.style.get('legend')
        opts = {'width_mm': s['width'] if s['sized'] else None, 'height_mm': s['height'] if s['sized'] else None,
                'font': s['font'], 'font_size': s['font_size'], 'legend': legend if legend in ('top', 'hide') else 'right' if legend else None,
                'table_show': s['table']['show'], 'table_font_size': s['table']['font_size'], 'table_row': s['table']['row'],
                'segment_size': s['segment_size']}
        content = chart_special.figure_file(out, s['format'], s['dpi'], opts)
        if out.heat is not None or out.strips is not None:
            notes.append(Note('Для тепловой карты и матрицы действуют размер рисунка, шрифт и заголовок; размер текста внутри задаёт сам график.'))
        return content, f'{render.safe_name(out.title)}.{s["format"]}', render.FORMATS[s['format']], [n.text for n in notes]
    content = figure_bytes(render.to_plotly(out), s['format'], s['dpi'], s['width'], s['height'], font=s['font'],
                           font_size=s['font_size'], look=s['look'])
    return content, f'{render.safe_name(out.title)}.{s["format"]}', render.FORMATS[s['format']], [n.text for n in notes]


def routes(projects, E, compute) -> list:
    """Маршруты вкладки «Любой график»; ``compute`` — расчёт модуля с общим кэшем (тот же, что у экрана и выгрузки графика раздела)."""
    import json
    from urllib.parse import quote

    from starlette.responses import Response
    from starlette.routing import Route

    from . import registry
    from .contract import MissingData

    def modules(request, body):
        """Все разделы, у которых могут быть графики, и готовы ли для них данные проекта."""
        data = projects.data(request.path_params['pid'])
        out = []
        for m in registry.modules().values():
            spec = m.spec
            missing = [k.label for k in spec.needs if k not in data or data[k].empty]
            out.append({'id': spec.id, 'title': spec.title, 'group': spec.group, 'order': spec.order, 'ready': not missing,
                        'missing': missing})
        return {'modules': out}

    def charts(request, body):
        module = registry.get(str(body.get('module') or ''))
        try:
            (result, _), _, _ = compute(module, request.path_params['pid'], body.get('params'), True)
        except MissingData as e:
            return {'charts': [], 'note': str(e)}
        return {'charts': [describe(c) for c in result.charts],
                'note': '' if result.charts else 'В этом разделе при выбранных параметрах графиков нет.'}

    def file(request, body):
        module = registry.get(str(body.get('module') or ''))
        (result, _), _, _ = compute(module, request.path_params['pid'], body.get('params'), True)
        chart = next((c for c in result.charts if c.id == body.get('chart')), None)
        if chart is None:
            return Response(json.dumps({'error': 'График не найден. Обновите список.'}, ensure_ascii=False), status_code=404,
                            media_type='application/json')
        content, name, mime, notes = export(chart, body.get('settings'))
        return Response(content, media_type=mime, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}",
                                                           'X-Atlas-Notes': quote(json.dumps(notes, ensure_ascii=False))})

    base = '/api/projects/{pid}/export/any'
    return [Route(base + '/modules', E(modules)), Route(base + '/charts', E(charts), methods=['POST']),
            Route(base + '/file', E(file), methods=['POST'])]
