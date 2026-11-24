"""Вид ремонта КРС по названию и кодам работ (общий для таблицы «Ремонты», справки о выполнении плана КР и «Справки ГДИ»).

Названия видов совпадают с книгой ``КРС_для_Атласа.xlsx`` (all_scripts, ``pxg_core/krs.py``). Читаются ВСЕ виды ремонтов; вид, который не узнан,
остаётся ``OTHER`` и показывается с исходным текстом работ, а не пропадает. Вид — подсказка: решает инженер (ручная правка вида в таблице ремонтов).
Окно наблюдения (счёт ревизий КРУ) сбрасывают замена фильтра и армирование; остальные виды — нет (``RESETTING``).
"""
from __future__ import annotations

import re

FILTER, CT, CTS, ARM = 'Замена фильтра', 'Колтюбинг без СКО', 'Колтюбинг с СКО / СКО', 'Армирование ПЗП'
ISOL, COLUMN, PLUG, KILL = 'Восстановление герметичности ЦК / изоляция', 'Ремонт колонны', 'Ликвидация пробки', 'Глушение скважины'
OTHER = 'Тип не определён'
ORDER = (FILTER, ARM, ISOL, COLUMN, CTS, CT, PLUG, KILL)       # в ремонте несколько видов работ: главным считается первый по порядку
RESETTING = (FILTER, ARM)
CODE_KINDS = {'1.094': FILTER, '2.013': ARM, '4.033': CTS, '2.022': PLUG, '7.02': KILL}
CODE = re.compile(r'(?:КР|ИС)\s*(\d+(?:\.\d+)?)')


def in_text(text) -> set:
    """Все виды работ в названии."""
    low = ' '.join(str(text or '').lower().split())
    found = set()
    if 'фильтр' in low and ('замен' in low or 'установ' in low):
        found.add(FILTER)
    if 'армирован' in low or ('закреплен' in low and 'пзп' in low):
        found.add(ARM)
    if re.search(r'герметичн|цемент|изоляц|переток|заколонн|\bрир\b', low):
        found.add(ISOL)
    if re.search(r'ремонт\w*\s+(?:эксплуатационной\s+)?(?:обсадн\w+\s+)?колонн|смяти|обсадн\w+\s+колонн|замен\w+\s+колонн|ремонт\s+эк\b', low):
        found.add(COLUMN)
    if 'колтюбинг' in low:
        found.add(CTS if re.search(r'\bско\b|кислот', low) and 'без ско' not in low else CT)
    elif re.search(r'\bско\b|кислотн', low):
        found.add(CTS)
    elif 'промывк' in low or 'промыв' in low:
        found.add(CT)
    if 'пробк' in low and re.search(r'ликвидац|промыв|разбур', low):
        found.add(PLUG)
    if 'глушен' in low:
        found.add(KILL)
    return found


def of_text(text) -> str:
    """Главный вид по названию работ; не узнан — ``OTHER``."""
    found = in_text(text)
    return next((k for k in ORDER if k in found), OTHER)


def of_codes(codes, text='') -> str:
    """Вид по кодам работ («КР 1.094; КР 4.033») и названиям: известный код главнее текста."""
    found = {CODE_KINDS[n] for n in CODE.findall(str(codes or '')) if n in CODE_KINDS}
    by_text = of_text(text)
    if by_text != OTHER:
        found.add(by_text)
    return next((k for k in ORDER if k in found), OTHER)


def all_of(codes, text='', main='') -> list[str]:
    """ВСЕ виды работ ремонта (не только главный), по порядку важности; ничего не узнано — ``[OTHER]``. ``main`` — вид, записанный в таблице ремонтов."""
    found = {CODE_KINDS[n] for n in CODE.findall(str(codes or '')) if n in CODE_KINDS} | in_text(text)
    found |= {k for k in in_text(codes)}
    if main in ORDER:
        found.add(main)
    return [k for k in ORDER if k in found] or [OTHER]
