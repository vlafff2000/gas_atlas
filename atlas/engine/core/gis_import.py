"""«База ГИС» (выгрузка all_scripts, pxg_core/gis_export.py, этап А8) → таблицы ГИС проекта Атласа.

Вход — CSV одной таблицы выгрузки: `gis_packs`, `gis_observations` или `gis_intervals` (разделитель «;», десятичная
запятая, UTF-8 с BOM). Таблица узнаётся по заголовкам, имя файла не важно; можно задать таблицу вручную, если заголовки
не совпали. Колонки — латиница Атласа, как в выгрузке. Parquet и Excel сюда не входят: для Атласа берётся CSV.
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


def detect(columns) -> str:
    """Таблица по заголовкам: первая, у которой есть все обязательные колонки; пусто — не распознано."""
    have = set(map(str, columns))
    return next((name for name, need in TABLES.items() if set(need) <= have), '')


def read(name: str, content: bytes, table: str = '') -> tuple[str, pd.DataFrame, list[str]]:
    """Таблица из файла выгрузки: (имя таблицы, строки, предупреждения). Строки без скважины или даты пропускаются
    с предупреждением, остальное не меняется: правка и исключения — в Атласе, вручную."""
    frame = pd.read_csv(io.BytesIO(content), sep=';', decimal=',', encoding='utf-8-sig', dtype={'well': str})
    frame.columns = [str(c).strip() for c in frame.columns]
    table = table or detect(frame.columns)
    if not table:
        raise ValueError('Не похоже на таблицу «База ГИС»: нет ни пачек, ни замеров, ни интервалов из выгрузки')
    missing = [c for c in TABLES[table] if c not in frame.columns]
    if missing:
        raise ValueError(f'В файле нет колонок {", ".join(missing)} (таблица «{LABELS[table]}»)')
    frame['well'] = frame['well'].astype(str).str.strip()
    frame['date'] = pd.to_datetime(frame['date'], errors='coerce')
    bad = frame['well'].isin(['', 'nan']) | frame['date'].isna()
    warnings = [f'Пропущено строк без скважины или даты: {int(bad.sum())}'] if bad.any() else []
    return table, frame[~bad].reset_index(drop=True), warnings


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
