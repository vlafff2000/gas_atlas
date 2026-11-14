"""Подсказки-проверки схемы скважины: логика расположения элементов конструкции.

Только подсказки с видимой причиной: ничего не исправляется и не скрывается, итоговое слово за инженером.
Вход — элементы схемы (``atlas.passport_card.schematic``: ``kind``, ``top``, ``bottom``, ``comment`` в метрах от стола)
и отбитый забой. Выход — список ``{'code', 'level', 'text', 'top', 'bottom'}``; ``top``/``bottom`` — интервал для подсветки или None.
"""
from __future__ import annotations

import re
from typing import Any

TOL_M = .5                  # допуск на округление глубин
OVERLAP_SHARE = .5          # доля более короткого интервала, после которой наложение однотипных интервалов считается сильным
CUT = re.compile(r'расшир|фрез|вырез|подзабой|каверн', re.I)
NAMES = {'casing': 'эксплуатационная колонна', 'tubing': 'НКТ', 'filter': 'фильтр', 'perf': 'перфорация'}


def _chk(code: str, level: str, text: str, top: float | None = None, bottom: float | None = None) -> dict[str, Any]:
    return {'code': code, 'level': level, 'text': text, 'top': top, 'bottom': bottom}


def check_construction(items: list[dict[str, Any]], bottom_m: float | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    of = lambda *kinds: [i for i in items if i['kind'] in kinds]
    for i in items:
        if i['top'] > i['bottom'] + 1e-9:
            out.append(_chk('inverted', 'warning', f"{i['label']}: верх {i['top']:g} м глубже низа {i['bottom']:g} м (интервал перевёрнут). "
                            'Проверьте, не перепутаны ли столбцы в таблице конструкции.', i['bottom'], i['top']))
    casing, tubing = of('casing'), of('tubing')
    working = of('filter', 'perf')
    cased_out = bool(of('reaming')) or any(CUT.search(i.get('comment') or '') or CUT.search(i['label']) for i in items)
    if casing and working:
        shoe, deep = max(c['bottom'] for c in casing), max(w['bottom'] for w in working)
        if shoe < deep - TOL_M:
            reason = 'есть расширка/фрезерование: часть колонны может быть вырезана' if cased_out else 'колонна обычно ниже фильтров и перфораций'
            out.append(_chk('casing_above_work', 'info' if cased_out else 'warning',
                            f'Башмак колонны {shoe:g} м выше низа фильтра/перфорации {deep:g} м на {deep - shoe:.1f} м: {reason}.', shoe, deep))
    if tubing:
        tube = max(t['bottom'] for t in tubing)
        if casing and tube > max(c['bottom'] for c in casing) + TOL_M:
            shoe = max(c['bottom'] for c in casing)
            out.append(_chk('tubing_below_casing', 'warning', f'Башмак НКТ {tube:g} м глубже башмака колонны {shoe:g} м '
                            f'на {tube - shoe:.1f} м: НКТ не может быть глубже колонны.', shoe, tube))
        if working and tube > max(w['bottom'] for w in working) + TOL_M:
            deep = max(w['bottom'] for w in working)
            out.append(_chk('tubing_below_work', 'warning', f'Башмак НКТ {tube:g} м глубже низа фильтра/перфорации {deep:g} м '
                            f'на {tube - deep:.1f} м: НКТ не должна быть глубже интервала работы.', deep, tube))
    art = of('artificial')
    if art:
        iz = max(a['top'] for a in art)
        for name, kind in (('НКТ', 'tubing'), ('фильтр', 'filter'), ('перфорация', 'perf')):
            deep = max((i['bottom'] for i in of(kind)), default=None)
            if deep is not None and deep > iz + TOL_M:
                out.append(_chk('below_artificial', 'warning', f'{name[:1].upper() + name[1:]}: низ {deep:g} м глубже искусственного забоя {iz:g} м '
                                f'на {deep - iz:.1f} м: ниже забоя элементов быть не может. Проверьте глубину забоя или интервал.', iz, deep))
        if casing and iz > max(c['bottom'] for c in casing) + TOL_M and not (cased_out or of('reaming')):
            shoe = max(c['bottom'] for c in casing)
            out.append(_chk('artificial_below_shoe', 'info', f'Искусственный забой {iz:g} м глубже башмака колонны {shoe:g} м на {iz - shoe:.1f} м: '
                            'если ниже башмака открытый ствол или хвостовик, это норма; иначе проверьте данные.', shoe, iz))
        if bottom_m is not None and abs(bottom_m - iz) > TOL_M:
            where = 'глубже' if bottom_m > iz else 'выше'
            out.append(_chk('current_vs_artificial', 'warning' if bottom_m > iz else 'info',
                            f'Текущий забой по замеру {bottom_m:g} м {where} искусственного {iz:g} м на {abs(bottom_m - iz):.1f} м. '
                            + ('Прибор не может дойти глубже искусственного забоя: проверьте оба значения.' if bottom_m > iz else
                               'Выше искусственного забоя — возможна пробка или отложения.'), min(bottom_m, iz), max(bottom_m, iz)))
    if bottom_m is not None and working:
        top_w = min(w['top'] for w in working)
        if bottom_m < top_w - TOL_M:
            out.append(_chk('bottom_above_filter', 'warning', f'Отбитый забой {bottom_m:g} м выше верха фильтра/перфорации {top_w:g} м: '
                            'интервал перекрыт целиком. Проверьте замер забоя.', bottom_m, top_w))
    for kind, name in NAMES.items():
        group = sorted(of(kind), key=lambda i: (i['top'], i['bottom']))
        for a, b in zip(group, group[1:]):
            lo, hi = b['top'], min(a['bottom'], b['bottom'])
            short = min(a['bottom'] - a['top'], b['bottom'] - b['top'])
            if hi - lo > TOL_M and short > 0 and (hi - lo) / short >= OVERLAP_SHARE:
                out.append(_chk('overlap', 'warning', f"Два интервала ({name}) {a['top']:g}–{a['bottom']:g} м и {b['top']:g}–{b['bottom']:g} м "
                                f'накладываются на {hi - lo:.1f} м: возможен дубль строки или разные снимки.', lo, hi))
    return out
