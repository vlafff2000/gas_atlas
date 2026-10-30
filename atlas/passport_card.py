"""Карточка «Паспорта скважины»: сводка работы, ГДИ, КРС и схема забойной части — одни данные для экрана и PDF.

Расчёты не новые: сезоны, ГДИ и конструкцию даёт ``atlas.engine.modules.well_analysis``; здесь только выбор данных и
представление, плюс максимальный суточный расход по сезону (максимум по дням той же таблицы суточных объёмов).
КРС — таблицы проекта ``krs_works`` и ``krs_priority`` (книга ``КРС_для_Атласа.xlsx`` загружается во вкладке «Импорт»).
Схема — список интервалов в метрах; экран (SVG) и PDF (matplotlib) рисуют по нему одинаково.
"""
from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pandas as pd

KINDS = (('withdrawal', 'Отбор'), ('injection', 'Закачка'))
# Какие элементы шаблона конструкции попадают на схему забойной части; кондуктор и прочие колонны — нет.
RULES = (('reaming', r'расшир|подзабой|каверн'), ('filter', r'фильтр'), ('perf', r'перфор'), ('packer', r'пакер'),
         ('tubing', r'нкт|лифт|насосно'), ('pay', r'пласт|коллектор|продуктив'),
         ('casing', r'эксплуатационн|э/?к\b'))
KIND_LABELS = {'casing': 'Эксплуатационная колонна', 'tubing': 'НКТ', 'filter': 'Фильтр', 'perf': 'Перфорация',
               'reaming': 'Расширка', 'packer': 'Пакер', 'pay': 'Пласт', 'bottom': 'Забой'}
SKIPPED = r'кондуктор|направлени|потайн|хвостовик|техническ'


def classify(element: str) -> str | None:
    """Тип элемента схемы по названию из шаблона конструкции; None — элемент на схему не выносится."""
    text = str(element).lower()
    if re.search(r'забой', text):
        return 'bottom'
    if re.search(SKIPPED, text) and not re.search(r'фильтр|перфор|расшир', text):
        return None
    for kind, pattern in RULES:
        if re.search(pattern, text):
            return kind
    return None


def _num(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _date(value: Any) -> str:
    return '' if value is None or pd.isna(value) else pd.Timestamp(value).strftime('%d.%m.%Y')


def schematic(construction: pd.DataFrame, bottom_m: float | None) -> dict[str, Any]:
    """Забойная часть: интервалы по типам, окно глубин и пояснение, чего не хватает. Глубины — метры от одного нуля."""
    items: list[dict[str, Any]] = []
    skipped: list[str] = []
    for _, r in construction.iterrows():
        kind = classify(r.element)
        top, low = _num(r.top_m), _num(r.bottom_m)
        if kind is None or top is None or low is None:
            skipped.append(str(r.element))
            continue
        items.append({'kind': kind, 'label': str(r.element), 'top': top, 'bottom': low,
                      'od': _num(r.get('diameter_mm')), 'id': _num(r.get('inner_diameter_mm')),
                      'comment': str(r.get('comment') or '')})
    notes: list[str] = []
    if not items:
        return {'items': [], 'notes': ['Нет конструкции на схему: загрузите снимок конструкции (шаблон «Конструкция»).'],
                'skipped': skipped, 'top': 0, 'bottom': 0, 'bottom_m': bottom_m}
    kinds = {i['kind'] for i in items}
    if 'casing' not in kinds:
        notes.append('В конструкции нет эксплуатационной колонны: колонна на схеме не показана.')
    if not kinds & {'filter', 'perf'}:
        notes.append('Не указан фильтр или интервал перфорации.')
    # Окно: от точки чуть выше самого верхнего элемента забойной части до забоя; колонна и НКТ идут сверху, их верх не берём.
    tops = [i['top'] for i in items if i['kind'] in ('filter', 'perf', 'reaming', 'packer', 'pay')]
    tubing = [i['bottom'] for i in items if i['kind'] == 'tubing']
    ends = [i['bottom'] for i in items]
    top_depth = min(tops + tubing) if tops or tubing else min(i['top'] for i in items)
    low_depth = max(ends + ([bottom_m] if bottom_m else []))
    span = max(low_depth - top_depth, 1.0)
    window_top = max(top_depth - max(span * .35, 15.0), 0.0)
    window_bottom = low_depth + max(span * .12, 8.0)
    out = {'items': sorted(items, key=lambda i: (i['top'], i['bottom'])), 'notes': notes, 'skipped': skipped,
           'top': round(window_top, 1), 'bottom': round(window_bottom, 1), 'bottom_m': bottom_m}
    filter_end = max([i['bottom'] for i in items if i['kind'] in ('filter', 'perf')], default=None)
    if bottom_m is not None and filter_end is not None and bottom_m < filter_end - .05:
        out['covered_m'] = round(filter_end - bottom_m, 1)
        out['notes'].append(f'Отбитый забой {bottom_m:g} м выше низа фильтра/перфорации {filter_end:g} м: '
                            f'перекрыто {filter_end - bottom_m:g} м (песчаная пробка).')
    out['shapes'], out['labels'] = shapes(out)
    return out


HALF = {'casing': 1.0, 'tubing': .45}          # условные полуширины, без масштаба диаметров (диаметры — в подписях)


def shapes(sch: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Фигуры схемы для экрана и PDF: прямоугольники и линии в условных единицах по x и метрах по y, подписи справа."""
    top, low = sch['top'], sch['bottom']
    by = {k: [i for i in sch['items'] if i['kind'] == k] for k in KIND_LABELS}
    out: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []

    def clip(a: float, b: float) -> tuple[float, float] | None:
        a, b = max(a, top), min(b, low)
        return (a, b) if b >= a else None

    def rect(x0, x1, a, b, fill, pattern='', name=''):
        span = clip(a, b)
        if span:
            out.append({'t': 'rect', 'x0': x0, 'x1': x1, 'y0': span[0], 'y1': span[1], 'fill': fill, 'pattern': pattern, 'name': name})

    def tag(y, text, color):
        labels.append({'y': y, 'text': text, 'color': color})
    for i in by['pay']:
        rect(-3, 3, i['top'], i['bottom'], '#fdf0c0', name='pay')
        tag((max(i['top'], top) + min(i['bottom'], low)) / 2, f"Пласт {i['top']:g}–{i['bottom']:g} м", '#a16207')
    for i in by['reaming']:
        rect(-1.9, 1.9, i['top'], i['bottom'], '#d6b48a', name='reaming')
        tag((max(i['top'], top) + min(i['bottom'], low)) / 2, f"Расширка {i['top']:g}–{i['bottom']:g} м"
            + (f", Ø{i['od']:g} мм" if i['od'] else ''), '#92400e')
    for i in by['casing']:
        rect(-1.0, 1.0, i['top'], i['bottom'], '#f1f5f9', name='bore')
        for sign in (-1, 1):
            x0, x1 = sorted((sign * 1.0, sign * 1.12))
            rect(x0, x1, i['top'], i['bottom'], '#6b7280', name='casing')
        if clip(i['bottom'], i['bottom']):
            tag(i['bottom'], f"Башмак колонны {i['bottom']:g} м" + (f", Ø{i['od']:g} мм" if i['od'] else ''), '#374151')
        elif i['top'] < top + 1:
            tag(top + (low - top) * .02, 'Эксплуатационная колонна' + (f", Ø{i['od']:g} мм" if i['od'] else ''), '#374151')
    for i in by['filter']:
        for sign in (-1, 1):
            x0, x1 = sorted((sign * .96, sign * 1.16))
            rect(x0, x1, i['top'], i['bottom'], '#14b8a6', 'slots', 'filter')
        tag((max(i['top'], top) + min(i['bottom'], low)) / 2, f"Фильтр {i['top']:g}–{i['bottom']:g} м", '#0f766e')
    for i in by['perf']:
        a, b = max(i['top'], top), min(i['bottom'], low)
        if b >= a:
            count = max(2, min(9, int((b - a) / max((low - top) / 40, .5)) + 1))
            for y in np.linspace(a, b, count):
                for sign in (-1, 1):
                    out.append({'t': 'line', 'x0': sign * .9, 'x1': sign * 1.55, 'y0': float(y), 'y1': float(y), 'stroke': '#e11d48', 'width': 1.6, 'name': 'perf'})
            tag((a + b) / 2, f"Перфорация {i['top']:g}–{i['bottom']:g} м", '#be123c')
    for i in by['tubing']:
        rect(-.45, .45, i['top'], i['bottom'], '#dbeafe', name='bore')
        for sign in (-1, 1):
            x0, x1 = sorted((sign * .45, sign * .53))
            rect(x0, x1, i['top'], i['bottom'], '#2563eb', name='tubing')
        if clip(i['bottom'], i['bottom']):
            tag(i['bottom'], f"Башмак НКТ {i['bottom']:g} м" + (f", Ø{i['od']:g} мм" if i['od'] else ''), '#1d4ed8')
    pack_h = max((low - top) * .018, 1.2)
    for i in by['packer']:
        mid = (i['top'] + i['bottom']) / 2
        for sign in (-1, 1):
            x0, x1 = sorted((sign * .53, sign * 1.0))
            rect(x0, x1, min(i['top'], mid - pack_h / 2), max(i['bottom'], mid + pack_h / 2), '#111827', name='packer')
        tag(mid, f"Пакер {mid:g} м", '#111827')
    cover, bottom_m = sch.get('covered_m'), sch.get('bottom_m')
    if cover and bottom_m:
        rect(-.95, .95, bottom_m, bottom_m + cover, '#e8c987', 'sand', 'fill')
    if bottom_m and top <= bottom_m <= low:
        out.append({'t': 'line', 'x0': -1.7, 'x1': 1.7, 'y0': bottom_m, 'y1': bottom_m, 'stroke': '#dc2626', 'width': 3, 'name': 'bottom'})
        tag(bottom_m, f'Забой {bottom_m:g} м (отбит)', '#b91c1c')
    return out, _spread(labels, (low - top) * .045)


def _spread(labels: list[dict[str, Any]], gap: float) -> list[dict[str, Any]]:
    """Подписи справа не налезают друг на друга: сдвигаем по глубине, выноска ведёт к реальной точке."""
    labels = sorted(labels, key=lambda l: l['y'])
    prev = None
    for label in labels:
        label['at'] = label['y']
        if prev is not None and label['at'] < prev + gap:
            label['at'] = prev + gap
        prev = label['at']
    return labels


def seasons_table(daily: pd.DataFrame, stats: pd.DataFrame, kind: str) -> list[dict[str, Any]]:
    """Сезоны: объём, отработанные дни, максимальный и средний суточный расход, часы и вода."""
    if stats.empty:
        return []
    top = {}
    if not daily.empty:
        g = daily[daily.gas_volume_m3.notna()]
        for period, part in g.groupby('period', sort=False):
            i = part.gas_volume_m3.idxmax()
            top[period] = (part.gas_volume_m3[i] / 1000, part.date[i])
    rows = []
    for _, s in stats.iterrows():
        peak = top.get(s.period)
        rows.append({'kind': kind, 'period': str(s.period), 'volume': _num(s.gas_volume), 'days': int(s.active_days),
                     'max_rate': _num(peak[0]) if peak else None, 'max_date': _date(peak[1]) if peak else '',
                     'mean_rate': _num(s.mean_active), 'hours': _num(s.hours), 'water': _num(s.water_volume),
                     'coverage': _num(s.coverage)})
    return rows


def gdi_table(history: pd.DataFrame) -> list[dict[str, Any]]:
    """Все исследования скважины за всё время; ненадёжные помечены, но не скрыты — решает инженер."""
    rows = []
    if history.empty:
        return rows
    for _, r in history.sort_values('date').iterrows():
        rows.append({'date': _date(r.date), 'method': str(r.method or ''), 'a': _num(r.a), 'b': _num(r.b), 'r2': _num(r.r2),
                     'q_max': _num(r.q_observed), 'q_free': _num(r.q_free), 'reliable': bool(r.reliable),
                     'note': str(r.note or '')})
    return rows


def krs_rows(works: pd.DataFrame | None, priority: pd.DataFrame | None, well: str) -> dict[str, Any]:
    """КРС скважины из таблиц проекта (импорт книги «КРС_для_Атласа.xlsx»): ремонты и приоритет-подсказка."""
    if works is None and priority is None:
        return {'works': [], 'priority': None, 'loaded': False,
                'note': 'КРС не загружены: импортируйте книгу КРС_для_Атласа.xlsx во вкладке «Импорт».'}
    rows = []
    if works is not None and not works.empty:
        mine = works[works.well.astype(str).eq(str(well))].sort_values('year')
        rows = [{'year': None if pd.isna(r.year) else int(r.year), 'type': str(r.work_type or ''), 'detail': str(r.detail or '')}
                for _, r in mine.iterrows()]
    info = None
    if priority is not None and not priority.empty:
        p = priority[priority.well.astype(str).eq(str(well))]
        if not p.empty:
            r = p.iloc[0]
            info = {'value': _num(r.priority), 'reason': str(r.reason or ''), 'sand': str(r.sand or '')}
    return {'works': rows, 'priority': info, 'loaded': True, 'note': '' if rows else 'По этой скважине КР в загруженных данных нет.'}


def build(frames, settings, mapping, well: str, krs: tuple[pd.DataFrame | None, pd.DataFrame | None] = (None, None)) -> dict[str, Any]:
    """Всё для карточки одной скважины. Пустые разделы — заметка, не ошибка."""
    from atlas.engine.modules import well_analysis
    by_kind: dict[str, dict[str, Any]] = {}
    for kind, _ in KINDS:
        by_kind[kind] = dict(well_analysis.analyze(frames, settings, mapping, well, kind))
    first = by_kind['withdrawal']
    seasons = [row for kind, _ in KINDS for row in seasons_table(by_kind[kind]['daily'], by_kind[kind]['seasons'], kind)]
    gdi_all = gdi_table(first['gdi_history'])
    bottom = first['bottom']
    bottom_m = _num(bottom.iloc[-1].bottom_m) if not bottom.empty else None
    construction = first['construction']
    cons = schematic(construction, bottom_m) if not construction.empty else schematic(pd.DataFrame(
        columns=['element', 'top_m', 'bottom_m']), bottom_m)
    krs = krs_rows(krs[0], krs[1], well)
    out_rows = [r for r in seasons if r['kind'] == 'withdrawal']
    peak = max((r for r in out_rows if r['max_rate'] is not None), key=lambda r: r['max_rate'], default=None)
    reliable = [g for g in gdi_all if g['reliable']]
    water = first['water']
    kpi = [
        {'label': 'Отбор за все сезоны', 'value': _sum(out_rows, 'volume'), 'unit': 'млн м³', 'digits': 2},
        {'label': 'Закачка за все сезоны', 'value': _sum([r for r in seasons if r['kind'] == 'injection'], 'volume'),
         'unit': 'млн м³', 'digits': 2},
        {'label': 'Максимальный суточный отбор', 'value': peak['max_rate'] if peak else None, 'unit': 'тыс. м³/сут', 'digits': 1,
         'hint': f"{peak['period']}, {peak['max_date']}" if peak else ''},
        {'label': 'Отработано дней (отбор)', 'value': float(sum(r['days'] for r in out_rows)) if out_rows else None, 'unit': 'дн.', 'digits': 0},
        {'label': 'ГДИ за всё время', 'value': float(len(gdi_all)) if gdi_all else None, 'unit': 'шт.', 'digits': 0,
         'hint': f"последнее {gdi_all[-1]['date']}" if gdi_all else '', 'extra': f'надёжных: {len(reliable)}' if gdi_all else ''},
        {'label': 'Проведено КР', 'value': float(len(krs['works'])) if krs['loaded'] else None, 'unit': 'шт.', 'digits': 0,
         'hint': f"последний {krs['works'][-1]['year']}" if krs['works'] else ''},
        {'label': 'Отбитый забой', 'value': bottom_m, 'unit': 'м', 'digits': 1,
         'hint': _date(bottom.iloc[-1].date) if not bottom.empty else ''},
        {'label': 'Вода по последнему контролю', 'value': None, 'text': 'нет данных' if water.empty else str(water.iloc[-1]['Состояние']),
         'hint': '' if water.empty else _date(water.iloc[-1]['Дата'])},
    ]
    notes = [s for s in cons['notes']]
    if krs['note']:
        notes.append(krs['note'])
    if not seasons:
        notes.append('Нет данных по сезонам эксплуатации: загрузите динамику или суточную эксплуатацию.')
    return {'well': well, 'group': mapping.get(well, {}).get('group', ''),
            'construction_date': _date(construction.date.max()) if not construction.empty else '',
            'kpi': kpi, 'seasons': seasons, 'gdi': gdi_all, 'krs': krs, 'schematic': cons, 'notes': notes}


def _sum(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [r[key] for r in rows if r[key] is not None]
    return float(sum(values)) if values else None
