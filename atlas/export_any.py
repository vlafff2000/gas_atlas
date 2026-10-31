"""Экспорт «Любой график»: реестр графиков всех разделов и выгрузка одного графика с полной ручной настройкой.

Реестр — это результат модуля (``Result.charts``) при выбранных параметрах: графики берутся оттуда же, где их видит инженер на экране,
поэтому список не расходится с программой, а новый модуль попадает в него сам. Настройки выгрузки (``settings``) накладываются на копию
графика и проверяются так же, как вид из конструктора (``atlas/chart_style.py``); неверное поле — ``ParamError`` с понятным текстом.
Главное слово за инженером: каждое поле необязательно, пустое — «авто» (как задал модуль).
"""
from __future__ import annotations

import dataclasses
import logging
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


def series_items(chart: Chart) -> list[dict[str, Any]]:
    """Ряды графика для настройки вида: ключ (тот же, что у экрана), имя, группа, вид и цвет, с которым ряд рисуется сейчас."""
    palette = render.group_colors(chart)
    out: dict[str, dict[str, Any]] = {}
    for s in chart.series:
        key = chart_view.series_key(s)
        if key not in out:
            color = (s.look or {}).get('color') or (render.series_color(s.color) if s.color else palette[s.group or s.name])
            out[key] = {'key': key, 'name': s.name, 'group': s.group or s.name, 'kind': s.kind, 'color': color}
    return list(out.values())


def describe(chart: Chart) -> dict[str, Any]:
    return {'items': series_items(chart), 'id': chart.id, 'title': chart.title, 'kind': kind_of(chart), 'table': chart.table is not None,
            'series': len(chart.series), 'axes': chart.axis_names(), 'special': chart_special.is_special(chart), 'facets': facets_of(chart),
            'range_key': range_key(chart),
            'labels': {name: (a.label + (f', {a.unit}' if a.unit else '')) for name in ['x', *chart.axis_names()]
                       for a in [chart.x if name == 'x' else chart.axis_at(name)] if a is not None}}


def range_key(chart: Chart) -> str:
    """Ключ ручных границ осей этого графика на экране (``rangeKey`` в ``web/src/ChartView.tsx``): заголовок и подписи осей Y."""
    return f'{chart.title}|{chart.y.label}|' + '|'.join(a.label for _, a in chart.right_axes())


def facets_of(chart: Chart) -> list[dict[str, Any]]:
    """Признаки рядов (период, сезон…), по которым на экране включают и выключают ряды: имя и значения в порядке появления."""
    out: dict[str, list[str]] = {}
    for s in chart.series:
        for name, value in (s.facets or {}).items():
            if value not in out.setdefault(name, []):
                out[name].append(value)
    return [{'name': k, 'values': v} for k, v in out.items()]


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
    angle = str(src.get('angle') or '')
    if angle and angle not in ('0', '30', '45', '60', '90'):
        raise ParamError('Подписи оси X: 0, 30, 45, 60 или 90 градусов')
    segment = _number(src.get('segment_size'), 'Подписи в столбцах, пт', 5, 30)
    cell = _number(src.get('cell_size'), 'Текст в ячейках, пт', 4, 30)
    filename = render.safe_name(str(src.get('filename') or '').strip()[:120]) if str(src.get('filename') or '').strip() else ''
    labels = src.get('labels') if isinstance(src.get('labels'), Mapping) else {}
    return {'format': fmt, 'dpi': dpi, 'look': look, 'width': width, 'height': height, 'font': font, 'font_size': size,
            'sized': bool(_number(src.get('width'), 'Ширина, мм', 80, 300) or preset[0]), 'table': table, 'segment_size': segment, 'cell_size': cell, 'angle': angle, 'filename': filename,
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
        if s['filename']:
            name = f'{s["filename"]}.{s["format"]}'
        return content, name, mime, [n.text for n in notes]
    if chart_special.is_special(out):
        legend = out.style.get('legend')
        opts = {'width_mm': s['width'] if s['sized'] else None, 'height_mm': s['height'] if s['sized'] else None,
                'font': s['font'], 'font_size': s['font_size'], 'legend': legend if legend in ('top', 'bottom', 'hide') else 'right' if legend else None,
                'table_show': s['table']['show'], 'table_font_size': s['table']['font_size'], 'table_row': s['table']['row'],
                'segment_size': s['segment_size'], 'cell_size': s['cell_size'], 'style': out.style, 'axes': s['axes'], 'labels': s['labels'],
                'angle': s['angle']}
        content = chart_special.figure_file(out, s['format'], s['dpi'], opts)
        return content, f'{s["filename"] or render.safe_name(out.title)}.{s["format"]}', render.FORMATS[s['format']], [n.text for n in notes]
    fig = render.to_plotly(out)
    if s['angle']:
        meta = dict(fig.layout.meta or {})
        fig.update_layout(meta={**meta, 'format': {**(meta.get('format') or {}), 'angle': s['angle']}})
    content = figure_bytes(fig, s['format'], s['dpi'], s['width'], s['height'], font=s['font'],
                           font_size=s['font_size'], look=s['look'])
    return content, f'{s["filename"] or render.safe_name(out.title)}.{s["format"]}', render.FORMATS[s['format']], [n.text for n in notes]


def routes(projects, E, compute) -> list:
    """Маршруты вкладки «Любой график»; ``compute`` — расчёт модуля с общим кэшем (тот же, что у экрана и выгрузки графика раздела)."""
    import json
    from urllib.parse import quote

    from starlette.responses import Response
    from starlette.routing import Route

    from . import registry
    from .contract import MissingData

    SAVED = 'builder-saved'      # не раздел, а макеты из библиотеки конструктора: каждый сохранённый макет — отдельный график

    def saved_charts(pid, params):
        from . import builder_library, well_filter
        flt, _ = well_filter.split(params)
        spec = registry.get('builder').spec
        data = projects.select(pid, spec.needs, spec.optional, flt)
        out, notes = [], []
        for item in builder_library.items_of(data.settings):
            chart, extra = builder_library.chart_of(data, item['layout'])
            if chart is None:
                notes.append(f'Макет «{item["name"]}»: рядов на графике нет.')
                continue
            out.append(dataclasses.replace(chart, id='layout-' + str(item['id']), title=chart.title or item['name']))
            notes += extra
        return out, notes

    SEP = '::'      # id графика в списке: «вид=значение&вид=значение::id» (пусто до «::» — виды по умолчанию)

    def variants_of(spec, params):
        """Все виды графиков раздела одним списком. Переключатели вида (chart_kind) идут по очереди во все свои значения; если они
        видны только в одном из режимов раздела (параметр, на который ссылается show_if), то так же обходится каждый режим.
        Возвращает [(переопределения параметров, подпись вида)]; первый — как задано по умолчанию."""
        base = spec.coerce(params)
        kinds = [p for p in spec.params if p.chart_kind and len(p.options) > 1]
        modes = []
        for name in dict.fromkeys(k for p in kinds for k in (p.show_if or {})):
            mode = next((p for p in spec.params if p.name == name and not p.chart_kind and p.kind == 'choice' and p.options), None)
            if mode is not None:
                modes.append(mode)
        combos = [({}, '')]
        for mode in modes:
            combos = [(over | {mode.name: o.value}, (label + ' · ' if label else '') + f'{mode.label}: {o.label}' if i else label)
                      for over, label in combos for i, o in enumerate(sorted(mode.options, key=lambda o: o.value != base.get(mode.name)))]
        out = []
        for over, label in combos:
            now = {**base, **over}
            out.append((over, label))
            for p in kinds:
                if p.show_if and any(now.get(k) != v for k, v in p.show_if.items()):
                    continue
                for o in p.options:
                    if o.value != now.get(p.name):
                        out.append(({**over, p.name: o.value}, (label + ' · ' if label else '') + f'{p.label}: {o.label}'))
        return out

    def charts_of(module_id, pid, params, only=None):
        """Графики раздела (или сохранённых макетов конструктора) при выбранных параметрах: один плоский список по всем видам.
        Каждый элемент — (график с id вида, подпись группы вида); ``only`` — ключ вида, если нужен один."""
        if module_id == SAVED:
            found, notes = saved_charts(pid, params)
            return [(c, '') for c in found], notes
        module = registry.get(module_id)
        kinds = {p.name for p in module.spec.params if p.chart_kind}
        clean = {k: v for k, v in dict(params or {}).items() if k not in kinds}
        out, seen = [], set()
        for over, label in variants_of(module.spec, clean):
            key = '&'.join(f'{k}={v}' for k, v in over.items())
            if only is not None and key != only:
                continue
            try:
                (result, _), _, _ = compute(module, pid, {**clean, **over}, True)
            except Exception:
                if not key:
                    raise
                logging.getLogger(__name__).warning('Любой график: вид «%s» раздела %s не посчитался', label, module_id, exc_info=True)
                continue            # вид, который при этих данных не считается, в списке просто отсутствует
            for c in result.charts:
                sig = (c.id, c.title, tuple((x.name, len(x.x), str(list(x.x)[:3]), str(list(x.y)[:3])) for x in c.series))
                if only is None and key and sig in seen:
                    continue            # тот же график уже есть в другом виде
                seen.add(sig)
                out.append((dataclasses.replace(c, id=key + SEP + c.id), label or 'Основные'))
        return out, []

    def modules(request, body):
        """Все разделы, у которых могут быть графики, и готовы ли для них данные проекта."""
        data = projects.data(request.path_params['pid'])
        out = []
        for m in registry.modules().values():
            spec = m.spec
            missing = [k.label for k in spec.needs if k not in data or data[k].empty]
            out.append({'id': spec.id, 'title': spec.title, 'group': spec.group, 'order': spec.order, 'ready': not missing,
                        'missing': missing})
        from . import builder_library
        if builder_library.items_of(getattr(data, 'settings', {}) or {}):
            out.append({'id': SAVED, 'title': 'Конструктор: сохранённые макеты', 'group': 'Графики', 'order': 96, 'ready': True, 'missing': []})
        return {'modules': out}

    def charts(request, body):
        try:
            found, notes = charts_of(str(body.get('module') or ''), request.path_params['pid'], body.get('params'))
        except MissingData as e:
            return {'charts': [], 'note': str(e)}
        return {'charts': [dict(describe(c), group=g) for c, g in found],
                'note': ' '.join(notes) if notes else '' if found else 'В этом разделе при выбранных параметрах графиков нет.'}

    def file(request, body):
        wanted = str(body.get('chart') or '')
        found, _ = charts_of(str(body.get('module') or ''), request.path_params['pid'], body.get('params'),
                             only=wanted.split(SEP, 1)[0] if SEP in wanted else None)
        chart = next((c for c, _ in found if c.id == wanted), None)
        if chart is None:
            return Response(json.dumps({'error': 'График не найден. Обновите список.'}, ensure_ascii=False), status_code=404,
                            media_type='application/json')
        content, name, mime, notes = export(chart, body.get('settings'))
        return Response(content, media_type=mime, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}",
                                                           'X-Atlas-Notes': quote(json.dumps(notes, ensure_ascii=False))})

    base = '/api/projects/{pid}/export/any'
    return [Route(base + '/modules', E(modules)), Route(base + '/charts', E(charts), methods=['POST']),
            Route(base + '/file', E(file), methods=['POST'])]
