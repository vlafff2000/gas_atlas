"""«БД давлений по замерам» (Работа с исходными данными → «База давлений по замерам», собирается из месячных отчётов «Результаты замеров»)
→ таблица проекта ``pressure_survey``: сырые замеры по скважинам замерной сетки, одна строка на скважину и дату.

Столбцы: ``well``, ``date``, ``category`` (эксплуатационная, наблюдательная…), ``horizon``, ``p_wellhead`` (Руст), ``p_excess``
(избыточное давление), ``p_res`` (Рпл, кгс/см²), ``level`` (уровень жидкости, м), ``note``, ``source``, ``group``.
Пропуск — NaN: «нет данных» не заменяется нулём, значения не пересчитываются (приведение давлений — «Пересчёт_давлений»).
"""
from __future__ import annotations

import io

import pandas as pd

KIND = 'pressure_survey'
SHEET = 'Данные'
COLUMNS = ['well', 'date', 'category', 'horizon', 'p_wellhead', 'p_excess', 'p_res', 'level', 'note', 'source', 'group']
SOURCE = {'Скважина': 'well', 'Дата': 'date', 'Категория': 'category', 'Горизонт': 'horizon', 'Руст': 'p_wellhead',
          'Избыточное давление': 'p_excess', 'Рпл': 'p_res', 'Уровень жидкости': 'level', 'Примечание': 'note',
          'Источник': 'source', 'ГСП': 'group'}
NUMERIC = ('p_wellhead', 'p_excess', 'p_res', 'level')
TEXT = ('category', 'horizon', 'note', 'source', 'group')
EXCEL = ('.xlsx', '.xlsm', '.xls')
NEED = {'Скважина', 'Дата', 'Категория', 'Руст'}


def looks_like(tables: dict[str, pd.DataFrame]) -> bool:
    """Лист «Данные» с шапкой Скважина, Дата, Категория, Руст (сырая база замеров Базы ПХГ)."""
    raw = tables.get(SHEET)
    return raw is not None and not raw.empty and NEED <= {str(v).strip() for v in raw.iloc[0].tolist()}


def _well(value) -> str:
    text = str(value).strip()
    if text.lower() in ('', 'nan', 'none'):
        return ''
    try:
        number = float(text.replace(',', '.'))
        return str(int(number)) if number.is_integer() else text
    except ValueError:
        return text


def read(name: str, content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Замеры из книги и замечания. Нет листа «Данные» с нужными колонками — ValueError с подсказкой."""
    if not str(name).lower().endswith(EXCEL):
        raise ValueError('нужна книга Excel «БД давлений по замерам» из Базы ПХГ')
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
    src = sheets.get(SHEET)
    if src is None or not NEED <= set(map(str, src.columns)):
        raise ValueError('нет листа «Данные» с колонками Скважина, Дата, Категория, Руст. Нужна «БД давлений по замерам» из «Работы с исходными данными»')
    d = src.rename(columns=lambda c: SOURCE.get(str(c).strip(), c))
    for col in COLUMNS:
        if col not in d:
            d[col] = pd.NA
    d = d[COLUMNS].copy()
    d['well'] = d['well'].map(_well)
    d['date'] = pd.to_datetime(d['date'], errors='coerce', dayfirst=True)
    warnings: list[str] = []
    bad = d.well.eq('') | d.date.isna()
    if bad.any():
        warnings.append(f'Пропущено строк без номера скважины или даты: {int(bad.sum())}')
    d = d[~bad]
    for col in NUMERIC:
        d[col] = pd.to_numeric(d[col], errors='coerce')
    for col in TEXT:
        d[col] = d[col].map(lambda v: '' if v is None or pd.isna(v) else str(v).strip())
    d = d.drop_duplicates(['well', 'date'], keep='last').reset_index(drop=True)
    return d, warnings


def merge(old: pd.DataFrame | None, new: pd.DataFrame, keep_old: bool = False) -> pd.DataFrame:
    """Новый файл заменяет замеры той же скважины и даты; «оставить прежние» — только добавляет пары, которых ещё нет."""
    if old is None or old.empty:
        return new.reset_index(drop=True)
    key = ['well', 'date']
    if keep_old:
        fresh = new.merge(old[key].drop_duplicates(), on=key, how='left', indicator=True)
        return pd.concat([old, fresh[fresh['_merge'].eq('left_only')].drop(columns='_merge')], ignore_index=True)
    mark = old.merge(new[key].drop_duplicates(), on=key, how='left', indicator=True)['_merge'].eq('both').to_numpy()
    return pd.concat([old[~mark], new], ignore_index=True)


def summary(d: pd.DataFrame) -> str:
    return (f'замеров {len(d)}, скважин {d.well.nunique()}, с Рпл {int(d.p_res.notna().sum())}, '
            f'период {d.date.min():%d.%m.%Y}–{d.date.max():%d.%m.%Y}')
