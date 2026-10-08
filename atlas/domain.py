"""Доменная модель ПХГ: единый словарь для всех модулей.

Канонические имена колонок совпадают с теми, что пишет импорт 5.8 (``app/core/loader.py``),
поэтому проекты 5.8 читаются без преобразований.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WellFund(str, Enum):
    PRODUCTION = 'production'        # эксплуатационная
    OBSERVATION = 'observation'      # наблюдательная
    CONTROL = 'control'              # контрольная

    @property
    def label(self) -> str:
        return {'production': 'Эксплуатационная', 'observation': 'Наблюдательная',
                'control': 'Контрольная'}[self.value]


class DatasetKind(str, Enum):
    """Вид набора данных. Значение — имя таблицы в проекте (parquet)."""
    PRODUCTION = 'production'            # отбор и закачка, суточные
    GDI = 'gdi'                          # газодинамические исследования
    RESPONSE = 'response'                # реагирование контрольных горизонтов
    OBJECT_PRESSURE = 'object_pressure'
    OPERATIONS = 'operations'            # суточная эксплуатация
    WATER = 'water'
    WATER_FACTOR = 'water_factor'        # вынос воды и водный фактор по объекту: одна таблица по датам, без скважин
    BOTTOM = 'bottom'                    # замеры забоя
    CONSTRUCTION = 'construction'
    PRESSURE_MATCH = 'pressure_match'    # кроссплот давлений: факт / модель
    PLAN = 'plan'                        # плановые объёмы отбора и закачки по группам и месяцам
    GGH = 'ggh'                          # газогидрохимические исследования: состав водорастворённого газа

    @property
    def label(self) -> str:
        return LABELS[self]


LABELS = {
    DatasetKind.PRODUCTION: 'Отбор и закачка',
    DatasetKind.GDI: 'ГДИ',
    DatasetKind.RESPONSE: 'Реагирование горизонтов',
    DatasetKind.OBJECT_PRESSURE: 'Давление объекта',
    DatasetKind.OPERATIONS: 'Суточная эксплуатация',
    DatasetKind.WATER: 'Контроль воды',
    DatasetKind.WATER_FACTOR: 'Вынос воды по объекту',
    DatasetKind.BOTTOM: 'Замеры забоя',
    DatasetKind.CONSTRUCTION: 'Конструкция скважин',
    DatasetKind.PRESSURE_MATCH: 'Кроссплот давлений',
    DatasetKind.PLAN: 'План по группам',
    DatasetKind.GGH: 'ГГХ',
}

# Обязательные колонки каждого набора (как после импорта 5.8).
REQUIRED_COLUMNS: dict[DatasetKind, tuple[str, ...]] = {
    DatasetKind.PRODUCTION: ('well', 'date', 'q', 'kind'),
    DatasetKind.GDI: ('well', 'date', 'q', 'dp2'),
    DatasetKind.RESPONSE: ('well', 'date', 'horizon'),
    DatasetKind.OBJECT_PRESSURE: ('date',),
    DatasetKind.OPERATIONS: ('well', 'date'),
    DatasetKind.WATER: ('well', 'date'),
    DatasetKind.WATER_FACTOR: ('date', 'gas_in_place'),
    DatasetKind.BOTTOM: ('well', 'date'),
    DatasetKind.CONSTRUCTION: ('well',),
    DatasetKind.PRESSURE_MATCH: ('well', 'date'),
    DatasetKind.PLAN: ('group', 'date', 'plan_volume', 'kind'),
    DatasetKind.GGH: ('well', 'date'),
}

# Подписи колонок для таблиц и подсказок.
COLUMN_LABELS = {
    'well': 'Скважина', 'date': 'Дата', 'q': 'Q', 'dp2': 'ΔP²', 'p_res': 'Рпл', 'p_bh': 'Рзаб',
    'horizon': 'Горизонт', 'group': 'Группа', 'subgroup': 'Подгруппа', 'season': 'Сезон',
    'method': 'Метод', 'study': 'Исследование', 'level': 'Уровень', 'pressure': 'Рпл привед.',
}

UNITS = {
    'q_gdi': 'тыс. м³/сут',
    'pressure': 'кгс/см²',
    'dp2': 'кгс²/см⁴',
}


@dataclass(frozen=True)
class Well:
    id: str
    fund: WellFund | None = None
    group: str = ''
    subgroup: str = ''
    horizon: str = ''
