"""Таблица плана «блоками»: «2026 РЕКОМЕНДАЦИЯ» / «2026 ФАКТ», группы в строках, месяцы в столбцах → длинный план.

Блок находится по заголовку (год в заголовке), месяцы — по строке заголовков под ним. Результат — обычная длинная таблица
«Группа | Месяц | Режим | План, млн м³», которую дальше читает общий импорт. Блоки «рекомендация» и «план» дают план,
блок «факт» в план не попадает (о нём остаётся заметка). Итоговая строка и пустые ячейки пропускаются, ноль остаётся.
"""
from __future__ import annotations

import re
from itertools import chain, islice
from typing import Iterable

import pandas as pd


TITLE = re.compile(r'^\s*(?:(20\d{2})\s*г?\.?\s*)?(рекомендаци\w*|план\w*|факт\w*)(?:\s*(20\d{2}))?\s*$', re.I)
TOTAL = re.compile(r'(?i)^\s*(всего|итого|суммарно|сумма|по объекту)\s*$')
HEAD = ('Группа', 'Месяц', 'Режим', 'План, млн м³')
SCAN = 40                      # первые строки листа, где ищем заголовок блока
INJECTION_MONTHS = range(4, 11)  # апрель–октябрь — закачка, ноябрь–март — отбор
NOTES: dict[tuple[str, str], list[str]] = {}


def season_kind(month: int) -> str:
    return 'закачка' if month in INJECTION_MONTHS else 'отбор'


def _title(cell):
    if cell is None or isinstance(cell, (int, float)):
        return None
    m = TITLE.match(str(cell))
    if not m:
        return None
    word = m.group(2).lower()
    return (m.group(1) or m.group(3)), 'fact' if word.startswith('факт') else 'plan'


def parse(rows: list[list]):
    """(строки длинной таблицы, заметки) либо None, если блоков нет."""
    from .loader import is_number, month_cell
    titles = [(i, j, *t) for i, r in enumerate(rows) for j, c in enumerate(r) if (t := _title(c))]
    if not titles:
        return None
    # один заголовок на строку (объединённая ячейка может повторяться), порядок сверху вниз
    seen, blocks = set(), []
    for t in titles:
        if t[0] not in seen:
            seen.add(t[0]); blocks.append(t)
    out, notes = [], []
    for n, (i, _j, year, kind) in enumerate(blocks):
        end = blocks[n + 1][0] if n + 1 < len(blocks) else len(rows)
        header = next((h for h in range(i + 1, end) if sum(month_cell(v) is not None for v in rows[h]) >= 2), None)
        if header is None:
            continue
        cols = [j for j, v in enumerate(rows[header]) if month_cell(v) is not None]
        label = (year and f'{year} ') or ''
        name = f'«{label}{"ФАКТ" if kind == "fact" else "РЕКОМЕНДАЦИЯ/ПЛАН"}»'
        gcol = cols[0] - 1
        if gcol < 0:
            continue
        current = int(year) if year else None
        stamps, last = {}, 0
        for j in cols:
            month, own = month_cell(rows[header][j])
            if own:
                current = own
            if current is None:
                raise ValueError('В заголовке блока нет года (например «2026 РЕКОМЕНДАЦИЯ»): добавьте его в заголовок или в названия месяцев.')
            if last and month < last:
                current += 1
            last = month; stamps[j] = pd.Timestamp(year=current, month=month, day=1)
        values = []
        for r in range(header + 1, end):
            row = rows[r]
            group = str(row[gcol]).strip() if gcol < len(row) and row[gcol] is not None else ''
            if not group or TOTAL.match(group):
                continue
            for j in cols:
                v = row[j] if j < len(row) else None
                if v is None or (isinstance(v, str) and not v.strip()) or not is_number(v):
                    continue
                values.append((group, stamps[j], float(str(v).replace(',', '.').replace('\xa0', '').replace(' ', ''))))
        if kind == 'fact':
            notes.append(f'Найден блок {name}: {len(values)} значений, в план не загружен.')
            continue
        out += [[g, d, season_kind(d.month), v] for g, d, v in values]
        notes.append(f'Блок {name}: {len(values)} значений плана.')
    if not out:
        return None
    return out, notes


def convert(path, sheet: str, rows: Iterable[list]):
    """Строки листа → строки длинного плана, если на листе есть блоки; иначе те же строки."""
    it = iter(rows)
    head = list(islice(it, SCAN))
    if not any(_title(c) for r in head for c in r):
        return chain(head, it)
    full = head + list(it)
    parsed = parse(full)
    if parsed is None:
        return iter(full)
    out, notes = parsed
    if len(NOTES) > 200:
        NOTES.clear()
    NOTES[(str(path), sheet)] = notes
    return iter([list(HEAD)] + out)


def to_frame(rows: list[list]) -> pd.DataFrame:
    return pd.DataFrame(rows[1:], columns=rows[0])


def is_converted(raw: pd.DataFrame) -> bool:
    return raw.shape[1] == len(HEAD) and tuple(str(v) for v in raw.iloc[0]) == HEAD if len(raw) else False
