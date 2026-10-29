"""Библиотека макетов конструктора графиков (этап 5): именованные макеты в проекте, файл для переноса, Word, вставка в отчёт АН.

Хранение: ``settings['builder_layouts'] = {'version': 1, 'items': [{id, name, created, updated, layout}]}`` в манифесте проекта.
Ключ новый и необязательный: проекты без него (в том числе из 5.8) открываются как раньше, 5.8 лишний ключ настроек не читает.
Расчёта здесь нет: проверка макета и график — ``modules/builder.py``.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import uuid
from typing import Any, Mapping

from .contract import Data, Note, ParamError, Result
from .domain import DatasetKind
from .modules import builder

KEY = 'builder_layouts'
VERSION = 1
FILE_FORMAT = 'gas-atlas-builder-layout'
MAX_ITEMS = 200
MAX_FILE = 2_000_000          # макет — это сотни байт; больше — не макет


def _now() -> str:
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def items_of(settings: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Макеты из настроек проекта; испорченная запись пропускается, а не роняет проект."""
    store = settings.get(KEY)
    raw = store.get('items') if isinstance(store, Mapping) else None
    return [i for i in raw or [] if isinstance(i, Mapping) and i.get('id') and isinstance(i.get('name'), str) and isinstance(i.get('layout'), Mapping)]


def _with(settings: Mapping[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = copy.deepcopy(dict(settings))
    cfg[KEY] = {'version': VERSION, 'items': items}
    return cfg


def clean_name(name: Any, items: list[dict[str, Any]], keep: str = '') -> str:
    text = ' '.join(str(name or '').split())[:120]
    if not text:
        raise ParamError('Введите имя макета')
    if any(i['name'].casefold() == text.casefold() for i in items if i['id'] != keep):
        raise ParamError(f'Макет «{text}» уже есть в проекте. Выберите другое имя.')
    return text


def checked(layout: Any) -> dict[str, Any]:
    """Макет, прошедший проверку конструктора (понятная ошибка по-русски), в виде, годном для хранения."""
    if not isinstance(layout, Mapping):
        raise ParamError('Макет: ожидается объект с рядами («series»)')
    builder.parse_layout(layout)
    out = json.loads(json.dumps(layout, ensure_ascii=False))     # только JSON-значения
    return out


def summary(item: Mapping[str, Any]) -> dict[str, Any]:
    series = item['layout'].get('series') or []
    return {'id': item['id'], 'name': item['name'], 'created': item.get('created', ''), 'updated': item.get('updated', ''),
            'series': len(series) if isinstance(series, list) else 0, 'title': str(item['layout'].get('title') or '')}


def listing(settings: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [summary(i) for i in sorted(items_of(settings), key=lambda i: str(i['name']).casefold())]


def find(settings: Mapping[str, Any], lid: str) -> dict[str, Any]:
    for item in items_of(settings):
        if item['id'] == lid:
            return dict(item)
    raise KeyError('Макет не найден. Возможно, он удалён в другом окне.')


def add(settings, name: str, layout: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    items = [dict(i) for i in items_of(settings)]
    if len(items) >= MAX_ITEMS:
        raise ParamError(f'В проекте не больше {MAX_ITEMS} макетов. Удалите ненужные.')
    item = {'id': uuid.uuid4().hex[:12], 'name': clean_name(name, items), 'created': _now(), 'updated': _now(), 'layout': checked(layout)}
    return _with(settings, [*items, item]), item


def change(settings, lid: str, name: Any = None, layout: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    items = [dict(i) for i in items_of(settings)]
    item = next((i for i in items if i['id'] == lid), None)
    if item is None:
        raise KeyError('Макет не найден. Возможно, он удалён в другом окне.')
    if name is not None:
        item['name'] = clean_name(name, items, keep=lid)
    if layout is not None:
        item['layout'] = checked(layout)
    item['updated'] = _now()
    return _with(settings, items), item


def duplicate(settings, lid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    src = find(settings, lid)
    names = {i['name'].casefold() for i in items_of(settings)}
    base, n = f'{src["name"]} (копия)', 1
    name = base
    while name.casefold() in names:
        n += 1
        name = f'{base} {n}'
    return add(settings, name, src['layout'])


def remove(settings, lid: str) -> dict[str, Any]:
    find(settings, lid)
    return _with(settings, [dict(i) for i in items_of(settings) if i['id'] != lid])


# ---------- файл макета ----------

def to_file(name: str, layout: Any) -> bytes:
    doc = {'format': FILE_FORMAT, 'version': VERSION, 'name': name, 'layout': checked(layout)}
    return json.dumps(doc, ensure_ascii=False, indent=1).encode('utf-8')


def from_file(raw: bytes | str) -> tuple[str, dict[str, Any]]:
    """(имя, макет) из файла JSON; кривой файл — понятная ошибка. Принимается и «голый» макет с рядами."""
    if len(raw) > MAX_FILE:
        raise ParamError('Файл слишком большой для макета конструктора')
    try:
        doc = json.loads(raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError):
        raise ParamError('Файл не является макетом: это не JSON. Выберите файл, выгруженный кнопкой «Экспорт макета».') from None
    if not isinstance(doc, Mapping):
        raise ParamError('Файл не является макетом: ожидается объект JSON.')
    if 'layout' not in doc and 'series' in doc:
        doc = {'name': '', 'layout': doc}
    elif doc.get('format') not in (FILE_FORMAT, None) or 'layout' not in doc:
        raise ParamError('Файл не является макетом конструктора графиков Газового атласа.')
    try:
        version = int(doc.get('version', VERSION))
    except (TypeError, ValueError):
        raise ParamError('Файл макета: версия формата должна быть числом') from None
    if version > VERSION:
        raise ParamError(f'Макет создан в более новой версии программы (формат {version}). Обновите Газовый атлас.')
    return str(doc.get('name') or '')[:120], checked(doc['layout'])


# ---------- что не найдено в данных проекта ----------

def missing_of(data: Data, layout: Any) -> list[str]:
    """Что из макета не нашлось в данных проекта: набор, поле, скважины. Пустой список — всё на месте."""
    series = layout.get('series') if isinstance(layout, Mapping) else None
    if not isinstance(series, list):
        return []
    known = {d['id']: d for d in builder.catalog(data)['datasets']}
    out: list[str] = []

    def field(i: int, label: str, kind: str, column: str) -> bool:
        ds = known.get(kind)
        if kind not in {k.value for k in DatasetKind}:
            out.append(f'Ряд {i}: неизвестный набор «{kind}»')
            return False
        title = DatasetKind(kind).label
        if ds is None:
            out.append(f'Ряд {i}: в проекте нет данных набора «{title}»')
            return False
        if column and column not in {f['field'] for f in ds['fields']}:
            out.append(f'Ряд {i}: в наборе «{title}» нет поля «{builder.meta(DatasetKind(kind), column).label}» ({label})')
            return False
        return True

    for i, r in enumerate(series, start=1):
        if not isinstance(r, Mapping) or str(r.get('source') or 'field') == 'formula':
            continue
        dataset = str(r.get('dataset') or '')
        if field(i, 'Y', dataset, str(r.get('y') or '')):
            ds = known[dataset]
            wells = [str(w) for w in r.get('wells') or []]
            lost = [w for w in wells if ds['entities'] and w not in set(ds['entities'])]
            if lost and ds['entities']:
                out.append(f'Ряд {i}: нет скважин (групп) {", ".join(lost[:8])}' + (f' и ещё {len(lost) - 8}' if len(lost) > 8 else '')
                           + ' — ряд будет пустым или неполным')
        x_dataset = str(r.get('x_dataset') or dataset)
        if x_dataset != dataset or str(r.get('x') or 'date') != 'date':
            field(i, 'X', x_dataset, str(r.get('x') or 'date'))
    return out


def chart_of(data: Data, layout: Any, well: str | None = None):
    """Готовый график макета (контракт ``Chart``) и заметки расчёта; ``None``, если рядов на графике нет.
    ``well`` — скважина для рядов «Текущая скважина» (иначе ``layout.current_well``)."""
    result = builder.build(data, layout, well)
    return (result.charts[0] if result.charts else None), [n.text for n in result.notes]


# ---------- макеты проекта в результате раздела ----------

MAX_WELL_CHARTS = 12        # графиков одного макета «Текущая скважина» в разделе; остальные скважины — заметка


def layout_names(data: Data) -> list[str]:
    """Имена макетов проекта: варианты параметра раздела ``builder_layouts``."""
    return sorted(i['name'] for i in items_of(data.settings))


def add_layout_charts(result: Result, data: Data, names: list[str], wells: list[str] | None = None, limit: int = MAX_WELL_CHARTS,
                      noun: str = 'график') -> None:
    """Выбранные макеты проекта графиками раздела (после основных), id ``builder-<id>`` (``builder-<id>-<скважина>``).

    Работает с наборами, которые раздел и так загрузил: чего не хватает — предупреждение «Макет «…»: …», раздел не падает.
    Макет «Текущая скважина»: ``wells`` — скважины раздела (график на каждую, не больше ``limit``); ``wells=None`` —
    скважина самого макета (``current_well``), без неё рисунок пропускается (отчёт АН). Остальные макеты — один график.
    """
    saved = {i['name']: i for i in items_of(data.settings)}
    for name in dict.fromkeys(names):
        item = saved.get(name)
        if item is None:
            result.notes.append(Note(f'Макет конструктора «{name}» не найден в проекте — {noun} пропущен.', 'warning'))
            continue
        layout = item['layout']
        try:
            lost = missing_of(data, layout)
        except ParamError as e:
            result.notes.append(Note(f'Макет «{name}»: {e}', 'warning'))
            continue
        result.notes += [Note(f'Макет «{name}»: {text}.', 'warning') for text in lost]
        targets: list[str | None] = [None]
        if builder.uses_current(layout):
            if wells is None:
                if not str(layout.get('current_well') or '').strip():
                    result.notes.append(Note(f'Макет «{name}»: не выбрана скважина — {noun} пропущен. Откройте макет в конструкторе, выберите '
                                             'скважину макета и нажмите «Обновить».', 'warning'))
                    continue
            elif not wells:
                result.notes.append(Note(f'Макет «{name}» строится по скважинам, а скважины в разделе не выбраны — {noun} пропущен.', 'warning'))
                continue
            else:
                targets = list(wells[:limit])
                if len(wells) > limit:
                    result.notes.append(Note(f'Макет «{name}»: показаны первые {limit} скважин из {len(wells)}. Остальные — в конструкторе '
                                             '(«Серия по скважинам») или выберите меньше скважин.'))
        empty: list[str] = []
        for well in targets:
            try:
                chart, notes = chart_of(data, layout, well)
            except ParamError as e:
                result.notes.append(Note(f'Макет «{name}»: {e}', 'warning'))
                break
            if chart is None or not chart.series:
                empty.append(well or '')
                if well is None:
                    result.notes.append(Note(f'Макет «{name}»: нет данных для графика' + (f' ({notes[0]})' if notes else '') + f' — {noun} пропущен.', 'warning'))
                continue
            chart.id = 'builder-' + item['id'] + (f'-{well}' if well else '')
            if not chart.title:
                chart.title = name
            if well and well not in chart.title:
                chart.title = f'{chart.title}, скважина {well}'
            result.charts.append(chart)
        if empty and targets != [None]:
            result.notes.append(Note(f'Макет «{name}»: нет данных по скважинам {", ".join(empty)} — графики пропущены.', 'warning'))


# ---------- Word: один график с заголовком и подписью ----------

def word_file(chart, title: str, caption: str, orientation: str = 'landscape', font: str = 'default', font_size=None,
              caption_mode: str = 'field') -> tuple[bytes, str]:
    """Документ Word с одним графиком: заголовок, рисунок и подпись «Рисунок N – …».

    Номер — поле SEQ (``field``, как в выгрузке графиков) или обычный текст (``text``): поле Word подсвечивается как ссылка.
    """
    from . import render, word_export
    from .word_export import Item, Layout
    layout = Layout(orientation='landscape' if orientation != 'portrait' else 'portrait', title=bool(title), title_text=title, dpi=200,
                    caption_mode=caption_mode if caption_mode in ('field', 'text') else 'field')
    text = ' '.join(str(caption or chart.title or 'График').split())
    item = Item(chart.title or 'График', 'Рисунок ', 1, ' – ' + text, module='builder')
    cap_h = word_export.caption_height(layout, item.text, layout.cell())
    item.png, item.w, item.h = word_export.render_png(render.to_plotly(chart), layout, cap_h, font, font_size)
    return word_export.build_docx([item], layout, title or chart.title), f'{chart.title or "График"}.docx'


# ---------- серия графиков по скважинам ----------

MAX_WELLS = 200
SERIES_FORMATS = {'png': 'PNG (zip, по файлу на скважину)', 'pdf': 'PDF, страница на скважину', 'docx': 'Word, график на странице'}
ZIP = 'application/zip'
PDF = 'application/pdf'
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def wells_info(data: Data, layout: Any) -> dict[str, Any]:
    """Скважины проекта для режима «Текущая скважина»: все, группы и те, у кого есть точки хотя бы в одном ряду этого режима."""
    import dataclasses
    from .modules.an_report import well_scopes
    rows, _ = builder.parse_layout(layout)
    wells = builder.catalog(data)['wells']
    current = [r for r in rows if r.well_mode == 'current' and r.source == 'field' and r.y and not r.hidden]
    have: set[str] = set()
    for r in current:
        p = builder.pairs(data, dataclasses.replace(r, wells=[], well_mode='fixed'))
        f = p.frame
        if p.frame.empty:
            continue
        have |= {str(e) for e in f.loc[f['x'].notna() & f['y'].notna(), 'entity'] if str(e)}
    groups: dict[str, list[str]] = {}
    mapping = getattr(data, 'mapping', None) or {}
    for w, g in well_scopes(mapping, wells).items():
        groups.setdefault(str(g), []).append(w)
    return {'enabled': builder.uses_current(layout), 'wells': wells, 'with_data': [w for w in wells if w in have],
            'groups': [{'name': g, 'wells': ws} for g, ws in sorted(groups.items(), key=lambda kv: kv[0].casefold())]}


def series_file(data: Data, layout: Any, wells: list[str], fmt: str, title: str = '', orientation: str = 'landscape',
                dpi: int = 200) -> tuple[bytes, str, str, list[str]]:
    """Файл с графиком макета по каждой выбранной скважине: (содержимое, имя файла, тип, заметки). Скважины без данных пропускаются."""
    import io
    import zipfile
    from . import render
    from .engine.core.export import safe_name
    if fmt not in SERIES_FORMATS:
        raise ParamError('Формат серии: PNG (архив zip), PDF или Word')
    if not builder.uses_current(layout):
        raise ParamError('В макете нет рядов в режиме «Текущая скважина»: включите его в карточке ряда, и серию можно будет выгрузить.')
    picked = list(dict.fromkeys(str(w).strip() for w in wells if str(w).strip()))
    if not picked:
        raise ParamError('Выберите хотя бы одну скважину для серии.')
    if len(picked) > MAX_WELLS:
        raise ParamError(f'За один раз можно выгрузить не больше {MAX_WELLS} скважин, выбрано {len(picked)}. Разделите выбор на части.')
    charts, skipped = [], []
    for w in picked:
        chart, _ = chart_of(data, layout, w)
        if chart is None or not chart.series:
            skipped.append(w)
        else:
            charts.append((w, chart))
    notes = [f'Нет данных для скважин, они пропущены ({len(skipped)}): ' + ', '.join(skipped[:30]) + (' и др.' if len(skipped) > 30 else '')] if skipped else []
    if not charts:
        raise ParamError('Ни у одной из выбранных скважин нет данных для графика макета. ' + (notes[0] if notes else ''))
    raw = str(layout.get('title') or '') if isinstance(layout, Mapping) else ''
    raw = '' if builder.PLACEHOLDER in raw else raw          # у заголовка с номером скважины имя файла общее
    base = safe_name(title or raw or 'Серия по скважинам')[:80]
    if fmt == 'png':
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for n, (w, chart) in enumerate(charts, start=1):
                z.writestr(f'{n:03d}_скв_{safe_name(w)}.png', render.chart_file(chart, 'png', dpi)[0])
        return buf.getvalue(), base + '.zip', ZIP, notes
    labelled = [(w, chart, _caption(chart, w)) for w, chart in charts]
    if fmt == 'pdf':
        from .engine.core.documents import grid_pdf
        buf = io.BytesIO()
        grid_pdf([(render.chart_file(chart, 'png', dpi)[0], text) for _, chart, text in labelled], buf, columns=1, rows=1,
                 metadata={'Title': base, 'Author': 'Газовый атлас'}, dpi=dpi)
        return buf.getvalue(), base + '.pdf', PDF, notes
    from . import word_export
    from .word_export import Item, Layout
    lay = Layout(orientation='landscape' if orientation != 'portrait' else 'portrait', per_page=1, title=bool(title), title_text=title, dpi=dpi)
    items = []
    for n, (_, chart, text) in enumerate(labelled, start=1):
        item = Item(chart.title or 'График', 'Рисунок ', n, ' – ' + text, module='builder')
        cap_h = word_export.caption_height(lay, item.text, lay.cell())
        item.png, item.w, item.h = word_export.render_png(render.to_plotly(chart), lay, cap_h)
        items.append(item)
    return word_export.build_docx(items, lay, title or base), base + '.docx', DOCX, notes


def _caption(chart, well: str) -> str:
    text = ' '.join(str(chart.title or 'График').split())
    return text if well in text else f'{text}, скважина {well}'
