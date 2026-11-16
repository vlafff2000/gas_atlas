"""План КР на год (Excel «План КР 2026»: номер скважины, наименование, инвентарный номер, краткое описание работ, начало и окончание работ) → набор ``krs_plan``.

Строки плана — ориентировочные даты, только для местной сверки в Атласе: ``source`` = «план». Фактические даты и таблица 7.1 берутся только из справки о
выполнении плана КР (строки с пустым ``source``); план их не заменяет. Строки с «-» вместо номера скважины пропускаются с предупреждением.
Если скважина и год уже есть в справке, строка плана не добавляется.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from . import krs_import, tabular

KIND = 'krs_plan'
SOURCE_PLAN = 'план'
NEED = ('Номер скважины', 'Краткое описание работ', 'Начало работ', 'Окончание работ')
CODE = re.compile(r'(КР|ИС|ТР)\s*(\d+(?:\.\d+)?)\s*[-–—]?\s*([А-ЯA-Z]{1,3})?')
GROUP = re.compile(r'ГСП[-\s]?(\d+)', re.I)


def _find(raw: pd.DataFrame):
    for i in range(min(len(raw), 12)):
        values = {str(v).strip() for v in raw.iloc[i].tolist() if pd.notna(v)}
        if set(NEED) <= values:
            return i
    return None


def looks_like(tables: dict[str, pd.DataFrame]) -> bool:
    return any(raw is not None and not raw.empty and _find(raw) is not None for raw in tables.values())


def _date(value):
    if pd.isna(value):
        return pd.NaT
    if isinstance(value, (int, float)):
        return pd.to_datetime(value, unit='D', origin='1899-12-30')
    return pd.to_datetime(value, dayfirst=True, errors='coerce')


def read(name: str, content: bytes) -> tuple[pd.DataFrame, list[str]]:
    if not str(name).lower().endswith(('.xlsx', '.xlsm', '.xls')):
        raise ValueError('нужен файл Excel с планом КР (.xlsx)')
    _, tables = tabular.read_content(content, name)
    sheet = next((raw for raw in tables.values() if raw is not None and not raw.empty and _find(raw) is not None), None)
    if sheet is None:
        raise ValueError('нет листа с колонками «Номер скважины», «Краткое описание работ», «Начало работ», «Окончание работ»')
    head = _find(sheet)
    body = sheet.iloc[head + 1:].copy()
    body.columns = [str(v).strip() if pd.notna(v) else f'_{i}' for i, v in enumerate(sheet.iloc[head].tolist())]
    warnings: list[str] = []
    rows, skipped = [], 0
    for _, r in body.iterrows():
        well = krs_import.well_id(r.get('Номер скважины'))
        if not well or not re.fullmatch(r'\d+\w?', well):
            if any(pd.notna(r.get(c)) and str(r.get(c)).strip() for c in NEED[1:]):
                skipped += 1
            continue
        start, end = _date(r.get('Начало работ')), _date(r.get('Окончание работ'))
        text = re.sub(r'\s+', ' ', str(r.get('Краткое описание работ') or '')).strip()
        code = CODE.search(text)
        year = (start if pd.notna(start) else end).year if pd.notna(start) or pd.notna(end) else None
        label = f'{code.group(1)} {code.group(2)}' + (f'-{code.group(3)}' if code.group(3) else '') if code else ''
        rows.append({'Скважина': well, 'Год': year, 'Вид': code.group(1) if code else 'КР', 'Шифры работ': text, 'Коды работ': label,
                     'Дата начала': start.strftime('%d.%m.%Y') if pd.notna(start) else '', 'Дата окончания': end.strftime('%d.%m.%Y') if pd.notna(end) else '',
                     'Состояние': 'Запланировано', 'Статус справки': 'План (ориентировочные даты)', 'Ремонт будет': 'Да', 'В таблицу 7.1': 'Нет',
                     'Проверить': '' if year else 'нет дат работ'})
    if skipped:
        warnings.append(f'План КР: пропущено строк без номера скважины («-» и пустые): {skipped}')
    plan = krs_import.read_plan(pd.DataFrame(rows)) if rows else pd.DataFrame(columns=krs_import.PLAN_COLUMNS)
    plan['source'] = SOURCE_PLAN
    return plan, warnings


def merge(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """Новый план заменяет прежние строки плана тех же скважин; справка не затрагивается и приоритетнее: пара «скважина + год» из справки не дублируется."""
    if 'source' not in new:
        new = new.assign(source=SOURCE_PLAN)
    if old is None or old.empty:
        return new.reset_index(drop=True)
    old = old.copy()
    if 'source' not in old:
        old['source'] = ''
    old['source'] = old['source'].fillna('')
    kept = old[~(old.source.eq(SOURCE_PLAN) & old.well.isin(set(new.well)))]
    fact = set(zip(kept[kept.source.ne(SOURCE_PLAN)].well, kept[kept.source.ne(SOURCE_PLAN)].year))
    add = new[[(w, y) not in fact for w, y in zip(new.well, new.year)]]
    return pd.concat([kept, add], ignore_index=True)


def actual(plan: pd.DataFrame | None) -> pd.DataFrame | None:
    """Только строки справки (фактические даты): для таблицы 7.1, событий на графиках и дат ремонтов; план в выгрузки не попадает."""
    if plan is None or plan.empty or 'source' not in plan:
        return plan
    return plan[plan['source'].fillna('').ne(SOURCE_PLAN)]


def summary(plan: pd.DataFrame) -> str:
    return f'план КР: строк {len(plan)}, скважин {plan.well.nunique()}'
