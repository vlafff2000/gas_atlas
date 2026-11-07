"""«База ГИС» (выгрузка all_scripts, pxg_core/gis_export.py, этап А8) → таблицы ГИС проекта Атласа.

Вход — CSV одной таблицы выгрузки: `gis_packs`, `gis_observations` или `gis_intervals` (разделитель «;», десятичная
запятая, UTF-8 с BOM) либо книга «ГИС_свод.xlsx» (листы «Свод», «Интервалы», «Замеры» с русскими заголовками выгрузки).
Таблица узнаётся по заголовкам, имя файла не важно; можно задать таблицу вручную, если заголовки не совпали.
Parquet сюда не входит: для Атласа берётся CSV.
Сохранение — по паре «скважина + дата»: новый файл заменяет замеры той же даты, прежние даты остаются.
"""
from __future__ import annotations

import io
import re

import pandas as pd

# обязательные колонки каждой таблицы; по ним же узнаётся таблица
TABLES: dict[str, tuple[str, ...]] = {
    'gis_packs': ('well', 'date', 'pack', 'h_eff_m', 'kg_avg', 'gvk_abs_m'),
    'gis_intervals': ('well', 'date', 'pack', 'from_m', 'to_m', 'kg'),
    'gis_observations': ('well', 'date', 'status', 'packs'),
    'gis_thermobaric': ('well', 'date', 'depth_m', 'pressure_kgs'),
    'gis_filling': ('well', 'date', 'fill'),
    'gis_annotations': ('well', 'date', 'kind', 'text'),
}
LABELS = {'gis_packs': 'пачки', 'gis_intervals': 'интервалы', 'gis_observations': 'замеры',
          'gis_thermobaric': 'термобарика', 'gis_filling': 'заполнение ствола', 'gis_annotations': 'пометки отчётов'}
# Таблицы из отчётов ГИС (OCR): в них бывают строки не по скважине («Альтитуда», «Касимовское») — они отбрасываются
REPORT_TABLES = ('gis_thermobaric', 'gis_filling', 'gis_annotations')
REPORT_NUMBERS = ('depth_m', 'depth_abs_m', 'temp_c', 'pressure_raw', 'pressure_kgs', 'from_m', 'to_m', 'density_min', 'density_max', 'level_m')
KEY = ['well', 'date']
# русские заголовки книги «ГИС_свод.xlsx» (pxg_core/gis_export.py) → колонки Атласа
RU = {'Скважина': 'well', 'Дата': 'date', 'Дата (точная)': 'date_exact', 'Сезон': 'season', 'Статус': 'status',
      'Текст статуса': 'status_text', 'Качество даты': 'date_quality', 'Пачек': 'packs', 'Лист': 'sheet', 'Строка листа': 'sheet_row',
      'Пачка': 'pack', 'Цвет': 'color', 'Строк': 'intervals', 'Кровля, м': 'top_m', 'Подошва, м': 'bottom_m', 'hг эф, м': 'h_eff_m',
      'Кг ср.взв': 'kg_avg', 'Этаж, м': 'floor_m', 'ГВК': 'gvk_label', 'ГВК глубина, м': 'gvk_depth_m', 'ГВК а.о., м': 'gvk_abs_m',
      'Лишних ГВК': 'gvk_extra', 'Альтитуда, м': 'altitude_m', 'Альтитуда по листу, м': 'altitude_sheet_m',
      'Перфорация верх, м': 'perf_top_m', 'Перфорация низ, м': 'perf_bottom_m', 'Замер': 'investigation', 'От, м': 'from_m',
      'До, м': 'to_m', 'hi, м': 'hi_m', 'Кп': 'kp', 'Кг': 'kg', 'hэф, м': 'h_eff_m', 'ГВК лишний': 'gvk_extra',
      'Кг (текст)': 'kg_text', 'Примечание': 'note', 'Методы': 'methods',
      # «Термобарика» и «Заполнение ствола» книги «БД_ГИС_из_отчётов.xlsx» (pxg_core/gis_report.py)
      'Глубина, м': 'depth_m', 'Глубина а.о., м': 'depth_abs_m', 'Пометка к глубине': 'depth_kind', 'Пометка (как в отчёте)': 'depth_note',
      'Температура, °C': 'temp_c', 'Давление (как в отчёте)': 'pressure_raw', 'Единица давления': 'pressure_unit', 'Давление, кгс/см²': 'pressure_kgs',
      'Режим исследования': 'regime', 'Плотность от, г/см³': 'density_min', 'Плотность до, г/см³': 'density_max',
      'Заполнение (как в отчёте)': 'fill_raw', 'Заполнение': 'fill', 'Уровень жидкости, м': 'level_m', 'Уровень (как в отчёте)': 'level_raw',
      'Откуда': 'origin', 'Вид': 'kind', 'Текст': 'text', 'Файл': 'file', 'Источник': 'source', 'Уверенность': 'confidence', 'Основание': 'basis'}
BOOK_SHEETS = ('Свод', 'Интервалы', 'Замеры', 'Термобарика', 'Заполнение ствола', 'Аннотации')


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


def clean_well(value) -> str:
    """Номер скважины единым видом, как всегда в проекте: «№21», «№ 21», «N21», «21.0» → «21»."""
    text = re.sub(r'^\s*(№|N|#)\s*', '', str(value).strip(), flags=re.I)
    return re.sub(r'^(\d+)\.0+$', r'\1', text).strip()


KG_COLUMNS = ('kg', 'kg_avg')


def kg_to_fraction(column: pd.Series) -> tuple[pd.Series, str]:
    """Кг в доли единицы по ВСЕЙ колонке: все значения > 1 — проценты (/100); все ≤ 1 — доли как есть. Смесь долей и процентов
    в одной колонке (старая и новая выгрузка вперемешку): значения > 1 — проценты, остальные — доли. Второй элемент —
    пояснение, если колонку пришлось переводить (пустая строка — менять нечего). Единица определена по данным: последнее слово за инженером."""
    values = pd.to_numeric(column, errors='coerce')
    over, under = (values > 1).sum(), ((values <= 1) & (values >= 0)).sum()
    if not over:
        return values, ''
    out = values.where(~(values > 1), values / 100)
    if under:
        return out, f'Кг: в колонке смесь долей и процентов — значения больше 1 приняты за проценты ({int(over)} шт.), остальные за доли'
    return out, 'Кг: в колонке проценты — переведены в доли единицы'


def tidy(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Единый вид таблицы базы ГИС при импорте и при чтении проекта: номера скважин без «№», Кг в долях единицы (на экране — проценты)."""
    out, notes = frame.copy(), []
    if 'well' in out:
        out['well'] = out['well'].map(clean_well)
    for column in KG_COLUMNS:
        if column in out:
            out[column], note = kg_to_fraction(out[column])
            if note and note not in notes:
                notes.append(note)
    return out, notes


def _clean(frame: pd.DataFrame, table: str, name: str) -> tuple[pd.DataFrame, list[str]]:
    missing = [c for c in TABLES[table] if c not in frame.columns]
    if missing:
        raise ValueError(f'В файле нет колонок {", ".join(missing)} (таблица «{LABELS[table]}»)')
    frame = frame.copy()
    frame, unit_notes = tidy(frame)
    frame['date'] = _dates(frame['date'])
    bad = frame['well'].isin(['', 'nan']) | frame['date'].isna()
    warnings = [f'Пропущено строк без скважины или даты: {int(bad.sum())}'] if bad.any() else []
    if table in REPORT_TABLES:
        for column in REPORT_NUMBERS:
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors='coerce')
        foreign = ~bad & ~frame['well'].str.contains(r'\d')
        if foreign.any():
            warnings.append(f'Пропущено строк, где вместо номера скважины слово ({", ".join(sorted(frame.loc[foreign, "well"].unique())[:5])}): {int(foreign.sum())}')
        bad |= foreign
    return frame[~bad].reset_index(drop=True), warnings + unit_notes


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
        if 'pack' in frame.columns and kind not in ('gis_observations', 'gis_annotations'):
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
