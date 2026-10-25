"""«База ГИС» (выгрузка all_scripts, pxg_core/gis_export.py, этап А8) → таблицы ГИС проекта Атласа.

Вход — CSV одной таблицы выгрузки: `gis_packs`, `gis_observations` или `gis_intervals` (разделитель «;», десятичная
запятая, UTF-8 с BOM) либо книга «ГИС_свод.xlsx» (листы «Свод», «Интервалы», «Замеры» с русскими заголовками выгрузки).
Таблица узнаётся по заголовкам, имя файла не важно; можно задать таблицу вручную, если заголовки не совпали.
Parquet сюда не входит: для Атласа берётся CSV.
Сохранение — по паре «скважина + дата»: новый файл заменяет замеры той же даты, прежние даты остаются.
"""
from __future__ import annotations

import io

import pandas as pd

# обязательные колонки каждой таблицы; по ним же узнаётся таблица
TABLES: dict[str, tuple[str, ...]] = {
    'gis_packs': ('well', 'date', 'pack', 'h_eff_m', 'kg_avg', 'gvk_abs_m'),
    'gis_intervals': ('well', 'date', 'pack', 'from_m', 'to_m', 'kg'),
    'gis_observations': ('well', 'date', 'status', 'packs'),
}
LABELS = {'gis_packs': 'пачки', 'gis_intervals': 'интервалы', 'gis_observations': 'замеры'}
KEY = ['well', 'date']
# русские заголовки книги «ГИС_свод.xlsx» (pxg_core/gis_export.py) → колонки Атласа
RU = {'Скважина': 'well', 'Дата': 'date', 'Дата (точная)': 'date_exact', 'Сезон': 'season', 'Статус': 'status',
      'Текст статуса': 'status_text', 'Качество даты': 'date_quality', 'Пачек': 'packs', 'Лист': 'sheet', 'Строка листа': 'sheet_row',
      'Пачка': 'pack', 'Цвет': 'color', 'Строк': 'intervals', 'Кровля, м': 'top_m', 'Подошва, м': 'bottom_m', 'hг эф, м': 'h_eff_m',
      'Кг ср.взв': 'kg_avg', 'Этаж, м': 'floor_m', 'ГВК': 'gvk_label', 'ГВК глубина, м': 'gvk_depth_m', 'ГВК а.о., м': 'gvk_abs_m',
      'Лишних ГВК': 'gvk_extra', 'Альтитуда, м': 'altitude_m', 'Альтитуда по листу, м': 'altitude_sheet_m',
      'Перфорация верх, м': 'perf_top_m', 'Перфорация низ, м': 'perf_bottom_m', 'Замер': 'investigation', 'От, м': 'from_m',
      'До, м': 'to_m', 'hi, м': 'hi_m', 'Кп': 'kp', 'Кг': 'kg', 'hэф, м': 'h_eff_m', 'ГВК лишний': 'gvk_extra',
      'Кг (текст)': 'kg_text', 'Примечание': 'note'}
BOOK_SHEETS = ('Свод', 'Интервалы', 'Замеры')


def normalize(columns) -> list[str]:
    """Заголовки в колонки Атласа: русские заголовки книги переводятся, латиница остаётся как есть."""
    return [RU.get(str(c).strip(), str(c).strip()) for c in columns]


def detect(columns) -> str:
    """Таблица по заголовкам: первая, у которой есть все обязательные колонки; пусто — не распознано."""
    have = set(normalize(columns))
    return next((name for name, need in TABLES.items() if set(need) <= have), '')


def _dates(column: pd.Series) -> pd.Series:
    """Даты: настоящие даты и ISO как есть, текст «дд.мм.гггг» — день первым (так пишет Excel выгрузки)."""
    if column.dtype != object:
        return pd.to_datetime(column, errors='coerce')
    text = column.astype(str).str.strip()
    iso = text.str.match(r'^\d{4}-\d{2}-\d{2}')
    out = pd.Series(pd.NaT, index=column.index, dtype='datetime64[ns]')
    out[iso] = pd.to_datetime(text[iso].str[:10], errors='coerce')
    out[~iso] = pd.to_datetime(column[~iso], errors='coerce', dayfirst=True)
    return out


def _clean(frame: pd.DataFrame, table: str, name: str) -> tuple[pd.DataFrame, list[str]]:
    missing = [c for c in TABLES[table] if c not in frame.columns]
    if missing:
        raise ValueError(f'В файле нет колонок {", ".join(missing)} (таблица «{LABELS[table]}»)')
    frame = frame.copy()
    frame['well'] = frame['well'].astype(str).str.strip()
    frame['date'] = _dates(frame['date'])
    bad = frame['well'].isin(['', 'nan']) | frame['date'].isna()
    warnings = [f'Пропущено строк без скважины или даты: {int(bad.sum())}'] if bad.any() else []
    return frame[~bad].reset_index(drop=True), warnings


def is_book(name: str) -> bool:
    return str(name).lower().endswith(('.xlsx', '.xlsm', '.xls'))


def read_all(name: str, content: bytes, table: str = '') -> list[tuple[str, pd.DataFrame, list[str]]]:
    """Все таблицы ГИС из файла: CSV даёт одну, книга «ГИС_свод.xlsx» — до трёх (пачки, интервалы, замеры) по листам.
    В книге берётся первый лист каждой таблицы: листы отдельных пачек повторяют «Свод» и пропускаются.
    Строки без пачки (цвет не подтверждён) в базу не идут, как и в CSV выгрузки."""
    if not is_book(name):
        one = read(name, content, table)
        return [one]
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=object)
    found: dict[str, pd.DataFrame] = {}
    for sheet, frame in sheets.items():
        frame.columns = normalize(frame.columns)
        kind = table or detect(frame.columns)
        if kind and kind not in found and (table or sheet in BOOK_SHEETS or not found):
            if set(TABLES[kind]) <= set(frame.columns) or table:
                found[kind] = frame
    if table:
        found = {table: next(iter(found.values()))} if found else {}
    if not found:
        raise ValueError('Не похоже на книгу «База ГИС»: нет листов «Свод», «Интервалы» или «Замеры» с заголовками выгрузки')
    out = []
    for kind in TABLES:
        if kind not in found:
            continue
        frame = found[kind]
        if 'pack' in frame.columns and kind != 'gis_observations':
            pack = frame['pack'].fillna('').astype(str).str.strip()
            keep = pack != ''
            if kind == 'gis_intervals' and 'from_m' in frame.columns:
                keep |= frame['from_m'].isna()
            frame = frame[keep]
        clean, warnings = _clean(frame, kind, name)
        out.append((kind, clean, warnings))
    return out


def read(name: str, content: bytes, table: str = '') -> tuple[str, pd.DataFrame, list[str]]:
    """Таблица из CSV выгрузки: (имя таблицы, строки, предупреждения). Строки без скважины или даты пропускаются
    с предупреждением, остальное не меняется: правка и исключения — в Атласе, вручную."""
    frame = pd.read_csv(io.BytesIO(content), sep=';', decimal=',', encoding='utf-8-sig', dtype={'well': str, 'Скважина': str})
    frame.columns = normalize(frame.columns)
    table = table or detect(frame.columns)
    if not table:
        raise ValueError('Не похоже на таблицу «База ГИС»: нет ни пачек, ни замеров, ни интервалов из выгрузки')
    clean, warnings = _clean(frame, table, name)
    return table, clean, warnings


def merge(old: pd.DataFrame | None, new: pd.DataFrame, keep_old: bool = False) -> pd.DataFrame:
    """Объединение с прежними замерами проекта. По умолчанию новый файл заменяет даты, которые в нём есть;
    `keep_old` — прежние даты сохраняются, новые добавляются только там, где их не было."""
    if old is None or old.empty:
        return new.reset_index(drop=True)
    old_keys = pd.MultiIndex.from_frame(old[KEY])
    new_keys = pd.MultiIndex.from_frame(new[KEY])
    if keep_old:
        final = pd.concat([old, new[~new_keys.isin(old_keys)]], ignore_index=True)
    else:
        final = pd.concat([old[~old_keys.isin(new_keys)], new], ignore_index=True)
    return final.sort_values(KEY, kind='stable').reset_index(drop=True)
