"""Исправленная БД вкладки: данные так, как их видит расчёт (исключённые точки убраны), в структуре книги импорта.

Листы — по наборам данных вкладки (один лист — один набор), колонки — с теми же заголовками, что понимает импорт
(``atlas.engine.core.loader.column_map``), служебные колонки Атласа не пишутся. Исключённая строка не попадает в файл;
исключённый показатель реагирования (уровень или давление) остаётся пустой ячейкой, как пропуск в расчёте.
Значения не меняются: переработка, отбраковка и исключения уже отражены в журнале проекта.
"""
from __future__ import annotations

from io import BytesIO
from typing import Mapping

import pandas as pd

from atlas.engine.core import exclusions
from .domain import DatasetKind

# Служебные колонки Атласа: выводятся из данных или относятся к файлу-источнику, в книгу импорта не входят.
INTERNAL = {'_point_id', '_excluded', '_row', '_model_row', '_reject', '_occurrence', 'file', 'sheet',
            'season', 'year', 'group', 'subgroup', 'period'}
# Заголовки полей — те же, что понимает импорт (синонимы из loader.ALIASES). Прочие колонки пишутся как есть.
HEADERS = {'well': 'Скважина', 'date': 'Дата', 'q': 'Q', 'kind': 'Тип', 'p_res': 'Рпл', 'p_bh': 'Рзаб',
           'dp2': 'Рпл2рз2', 'horizon': 'Горизонт', 'level': 'Уровень', 'pressure': 'Рпл привед',
           'method': 'Метод', 'study': 'Исследование', 'a_db': 'a', 'b_db': 'b', 'hours': 'Часы работы'}
SHEET_LIMIT = 31


def dataset_frame(raw: pd.DataFrame, kind: DatasetKind, excluded: Mapping[str, dict]) -> pd.DataFrame:
    """Таблица набора с исключениями, как в расчёте, без служебных колонок, с заголовками импорта."""
    if kind is DatasetKind.RESPONSE:
        d = exclusions.apply({kind.value: raw}, {'excluded_points': dict(excluded)})[kind.value]
    else:
        d = raw.loc[~raw['_point_id'].isin(list(excluded))]
    d = d.drop(columns=[c for c in d if c in INTERNAL or c.startswith('_')])
    return d.rename(columns={k: v for k, v in HEADERS.items() if k in d}).reset_index(drop=True)


def workbook(frames: Mapping[DatasetKind, pd.DataFrame]) -> bytes:
    """Книга: по листу на набор; пустой набор записывается заголовками, чтобы структура не терялась."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as xl:
        for kind, frame in frames.items():
            frame.to_excel(xl, sheet_name=kind.label[:SHEET_LIMIT], index=False)
    return buffer.getvalue()


def build(raw: Mapping[DatasetKind, pd.DataFrame], excluded: Mapping[str, dict], kinds) -> bytes:
    """Исправленная БД для наборов ``kinds`` (те, что есть в проекте)."""
    frames = {k: dataset_frame(raw[k], k, excluded) for k in kinds if k in raw}
    return workbook(frames)
