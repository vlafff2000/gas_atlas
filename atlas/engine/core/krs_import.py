"""КРС: книга ``КРС_для_Атласа.xlsx`` («Работа с исходными данными» → «Состояние скважин и приоритет КР») → две таблицы проекта.

- ``krs_works`` — проведённые капитальные ремонты, одна строка на ремонт: ``well``, ``year``, ``work_type``, ``detail``
  (лист «Ремонты»; прочие столбцы листа склеиваются в ``detail``);
- ``krs_plan`` — необязательный лист «План КР» (справка о выполнении плана КР): скважина × ремонт, шифры работ, даты, состояние,
  статус, «Ремонт будет», «В таблицу 7.1»;
- ``krs_priority`` — приоритет КР по скважине, одна строка на скважину: ``well``, ``group``, ``priority`` (итог), ``priority_calc``,
  ``priority_manual``, ``sand`` (сезоны с песком), ``last_year``, ``last_type``, ``planned``, ``reason`` (лист «Приоритет»).
Приоритет — подсказка (1 — срочно), ручное значение главнее расчёта: решает инженер. Скважина — номер текстом без «.0».
Пропуск — NaN/пусто: «нет данных» не заменяется нулём.
"""
from __future__ import annotations

import io

import pandas as pd

WORKS, PRIORITY, PLAN = 'krs_works', 'krs_priority', 'krs_plan'
LABELS = {WORKS: 'проведённые КР', PRIORITY: 'приоритет КР', PLAN: 'план и выполнение КР'}
SHEETS = {WORKS: 'Ремонты', PRIORITY: 'Приоритет', PLAN: 'План КР'}
PLAN_COLUMNS = ['well', 'year', 'well_type', 'kind', 'works', 'codes', 'quarter', 'color', 'state', 'start', 'end', 'status', 'will',
                'in_table', 'check']
PLAN_SOURCE = {'Скважина': 'well', 'Год': 'year', 'Тип скважины': 'well_type', 'Вид': 'kind', 'Шифры работ': 'works', 'Коды работ': 'codes',
               'Квартал': 'quarter', 'Цвет в справке': 'color', 'Состояние': 'state', 'Дата начала': 'start', 'Дата окончания': 'end',
               'Статус справки': 'status', 'Ремонт будет': 'will', 'В таблицу 7.1': 'in_table', 'Проверить': 'check'}
WORKS_COLUMNS = ['well', 'year', 'work_type', 'detail']
PRIORITY_COLUMNS = ['well', 'group', 'priority', 'priority_calc', 'priority_manual', 'sand', 'last_year', 'last_type', 'planned',
                    'reason']
PRIORITY_SOURCE = {'Скважина': 'well', 'ГСП': 'group', 'Приоритет итог': 'priority', 'Приоритет (расчёт)': 'priority_calc',
                   'Приоритет вручную': 'priority_manual', 'Песок в ревизиях КРУ': 'sand', 'Последний КР': 'last_year',
                   'Тип последнего КР': 'last_type', 'В плане КР': 'planned', 'Причина': 'reason'}
EXCEL = ('.xlsx', '.xlsm', '.xls')


def looks_like(tables: dict[str, pd.DataFrame]) -> bool:
    """Книга КРС: есть листы «Ремонты» и «Приоритет» с колонками «Скважина»."""
    def head(sheet: str) -> set[str]:
        raw = tables.get(sheet)
        return set() if raw is None or raw.empty else {str(v).strip() for v in raw.iloc[0].tolist()}
    return 'Скважина' in head(SHEETS[WORKS]) and 'Скважина' in head(SHEETS[PRIORITY])


def well_id(value) -> str:
    text = str(value).strip()
    if text.lower() in ('', 'nan', 'none'):
        return ''
    try:
        number = float(text.replace(',', '.'))
        return str(int(number)) if number.is_integer() else text
    except ValueError:
        return text


def _text(value) -> str:
    return '' if value is None or pd.isna(value) else str(value).strip()


def read(name: str, content: bytes) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Таблицы КРС из книги и замечания. Нет листа «Ремонты» или «Приоритет» — ValueError с подсказкой."""
    if not str(name).lower().endswith(EXCEL):
        raise ValueError('нужна книга Excel КРС_для_Атласа.xlsx')
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
    missing = [SHEETS[k] for k in (WORKS, PRIORITY) if SHEETS[k] not in sheets or 'Скважина' not in sheets[SHEETS[k]].columns]
    if missing:
        raise ValueError('в книге нет листов с колонкой «Скважина»: ' + ', '.join(missing)
                         + '. Нужен файл КРС_для_Атласа.xlsx из «Работы с исходными данными»')
    warnings: list[str] = []
    src = sheets[SHEETS[WORKS]]
    extra = [c for c in src.columns if c not in ('Скважина', 'Год', 'Тип ремонта')]
    rows = []
    for _, r in src.iterrows():
        well = well_id(r['Скважина'])
        if not well:
            continue
        year = pd.to_numeric(r.get('Год'), errors='coerce')
        rows.append({'well': well, 'year': float(year) if pd.notna(year) else float('nan'), 'work_type': _text(r.get('Тип ремонта')),
                     'detail': '; '.join(f'{c}: {_text(r[c])}' for c in extra if _text(r[c]))})
    works = pd.DataFrame(rows, columns=WORKS_COLUMNS)
    skipped = len(src) - len(works)
    if skipped:
        warnings.append(f'Ремонты: пропущено строк без номера скважины: {skipped}')
    if works.year.isna().any():
        warnings.append(f'Ремонты: у {int(works.year.isna().sum())} строк нет года')
    prio = sheets[SHEETS[PRIORITY]].rename(columns=PRIORITY_SOURCE)
    prio = prio[[c for c in PRIORITY_COLUMNS if c in prio.columns]].copy()
    for col in PRIORITY_COLUMNS:
        if col not in prio:
            prio[col] = pd.NA
    prio['well'] = prio['well'].map(well_id)
    prio = prio[prio.well.ne('')]
    for col in ('priority', 'priority_calc', 'priority_manual', 'last_year', 'planned'):
        prio[col] = pd.to_numeric(prio[col], errors='coerce')
    for col in ('group', 'sand', 'last_type', 'reason'):
        prio[col] = prio[col].map(_text)
    parts = {WORKS: works, PRIORITY: prio[PRIORITY_COLUMNS].drop_duplicates('well', keep='last').reset_index(drop=True)}
    if SHEETS[PLAN] in sheets and 'Скважина' in sheets[SHEETS[PLAN]].columns:      # лист необязательный: появляется, если книгу собрали со справкой КР
        parts[PLAN] = read_plan(sheets[SHEETS[PLAN]])
    return parts, warnings


def read_plan(raw: pd.DataFrame) -> pd.DataFrame:
    """Лист «План КР»: одна строка на скважину и ремонт. Даты — настоящие даты, пусто — пропуск; «Да/Нет» остаются текстом."""
    plan = raw.rename(columns=PLAN_SOURCE)
    plan = plan[[c for c in PLAN_COLUMNS if c in plan.columns]].copy()
    for col in PLAN_COLUMNS:
        if col not in plan:
            plan[col] = pd.NA
    plan['well'] = plan['well'].map(well_id)
    plan = plan[plan.well.ne('')]
    plan['year'] = pd.to_numeric(plan['year'], errors='coerce')
    for col in ('start', 'end'):
        plan[col] = pd.to_datetime(plan[col], format='%d.%m.%Y', errors='coerce')
    for col in PLAN_COLUMNS:
        if col not in ('year', 'start', 'end', 'well'):
            plan[col] = plan[col].map(_text)
    return plan[PLAN_COLUMNS].reset_index(drop=True)


def merge(old: pd.DataFrame | None, new: pd.DataFrame, keep_old: bool = False) -> pd.DataFrame:
    """Скважины нового файла заменяют все прежние строки этих скважин; «оставить прежние» — добавляются только новые скважины."""
    if old is None or old.empty:
        return new.reset_index(drop=True)
    wells = set(new.well)
    if keep_old:
        return pd.concat([old, new[~new.well.isin(set(old.well))]], ignore_index=True)
    return pd.concat([old[~old.well.isin(wells)], new], ignore_index=True)


def summary(parts: dict[str, pd.DataFrame]) -> str:
    return '; '.join(f'{LABELS[k]}: строк {len(v)}, скважин {v.well.nunique()}' for k, v in parts.items())
