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

from atlas.construction_checks import check_construction

KINDS = (('withdrawal', 'Отбор'), ('injection', 'Закачка'))
# Какие элементы шаблона конструкции попадают на схему забойной части; кондуктор и прочие колонны — нет.
RULES = (('reaming', r'расшир|подзабой|каверн'), ('filter', r'фильтр'), ('perf', r'перфор'), ('packer', r'пакер'), ('bridge', r'мост'),
         ('tubing', r'нкт|лифт|насосно'), ('pay', r'пласт|коллектор|продуктив'),
         ('casing', r'эксплуатационн|э/?к\b'))
KIND_LABELS = {'casing': 'Эксплуатационная колонна', 'tubing': 'НКТ', 'filter': 'Фильтр', 'perf': 'Перфорация',
               'reaming': 'Расширка', 'packer': 'Пакер', 'bridge': 'Цементный мост', 'pay': 'Пласт', 'bottom': 'Забой',
               'artificial': 'Искусственный забой'}
SKIPPED = r'кондуктор|направлени|потайн|хвостовик|техническ'


def classify(element: str) -> str | None:
    """Тип элемента схемы по названию из шаблона конструкции; None — элемент на схему не выносится."""
    text = str(element).lower()
    if re.search(r'искусствен', text):
        return 'artificial'
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


BREAK_M = 50.0          # пустой участок длиннее этого (м) на схеме сжимается; 0 — не сжимать (ручной режим)
BREAK_KEEP_M = 12.0     # высота сжатого участка на схеме, м (подписи — реальные глубины)
FOCUS = ('filter', 'perf', 'reaming', 'packer', 'pay', 'bridge', 'artificial', 'bottom')


def _gaps(items: list[dict[str, Any]], top: float, low: float, threshold: float, pad: float = 6.0) -> list[tuple[float, float]]:
    """Участки окна без элементов фокуса (фильтр, перфорация, расширка, пакер, пласт, мост, пробка, забой) длиннее порога."""
    spans = sorted((max(i['top'] - pad, top), min(i['bottom'] + pad, low)) for i in items
                   if i['kind'] in FOCUS and i['top'] <= low and i['bottom'] >= top)
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    gaps, start = [], top
    for a, b in merged:
        if a - start > threshold:
            gaps.append((start, a))
        start = max(start, b)
    if low - start > threshold:
        gaps.append((start, low))
    return gaps


def _mapper(gaps: list[tuple[float, float]], keep: float):
    """Монотонное преобразование глубины: каждый пустой участок сжат до keep, остальные глубины на месте."""
    def f(d: float) -> float:
        shift = 0.0
        for g0, g1 in gaps:
            length = g1 - g0
            if d <= g0:
                break
            if d < g1:
                return g0 - shift + (d - g0) * keep / length
            shift += length - keep
        return d - shift
    return f


def _ticks(top: float, low: float, gaps: list[tuple[float, float]], f) -> list[list[float]]:
    """Отметки оси в реальных глубинах; внутри сжатого участка отметок нет."""
    span = low - top
    step = next((k for k in (1, 2, 5, 10, 20, 50, 100) if span / k <= 7), 100)
    out = []
    t = math.ceil(top / step) * step
    while t <= low:
        if not any(g0 < t < g1 for g0, g1 in gaps):
            out.append([round(f(t), 2), float(t)])
        t += step
    return out


MERGE = ('casing', 'tubing', 'filter', 'perf', 'reaming', 'pay', 'bridge')      # наложенные интервалы этих типов сливаются в один


def merge_items(items: list[dict[str, Any]], touch: float = .5) -> tuple[list[dict[str, Any]], int]:
    """Перекрывающиеся или стыкующиеся (зазор до ``touch`` м) интервалы одного типа и точные дубли — в один; возвращает и число слитых строк.
    Исходные строки не меняются: слияние только для рисунка, причина видна в пояснении."""
    out: list[dict[str, Any]] = []
    merged = 0
    for kind in dict.fromkeys(i['kind'] for i in items):
        same = sorted((i for i in items if i['kind'] == kind), key=lambda i: (i['top'], i['bottom']))
        if kind not in MERGE:
            out += same
            continue
        for it in same:
            last = out[-1] if out and out[-1]['kind'] == kind else None
            if last is not None and it['top'] <= last['bottom'] + touch:
                merged += 1
                if it['bottom'] > last['bottom']:
                    last.update(bottom=it['bottom'], od=it['od'] or last['od'], id=it['id'] or last['id'])
                last['top'] = min(last['top'], it['top'])
            else:
                out.append(dict(it))
    return out, merged


def schematic(construction: pd.DataFrame, bottom_m: float | None, break_m: float = BREAK_M) -> dict[str, Any]:
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
    raw_items = items                      # проверки логики идут по строкам как есть: слияние для рисунка прятало бы наложения
    items, merged = merge_items([dict(i) for i in items])
    if merged:
        notes.append(f'Перекрывающиеся и дублирующие интервалы одного типа показаны одним: слито строк — {merged}. В таблице конструкции строки остаются как есть.')
    if not items:
        return {'items': [], 'notes': ['Нет конструкции на схему: загрузите снимок конструкции (шаблон «Конструкция»).'],
                'skipped': skipped, 'top': 0, 'bottom': 0, 'bottom_m': bottom_m}
    kinds = {i['kind'] for i in items}
    if 'artificial' in kinds:
        notes.append('Фиолетовая линия — искусственный забой (пробка, глубина от стола); красная — отбитый забой по замеру.')
    if 'casing' not in kinds:
        notes.append('В конструкции нет эксплуатационной колонны: колонна на схеме не показана.')
    if not kinds & {'filter', 'perf'}:
        notes.append('Не указан фильтр или интервал перфорации.')
    # Окно: от точки чуть выше самого верхнего элемента забойной части до забоя; колонна и НКТ идут сверху, их верх не берём.
    tops = [i['top'] for i in items if i['kind'] in ('filter', 'perf', 'reaming', 'packer', 'pay', 'bridge')]
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
    out['checks'] = check_construction(raw_items, bottom_m)      # подсказки: только показать причину, не исправлять
    out['shapes'], out['labels'] = shapes(out)
    out['ticks'] = None
    gaps = _gaps(out['items'], out['top'], out['bottom'], break_m) if break_m and break_m > 0 else []
    if gaps:
        f = _mapper(gaps, BREAK_KEEP_M)
        for sh in out['shapes']:
            for key in ('y0', 'y1'):
                if key in sh:
                    sh[key] = round(f(sh[key]), 3)
            if 'pts' in sh:
                sh['pts'] = [[u, round(f(m), 3)] for u, m in sh['pts']]
        for lab in out['labels']:
            lab['y'] = round(f(lab['y']), 3)
        for g0, g1 in gaps:
            mid = f(g0) + BREAK_KEEP_M / 2
            for dy in (-1.2, 1.2):
                out['shapes'].append({'t': 'line', 'x0': -2.2, 'x1': 2.2, 'y0': mid + dy - .6, 'y1': mid + dy + .6,
                                      'stroke': '#6b7280', 'width': 1.2, 'name': 'break'})
        out['breaks'] = [{'from': round(g0, 1), 'to': round(g1, 1)} for g0, g1 in gaps]
        out['ticks'] = _ticks(out['top'], out['bottom'], gaps, f)
        out['top'], out['bottom'] = round(f(out['top']), 3), round(f(out['bottom']), 3)
        out['notes'].append('Разрыв на схеме: участки без элементов длиннее %g м сжаты (%s). Подписи — реальные глубины.'
                            % (break_m, '; '.join('%g–%g м' % (g[0], g[1]) for g in gaps)))
    out['labels'] = _spread(out['labels'], (out['bottom'] - out['top']) * .045, out['top'], out['bottom'])
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
            # Условное обозначение: перфорация — «пила» вдоль стенки колонны с обеих сторон; зубцов тем больше, чем длиннее интервал.
            teeth = max(3, min(24, int((b - a) / max((low - top) / 48, .5)) + 1))
            ys = np.linspace(a, b, teeth * 2 + 1)
            for sign in (-1, 1):
                pts = [[sign * (1.12 if k % 2 == 0 else 1.6), float(y)] for k, y in enumerate(ys)]
                out.append({'t': 'poly', 'pts': pts, 'stroke': '#e11d48', 'width': 1.6, 'name': 'perf'})
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
    for i in by['bridge']:
        rect(-1.0, 1.0, i['top'], i['bottom'], '#9ca3af', 'cement', 'bridge')
        tag((max(i['top'], top) + min(i['bottom'], low)) / 2, f"Цементный мост {i['top']:g}–{i['bottom']:g} м", '#4b5563')
    for i in by['artificial']:
        if top <= i['top'] <= low:
            out.append({'t': 'line', 'x0': -1.7, 'x1': 1.7, 'y0': i['top'], 'y1': i['top'], 'stroke': '#7c3aed', 'width': 2.5, 'name': 'artificial'})
            tag(i['top'], f"Искусственный забой {i['top']:g} м", '#6d28d9')
    cover, bottom_m = sch.get('covered_m'), sch.get('bottom_m')
    if cover and bottom_m:
        rect(-.95, .95, bottom_m, bottom_m + cover, '#e8c987', 'sand', 'fill')
    if bottom_m and top <= bottom_m <= low:
        out.append({'t': 'line', 'x0': -1.7, 'x1': 1.7, 'y0': bottom_m, 'y1': bottom_m, 'stroke': '#dc2626', 'width': 3, 'name': 'bottom'})
        tag(bottom_m, f'Забой {bottom_m:g} м (отбит)', '#b91c1c')
    return out, labels


def _spread(labels: list[dict[str, Any]], gap: float, top: float, low: float) -> list[dict[str, Any]]:
    """Подписи справа не налезают друг на друга и не выходят за окно: считаем в координатах уже сжатой схемы
    (разводка до сжатия схлопывалась), сдвигаем вниз, а что упёрлось в край окна — поднимаем; выноска ведёт к реальной точке."""
    labels = sorted(labels, key=lambda l: l['y'])
    prev = top - gap
    for label in labels:
        label['at'] = max(label['y'], prev + gap)
        prev = label['at']
    limit = low - gap / 2
    for label in reversed(labels):
        label['at'] = min(label['at'], limit)
        limit = label['at'] - gap
    return labels


def seasons_table(daily: pd.DataFrame, stats: pd.DataFrame, kind: str) -> list[dict[str, Any]]:
    """Сезоны: объём, отработанные дни, максимальный и средний суточный расход, часы и вода."""
    if stats.empty:
        return []
    top, first, last = {}, {}, {}
    if not daily.empty:
        # Qmax — только по отработанным дням (как «Qср» и «Отработано дней»): объём в день с нулём часов не рекорд работы.
        g = daily[daily.gas_volume_m3.notna() & daily.active.fillna(False).astype(bool)]
        for period, part in g.groupby('period', sort=False):
            i = part.gas_volume_m3.idxmax()
            top[period] = (part.gas_volume_m3[i] / 1000, part.date[i])
        for period, part in daily.groupby('period', sort=False):
            first[period], last[period] = part.date.min(), part.date.max()
    rows = []
    for _, s in stats.iterrows():
        peak = top.get(s.period)
        rows.append({'kind': kind, 'period': str(s.period), 'volume': _num(s.gas_volume), 'days': int(s.active_days),
                     'max_rate': _num(peak[0]) if peak else None, 'max_date': _date(peak[1]) if peak else '',
                     'mean_rate': _num(s.mean_active), 'hours': _num(s.hours), 'water': _num(s.water_volume),
                     'coverage': _num(s.coverage), 'end': _date(last.get(s.period)), 'start': pd.Timestamp(first[s.period]).strftime('%Y-%m-%d') if s.period in first else None})
    return rows


def assign_pairs(rows: list[dict[str, Any]], manual: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Пара (цикл): сезон отбора и следующий за ним сезон закачки. Разбор — общий с модулем «Сезонные показатели»
    (``assign_cycles``); ``manual`` — правка инженера: подпись сезона («Закачка 2025») → год начала отбора пары."""
    from atlas.modules import _seasonal as S
    dated = [r for r in rows if r.get('start') is not None and pd.notna(r['start'])]
    if dated:
        frame = pd.DataFrame({'kind': [r['kind'] for r in dated], 'start': [pd.Timestamp(r['start']) for r in dated],
                              'cycle': [S.cycle_of(r['kind'], pd.Timestamp(r['start'])) for r in dated]})
        for r, cycle in zip(dated, S.assign_cycles(frame).cycle):
            r['cycle'] = int(cycle)
    for r in rows:
        if manual and season_label(r['kind'], r['period']) in manual:
            r['cycle'] = int(manual[season_label(r['kind'], r['period'])])
        r.setdefault('cycle', None)
    return rows


def chronological(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сезоны одной таблицей по хронологии: сверху самый свежий, за ним предыдущий другого вида (закачка/отбор) и так далее."""
    def key(r):
        end = pd.to_datetime(r['end'], format='%d.%m.%Y', errors='coerce')
        return (end if pd.notna(end) else pd.Timestamp.min, r['period'])
    return sorted(rows, key=key, reverse=True)


def gdi_table(history: pd.DataFrame) -> list[dict[str, Any]]:
    """Все исследования скважины за всё время; ненадёжные помечены, но не скрыты — решает инженер."""
    rows = []
    if history.empty:
        return rows
    for _, r in history.sort_values('date').iterrows():
        rows.append({'date': _date(r.date), 'method': str(r.method or ''), 'a': _num(r.a), 'b': _num(r.b), 'r2': _num(r.r2),
                     'q_max': _num(r.q_observed), 'q_free': _num(r.q_free), 'reliable': bool(r.reliable), 'by_coef': bool(r.get('by_coef', False)),
                     'note': str(r.note or '')})
    return rows


def gdi_diagrams(raw: pd.DataFrame | None, history: pd.DataFrame, well: str) -> list[dict[str, Any]]:
    """Индикаторные диаграммы: точки режимов (q, Δp²) каждого исследования и коэффициенты a, b его кривой Δp² = a·q + b·q²."""
    if raw is None or raw.empty or history.empty:
        return []
    pts = raw[raw.well.astype(str).eq(str(well)) & raw.q.gt(0) & raw.dp2.notna()]
    out = []
    for _, h in history.sort_values('date', ascending=False).iterrows():
        mine = pts[pts.date.eq(h.date) & pts.method.astype(str).eq(str(h.method)) & pts.study.astype(str).eq(str(h.study))]
        by_coef = bool(h.get('by_coef', False))
        if mine.empty and not by_coef:
            continue
        mine = mine.sort_values('q')
        out.append({'date': _date(h.date), 'method': str(h.method or ''), 'a': _num(h.a), 'b': _num(h.b), 'r2': _num(h.r2),
                    'reliable': bool(h.reliable), 'by_coef': by_coef, 'points': [[float(q), float(d)] for q, d in zip(mine.q, mine.dp2)]})
    return out


def daily_series(daily: pd.DataFrame, kind: str) -> dict[str, list]:
    """Суточные расходы для графика: тыс. м³/сут (объём за календарные сутки) и часы; по дням, где есть газ."""
    if daily.empty:
        return {'date': [], 'volume': [], 'hours': [], 'period': []}
    g = daily[daily.gas_volume_m3.notna()].sort_values('date')
    # Между сезонами линия не тянется через паузу: в разрыв > 3 суток вставляется пустая точка (график рвёт линию).
    gaps = g.date.diff().dt.days.gt(3)
    if gaps.any():
        rows = []
        for i, (d, v, h, per, gap) in enumerate(zip(g.date, g.gas_volume_m3, g.work_hours, g.period, gaps)):
            if gap:
                rows.append((d - pd.Timedelta(days=1), np.nan, np.nan, per))
            rows.append((d, v, h, per))
        g = pd.DataFrame(rows, columns=['date', 'gas_volume_m3', 'work_hours', 'period'])
    return {'date': [pd.Timestamp(d).strftime('%Y-%m-%d') for d in g.date], 'volume': [_num(v / 1000) for v in g.gas_volume_m3],
            'hours': [_num(h) for h in g.work_hours], 'period': [str(p) for p in g.period]}


def consistency(frames, settings, well: str, seasons: list[dict[str, Any]]) -> list[str]:
    """Сверка с модулем «Производительность»: объём и дни сезона в паспорте должны сходиться с ним; расхождение — заметка."""
    if 'production' not in frames:
        return []
    from atlas.engine.modules import production
    d = production.periods(frames['production'], settings.get('season_start', 11), settings.get('season_end', 4))
    notes = []
    for kind, label in KINDS:
        periods = [r['period'] for r in seasons if r['kind'] == kind]
        if not periods:
            continue
        ref = production.averages(d, kind, periods, [well])
        for _, r in ref.iterrows():
            mine = next((x for x in seasons if x['kind'] == kind and x['period'] == str(r.period)), None)
            if mine is None or mine['volume'] is None or pd.isna(r.volume):
                continue
            if abs(mine['volume'] - r.volume) > max(abs(r.volume) * .02, .01) or mine['days'] != int(r.active):
                notes.append(f"{label} {r.period}: в «Производительности» {r.volume:.2f} млн м³ и {int(r.active)} дн., в паспорте "
                             f"{mine['volume']:.2f} млн м³ и {mine['days']} дн..")
    if not notes:
        return []
    head = f'Сверка с «Производительностью»: расхождение в {len(notes)} сезон(ах) (паспорт берёт суточную эксплуатацию, где она есть). '
    return [head + ' '.join(notes[:2])]


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


def season_label(kind: str, period: str) -> str:
    return f'{dict(KINDS)[kind]} {period}'


def build(frames, settings, mapping, well: str, krs: tuple[pd.DataFrame | None, pd.DataFrame | None] = (None, None),
          only: list[str] | None = None) -> dict[str, Any]:
    """Всё для карточки одной скважины. Пустые разделы — заметка, не ошибка.

    ``only`` — подписи сезонов («Отбор 2025-2026»), которые показывать: показатели, таблица сезонов, графики и PDF считаются
    только по ним; пусто или None — все. ГДИ, КРС и конструкция от выбора не зависят."""
    from atlas.engine.modules import well_analysis
    by_kind: dict[str, dict[str, Any]] = {}
    for kind, _ in KINDS:
        by_kind[kind] = dict(well_analysis.analyze(frames, settings, mapping, well, kind))
    first = by_kind['withdrawal']
    seasons = chronological(assign_pairs([row for kind, _ in KINDS for row in seasons_table(by_kind[kind]['daily'], by_kind[kind]['seasons'], kind)],
                                         settings.get('passport_pairs')))
    season_options = [season_label(r['kind'], r['period']) for r in seasons]
    keep = set(only or season_options)
    seasons = [r for r in seasons if season_label(r['kind'], r['period']) in keep]
    for kind, _ in KINDS:       # суточные ряды — только выбранные сезоны
        d = by_kind[kind]['daily']
        if only and not d.empty:
            by_kind[kind]['daily'] = d[d.period.astype(str).map(lambda p, k=kind: season_label(k, p) in keep)]
    gdi_all = gdi_table(first['gdi_history'])
    bottom = first['bottom']
    bottom_m = _num(bottom.iloc[-1].bottom_m) if not bottom.empty else None
    construction = first['construction']
    cons = schematic(construction, bottom_m) if not construction.empty else schematic(pd.DataFrame(
        columns=['element', 'top_m', 'bottom_m']), bottom_m)
    krs = krs_rows(krs[0], krs[1], well)
    out_rows = [r for r in seasons if r['kind'] == 'withdrawal']
    notes_check = consistency(frames, settings, well, seasons)
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
    res = first.get('resource') or {'flag': False}
    if res['flag']:
        kpi.append({'label': 'Пометка «Ресурс»', 'value': None, 'text': 'есть', 'hint': ', '.join(res['kits']),
                    'extra': 'нормальное ГДИ невозможно'})
    notes = list(notes_check)         # пояснения по конструкции и КРС показываются в своих блоках, здесь не повторяются
    if not seasons:
        notes.append('Нет данных по сезонам эксплуатации: загрузите динамику или суточную эксплуатацию.')
    return {'well': well, 'group': mapping.get(well, {}).get('group', ''),
            'construction_date': _date(construction.date.max()) if not construction.empty else '',
            'kpi': kpi, 'seasons': seasons, 'season_options': season_options, 'gdi': gdi_all, 'gdi_diagrams': gdi_diagrams(frames.get('gdi'), first['gdi_history'], well),
            'daily': {kind: daily_series(by_kind[kind]['daily'], kind) for kind, _ in KINDS}, 'krs': krs, 'schematic': cons, 'notes': notes}


def _sum(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [r[key] for r in rows if r[key] is not None]
    return float(sum(values)) if values else None
