"""Колонки ГИС рядом со схемой скважины: техсостояние (скопления газа, перетоки, дефекты), коллектор/неколлектор, насыщение пласта и заполнение ствола.

Ядро общее для всех мест, где рисуется схема (``atlas.passport_card.schematic``): здесь только данные и фигуры в метрах от стола.
Колонка коллектора одна на скважину (последний замер каждой пачки). Насыщение пласта и ствола зависят от даты исследования:
фигуры помечены ``date`` (ISO), экран и PDF показывают выбранную дату. Ничего не подставляется: на дату без записи колонка пустая.
Правило коллектора — подсказка с видимой причиной в подсказке фигуры (``name``); решение за инженером.
Техсостояние — пометки отчётов («Аннотации» БД ГИС: «Скопление газа: за колонной», «Заколонный переток — не выявлено», «Толщина стенки ЭК (МИД): …»):
интервалы «есть» — в колонке «Газ, ТС» на дату отчёта, всё сказанное в последнем отчёте — строкой пояснения под схемой (там видно и то, что вне окна).
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

X_TECH = (-7.5, -6.4)              # колонка «Газ, ТС»: скопления газа за колонной, в покрышке, перетоки, дефекты (пометки отчётов)
X_COLLECTOR = (-6.2, -5.1)          # колонка «коллектор / неколлектор»
X_KG = (-5.0, -3.5)                 # трек «Кг» на дату замера: столбец интервала длиной по Кг на шкале 0–1
X_BORE = ((-.95, -.58), (.58, .95))  # насыщение ствола: полосы внутри колонны по сторонам от НКТ
COLUMNS = [{'key': 'tech', 'x0': X_TECH[0], 'x1': X_TECH[1], 'title': 'Газ, ТС'},
           {'key': 'collector', 'x0': X_COLLECTOR[0], 'x1': X_COLLECTOR[1], 'title': 'Коллектор'},
           {'key': 'kg', 'x0': X_KG[0], 'x1': X_KG[1], 'title': 'Кг, д.ед.', 'scale': [0, 1]}]      # заголовки и шкала рисуют экран и PDF
SHIFT = 4.4                          # на сколько условных единиц схема сдвигается вправо ради колонок (экран и PDF)
NO = ' — не выявлено'                # окончание вида пометки «нет» (как в сборке БД ГИС)
TECH_KINDS = ('Скопление газа', 'Скопления газа', 'Заколонный переток', 'Дефекты', 'Изменение НГК', 'Толщина стенки', 'Насыщение пласта')
TECH_COLORS = (('за колонной', '#dc2626', 'газ за колонной'), ('под башмаком', '#b91c1c', 'газ под башмаком'), ('покрышк', '#f97316', 'газ в покрышке'),
               ('глинистый прослой', '#fb923c', 'газ в глинистом прослое'), ('вышележащ', '#eab308', 'газ выше пласта'), ('переток', '#7c3aed', 'переток'),
               ('дефект', '#111827', 'дефект'), ('по стволу', '#facc15', 'газ'), ('пласте-коллекторе', '#fbbf24', 'газ в пласте'))

CLAY, WATER = 'глин', 'водонасыщ'
NOT_STUDIED = ('не исследован', 'не охвачен', 'не ясно', 'влияние конструкции')
GAS_LOW, GAS_HIGH = (253, 233, 184), (224, 120, 0)       # Кг 0 → светло-жёлтый, Кг 1 → насыщенный оранжевый (один оттенок, без серых середин)
COLORS = {'collector': '#f4c542', 'non_collector': '#9ca3af', 'water': '#2b6cb0'}
FILL_COLORS = (('газ', '#f6c244', 'газ'), ('вод', '#60a5fa', 'вода'), ('раств', '#a78bfa', 'раствор'), ('нефт', '#92400e', 'нефть'))


def _num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _text(row: pd.Series, *columns: str) -> str:
    return ' '.join(str(row[c]) for c in columns if c in row.index and pd.notna(row[c])).lower()


def classify(row: pd.Series) -> tuple[str, str]:
    """(класс, причина): ``non_collector`` (глина), ``collector`` (водонасыщен или есть Кг) или ``unknown``. Глина проверяется первой."""
    text = _text(row, 'note', 'kg_text', 'status', 'status_text')
    kg = _num(row.get('kg'))
    if CLAY in text:
        return 'non_collector', 'в отчёте глина / заглинизирован'
    if WATER in text:
        return 'collector', 'в отчёте «водонасыщен»'
    if kg is not None:
        return 'collector', f'есть Кг {kg:.2f}'
    if any(w in text for w in NOT_STUDIED):
        return 'unknown', 'в отчёте: интервал не исследован или не ясен'
    return 'unknown', 'нет ни Кг, ни пометки'


def kg_color(kg: float) -> str:
    t = min(max(kg, 0.0), 1.0)
    return '#%02x%02x%02x' % tuple(round(a + (b - a) * t) for a, b in zip(GAS_LOW, GAS_HIGH))


def fill_kind(text: str) -> tuple[str, str]:
    low = (text or '').lower()
    return next(((c, name) for key, c, name in FILL_COLORS if key in low), ('#d1d5db', (text or 'прочее')))


def _iso(v: Any) -> str:
    return pd.Timestamp(v).strftime('%Y-%m-%d')


def tech_kind(kind: str) -> tuple[str, str] | None:
    """Цвет и короткое название пометки техсостояния для колонки «Газ, ТС»; None — не рисуется (не техсостояние, «не выявлено», толщина, насыщение)."""
    k = str(kind or '')
    if not k.startswith(TECH_KINDS) or k.endswith(NO) or k.startswith(('Толщина', 'Насыщение', 'Изменение НГК')):
        return None
    low = k.lower()
    return next(((c, name) for key, c, name in TECH_COLORS if key in low), ('#f59e0b', k))


def _ru(v: float) -> str:
    return f'{v:g}'.replace('.', ',')


def tech_notes(well: str, annotations: pd.DataFrame | None) -> list[str]:
    """Пояснение под схемой: что о техсостоянии сказано в последнем отчёте ГИС скважины (в том числе вне окна схемы и «не выявлено»)."""
    if annotations is None or not len(annotations) or not {'well', 'date', 'kind'} <= set(annotations.columns):
        return []
    a = annotations[(annotations['well'].astype(str) == str(well)) & annotations['kind'].astype(str).str.startswith(TECH_KINDS)].copy()
    a['date'] = pd.to_datetime(a['date'], errors='coerce', dayfirst=True)
    a = a[a['date'].notna()]
    if not len(a):
        return []
    last = a[a['date'] == a['date'].max()]
    found, absent, other = [], [], []
    for kind, g in last.groupby(last['kind'].astype(str), sort=False):
        spans = ', '.join(f'{_ru(_num(r.from_m))}–{_ru(_num(r.to_m))} м' for r in g.itertuples() if _num(getattr(r, 'from_m', None)) is not None
                          and _num(getattr(r, 'to_m', None)) is not None)
        if kind.endswith(NO):
            name = kind[:-len(NO)].replace('Скопление газа: ', 'газ ')
            absent.append(name[:1].lower() + name[1:])          # «дефекты НКТ и ЭК»: аббревиатуры не трогаем
        elif kind.startswith(('Толщина', 'Насыщение', 'Изменение НГК')):
            other.append(kind + (f' {spans}' if spans and not kind.startswith('Толщина') else ''))
        else:
            found.append(kind + (f' {spans}' if spans else ''))
    day = a['date'].max().strftime('%d.%m.%Y')
    parts = (['есть: ' + '; '.join(found)] if found else []) + (['не выявлено: ' + ', '.join(absent)] if absent else []) + (['; '.join(other)] if other else [])
    return [f'Техсостояние по ГИС {day}: ' + ' | '.join(parts) + '. Из текста отчёта; решение за инженером.']


def prepare(well: str, intervals: pd.DataFrame | None, filling: pd.DataFrame | None, annotations: pd.DataFrame | None = None) -> dict[str, Any] | None:
    """Данные колонок скважины: фигуры (метры от стола), список дат её замеров и пояснение о техсостоянии. Нет ничего — None."""
    shapes: list[dict[str, Any]] = []
    dates: set[str] = set()
    if annotations is not None and len(annotations) and {'well', 'date', 'kind', 'from_m', 'to_m'} <= set(annotations.columns):
        part = annotations[annotations['well'].astype(str) == str(well)].copy()
        part['date'] = pd.to_datetime(part['date'], errors='coerce', dayfirst=True)
        has_iv = intervals is not None and len(intervals) and 'well' in intervals and (intervals['well'].astype(str) == str(well)).any()
        for _, r in part[part['date'].notna()].iterrows():
            a, b, kind = _num(r['from_m']), _num(r['to_m']), str(r['kind'])
            if a is None or b is None:
                continue
            lo, hi, day = min(a, b), max(a, b), _iso(r['date'])
            text = str(r.get('text') or '')[:160]
            look = tech_kind(kind)
            if look:
                dates.add(day)
                shapes.append({'t': 'rect', 'x0': X_TECH[0], 'x1': X_TECH[1], 'y0': lo, 'y1': max(hi, lo + .3), 'fill': look[0], 'pattern': '',
                               'name': f'{kind} {lo:g}–{hi:g} м (ГИС {r["date"]:%d.%m.%Y}): {text}', 'col': 'tech', 'date': day})
            elif kind.startswith('Насыщение пласта') and not has_iv:      # отчёт без таблицы Кг (диагностика техсостояния): насыщение из текста, Кг нет
                dates.add(day)
                water = WATER in text.lower() and 'газонасыщ' not in text.lower()
                shapes.append({'t': 'rect', 'x0': X_KG[0], 'x1': X_KG[1], 'y0': lo, 'y1': hi, 'fill': '#cfe3f4' if water else '#fde9b8', 'pattern': '',
                               'name': f'{lo:g}–{hi:g} м: {"водонасыщен" if water else "газонасыщен"} по тексту отчёта, Кг не указан', 'col': 'kg', 'date': day})
    notes = tech_notes(well, annotations)
    if intervals is not None and len(intervals) and 'date' in intervals:       # сырые таблицы проекта: даты могут быть строками
        intervals = intervals.assign(date=pd.to_datetime(intervals['date'], errors='coerce', dayfirst=True))
    if filling is not None and len(filling) and 'date' in filling:
        filling = filling.assign(date=pd.to_datetime(filling['date'], errors='coerce', dayfirst=True))
    if intervals is not None and len(intervals) and {'well', 'date', 'from_m', 'to_m'} <= set(intervals.columns):
        part = intervals[intervals['well'].astype(str) == str(well)].copy()
        part = part[part['date'].notna()]
        if len(part):
            part['_pack'] = part['pack'].astype(object).where(part['pack'].notna(), 'без пачки').astype(str) if 'pack' in part else 'без пачки'
            last = part.groupby('_pack')['date'].transform('max')
            for _, r in part[part['date'] == last].iterrows():
                a, b = _num(r['from_m']), _num(r['to_m'])
                kind, why = classify(r)
                if a is None or b is None or kind == 'unknown':
                    continue
                shapes.append({'t': 'rect', 'x0': X_COLLECTOR[0], 'x1': X_COLLECTOR[1], 'y0': min(a, b), 'y1': max(a, b),
                               'fill': COLORS[kind], 'pattern': '', 'name': f"{'Коллектор' if kind == 'collector' else 'Неколлектор'} {min(a, b):g}–{max(a, b):g} м: {why}",
                               'col': 'collector'})
            for _, r in part.iterrows():
                a, b = _num(r['from_m']), _num(r['to_m'])
                kind, _ = classify(r)
                dates.add(_iso(r['date']))
                if a is None or b is None or kind != 'collector':
                    continue
                kg = _num(r.get('kg'))
                water = WATER in _text(r, 'note', 'kg_text', 'status', 'status_text')
                lo, hi = min(a, b), max(a, b)
                day = _iso(r['date'])
                if kg is None or water:             # водонасыщенный интервал: полоса на всю ширину шкалы, без числа
                    shapes.append({'t': 'rect', 'x0': X_KG[0], 'x1': X_KG[1], 'y0': lo, 'y1': hi, 'fill': '#cfe3f4', 'pattern': '',
                                   'name': f'{lo:g}–{hi:g} м: водонасыщен', 'col': 'kg', 'date': day})
                    continue
                share = min(max(kg, 0.0), 1.0)
                shapes.append({'t': 'rect', 'x0': X_KG[0], 'x1': X_KG[0] + share * (X_KG[1] - X_KG[0]), 'y0': lo, 'y1': hi, 'fill': kg_color(kg),
                               'pattern': '', 'name': f'{lo:g}–{hi:g} м: Кг {kg:.2f}', 'col': 'kg', 'date': day})
                shapes.append({'t': 'text', 'x0': X_KG[0] + .06, 'x1': X_KG[0] + .06, 'y0': (lo + hi) / 2, 'y1': (lo + hi) / 2, 'text': f'{kg:.2f}'.replace('.', ','),
                               'span': hi - lo, 'name': f'Кг {kg:.2f}', 'col': 'kg', 'date': day})
    if filling is not None and len(filling) and {'well', 'date', 'fill'} <= set(filling.columns):
        part = filling[(filling['well'].astype(str) == str(well)) & filling['date'].notna()]
        for _, r in part.iterrows():
            day = _iso(r['date'])
            dates.add(day)
            color, name = fill_kind(str(r.get('fill') or ''))
            a, b, level = _num(r.get('from_m')), _num(r.get('to_m')), _num(r.get('level_m'))
            if a is not None and b is not None:
                lo, hi = min(a, b), max(a, b)
                what = f'Ствол {lo:g}–{hi:g} м: {name}'
            elif level is not None:
                lo, hi = level, None              # жидкость ниже уровня; нижняя граница — забой/низ окна (задаёт схема)
                what = f'Ствол: {name}, уровень {level:g} м'
            else:
                continue
            for x0, x1 in X_BORE:
                shapes.append({'t': 'rect', 'x0': x0, 'x1': x1, 'y0': lo, 'y1': hi, 'fill': color, 'pattern': '', 'name': what,
                               'col': 'bore', 'date': day})
    if not shapes and not notes:
        return None
    return {'shapes': shapes, 'dates': sorted(dates), 'notes': notes}


def frame_shapes(top: float, bottom: float) -> list[dict[str, Any]]:
    """Рамки колонок и сетка шкалы Кг на всё окно глубин (как трек на планшете ГИС); без даты — видны всегда."""
    out: list[dict[str, Any]] = []
    for c in COLUMNS:
        out.append({'t': 'frame', 'x0': c['x0'], 'x1': c['x1'], 'y0': top, 'y1': bottom, 'stroke': '#9ca3af', 'width': 1, 'name': c['title']})
        for v in ([.25, .5, .75] if c['key'] == 'kg' else []):
            x = c['x0'] + v * (c['x1'] - c['x0'])
            out.append({'t': 'line', 'x0': x, 'x1': x, 'y0': top, 'y1': bottom, 'stroke': '#e5e7eb', 'width': 1, 'name': 'grid'})
    return out
