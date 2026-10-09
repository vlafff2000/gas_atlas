"""Импорт газогидрохимических исследований (ГГХ): состав водорастворённого газа по скважинам и датам отбора.

Формат — лист «Общий» книги отчёта: по строке на отбор пробы; шапка с «№№ скв.» и «Дата отбора»,
затем горизонт, уровень, глубина, газонасыщенность, компоненты газа (СН4 … СО2, СО), «Сумма УВ», «Сумма анализа».
Названия колонок распознаются без учёта регистра и без различия русских и латинских букв (в файлах «Не», «Н2», «СО2»
пишут и теми, и другими), числа с запятой читаются как числа. Чистая функция: файлов не пишет.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from .config import NODATA

# каноническое имя → (подпись, единица)
COLUMNS = {
    'well': 'Скважина', 'date': 'Дата отбора', 'horizon': 'Водоносный горизонт', 'level': 'Уровень, м',
    'depth': 'Глубина отбора проб, м', 'method': 'Способ отбора проб', 'gas': 'Газонасыщенность, см³/л',
    'ch4': 'СН4', 'c2h6': 'С2Н6', 'c3h8': 'С3Н8', 'c4h10': 'С4Н10+ТУ', 'hc': 'Сумма УВ', 'he': 'Не', 'h2': 'Н2',
    'n2': 'N2', 'o2': 'О2', 'co2': 'СО2', 'co': 'СО', 'total': 'Сумма анализа',
}
NUMERIC = ('level', 'depth', 'gas', 'ch4', 'c2h6', 'c3h8', 'c4h10', 'hc', 'he', 'h2', 'n2', 'o2', 'co2', 'co', 'total')
TEXT = ('well', 'horizon', 'method')
# Ключ колонки — заглавные латинские буквы и цифры: «СО2» (кириллица) и «CO2» (латиница) дают один ключ.
_LOOKALIKE = str.maketrans('АВЕКМНОРСТХ', 'ABEKMHOPCTX')
_HEADERS = {
    'well': ('№№СКВ', '№СКВ', 'СКВАЖИНА', 'НОМЕРСКВАЖИНЫ', 'СКВ'), 'date': ('ДАТАОТБОРА', 'ДАТА'),
    'horizon': ('ВОДОНОСНЫЙГОРИЗОНТ', 'ГОРИЗОНТ'), 'level': ('УРОВЕНЬ',), 'method': ('СПОСОБОТБОРАПРОБ',),
    'ch4': ('CH4', 'CH4'), 'c2h6': ('C2H6',), 'c3h8': ('C3H8',), 'c4h10': ('C4H10+TY', 'C4H10', 'C4H10+ТУ'),
    'hc': ('СУММАУВ',), 'he': ('HE',), 'h2': ('H2',), 'n2': ('N2',), 'o2': ('O2',), 'co2': ('CO2',), 'co': ('CO',),
    'total': ('СУММААНАЛИЗА',),
}
HEADER_SEARCH = 20          # шапку ищем в первых строках листа


def _key(value: Any) -> str:
    text = re.sub(r'[\s.,;:()\[\]]+', '', str(value).upper().translate(_LOOKALIKE)).replace('Ё', 'Е')
    return text


def _field(header: Any) -> str | None:
    key = _key(header)
    if not key or key == 'NAN':
        return None
    if key.startswith((_key('ГАЗОНАСЫЩ'), _key('ГАЗОСОДЕРЖ'))):
        return 'gas'
    if key.startswith((_key('ГЛУБИНАОТБОРА'), _key('ГЛУБИНАПРОБ'))):
        return 'depth'
    for name, variants in _HEADERS.items():
        if key in {_key(v) for v in variants}:
            return name
    return None


def find_header(raw: pd.DataFrame) -> int | None:
    """Номер строки шапки (с нуля) или ``None``: строка, где есть и скважина, и дата отбора."""
    for i in range(min(HEADER_SEARCH, len(raw))):
        found = {_field(v) for v in raw.iloc[i].tolist()}
        if 'well' in found and 'date' in found:
            return i
    return None


def nodata_cells(series: pd.Series) -> pd.Series:
    """Ячейки с условным «нет данных»: не считаются нечитаемым текстом."""
    text = series.astype(str).str.replace(',', '.', regex=False).str.replace(r'[\s ]+', '', regex=True)
    return pd.to_numeric(text.where(series.notna()), errors='coerce').isin(NODATA)


def clean_number(series: pd.Series) -> pd.Series:
    """Число с запятой и пробелами → число; нечитаемое → NaN (как в скрипте построения)."""
    if pd.api.types.is_numeric_dtype(series):
        out = series.astype(float)
    else:
        text = series.astype(str).str.replace(',', '.', regex=False).str.replace(r'[\s ]+', '', regex=True)
        out = pd.to_numeric(text.where(series.notna()), errors='coerce')
    return out.mask(out.isin(NODATA))      # −999,25 и подобное — «нет данных», а не измерение


def normalize(raw: pd.DataFrame, header: int | None = None) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Лист → (таблица ГГХ в канонических колонках, замечания по строкам).

    Замечание — словарь ``{Строка, Уровень, Причина}``; строка считается как в Excel (с единицы).
    Бросает ``ValueError``, если на листе нет шапки ГГХ.
    """
    start = find_header(raw) if header is None else header
    if start is None:
        raise ValueError('На листе не найдена шапка ГГХ: нужны колонки «№№ скв.» и «Дата отбора».')
    names = [_field(v) for v in raw.iloc[start].tolist()]
    columns: dict[str, int] = {}
    for j, name in enumerate(names):
        if name and name not in columns:
            columns[name] = j
    body = raw.iloc[start + 1:]
    data = pd.DataFrame({name: body.iloc[:, j].to_numpy() for name, j in columns.items()}, index=body.index)
    notes: list[dict[str, Any]] = []
    excel_row = lambda idx: int(idx) + 1   # noqa: E731  (индексы сырого листа идут с нуля подряд)

    for name in TEXT:
        data[name] = data[name].map(lambda v: '' if pd.isna(v) else str(v).strip()) if name in data else ''
    data['horizon'] = data.horizon.map(lambda v: v[:1].upper() + v[1:].lower())    # «Задонско-Елецкий» и «Задонско-елецкий» — один горизонт
    data['well'] = data.well.map(lambda v: v[:-2] if re.fullmatch(r'\d+\.0', v) else v)
    dates = pd.to_datetime(data['date'], errors='coerce', dayfirst=True) if 'date' in data else pd.Series(pd.NaT, index=data.index)
    data['date'] = dates

    empty = data.well.eq('') & data.date.isna() & data[[c for c in NUMERIC if c in data]].isna().all(axis=1)
    unused = data.well.str.contains('неиспольз', case=False)
    no_well = data.well.eq('') & ~empty
    no_date = data.date.isna() & ~empty & ~no_well & ~unused
    for idx in data.index[unused]:
        notes.append({'Строка': excel_row(idx), 'Уровень': 'Пропущено', 'Причина': 'Строка помечена как неиспользуемые данные'})
    for idx in data.index[no_well]:
        notes.append({'Строка': excel_row(idx), 'Уровень': 'Ошибка', 'Причина': 'Нет номера скважины'})
    for idx in data.index[no_date]:
        notes.append({'Строка': excel_row(idx), 'Уровень': 'Ошибка', 'Причина': f'Скважина {data.well[idx]}: нет даты отбора'})

    for name in NUMERIC:
        if name not in data:
            data[name] = np.nan
            continue
        before = data[name]
        data[name] = clean_number(before)
        bad = before.notna() & data[name].isna() & before.astype(str).str.strip().ne('') & ~nodata_cells(before)
        for idx in data.index[bad & ~(empty | unused | no_well | no_date)]:
            notes.append({'Строка': excel_row(idx), 'Уровень': 'Предупреждение',
                          'Причина': f'«{COLUMNS[name]}»: не число «{before[idx]}», значение не загружено'})
    keep = ~(empty | unused | no_well | no_date)
    out = data.loc[keep, list(COLUMNS)].copy()
    out['date'] = pd.to_datetime(out['date']).dt.normalize()
    dup = out.duplicated(['well', 'date'], keep='first')
    for idx in out.index[dup]:
        notes.append({'Строка': excel_row(idx), 'Уровень': 'Предупреждение',
                      'Причина': f'Скважина {out.well[idx]}: повтор даты {out.date[idx]:%d.%m.%Y}, оставлена первая запись'})
    out = out[~dup].sort_values(['well', 'date'], kind='stable').reset_index(drop=True)
    if out.empty:
        raise ValueError('На листе нет строк с номером скважины и датой отбора.')
    return out, sorted(notes, key=lambda n: n['Строка'])


def find_sheet(tables: dict[str, pd.DataFrame]) -> str | None:
    """Лист с шапкой ГГХ; при нескольких — с наибольшим числом строк (в книге отчёта это «Общий»)."""
    best, size = None, -1
    for name, raw in tables.items():
        if raw is None or raw.empty or raw.shape[1] < 5:
            continue
        if find_header(raw) is not None and len(raw) > size:
            best, size = name, len(raw)
    return best


def merge(old: pd.DataFrame | None, new: pd.DataFrame, mode: str = 'merge') -> pd.DataFrame:
    """``merge`` — добавить, при совпадении «скважина + дата» берётся новая запись; ``replace`` — только новые."""
    if old is None or old.empty or mode == 'replace':
        return new.reset_index(drop=True)
    old = old.drop(columns=['_point_id'], errors='ignore')
    key = lambda f: pd.MultiIndex.from_arrays([f.well.astype(str), pd.to_datetime(f.date)])   # noqa: E731
    keep = ~key(old).isin(key(new))
    return pd.concat([old[keep], new], ignore_index=True).sort_values(['well', 'date'], kind='stable').reset_index(drop=True)
