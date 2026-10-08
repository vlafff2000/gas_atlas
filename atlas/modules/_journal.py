"""Общее для «Исключенных точек» и «Истории фильтра»: журнал исключений 5.8 в виде таблицы.

Журнал — ``settings.excluded_points`` (формат 5.8, ``atlas.engine.core.exclusions.entry``); здесь только представление.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

import pandas as pd

from atlas.engine.core import exclusions as legacy
from atlas.engine.core.config import MODULES

from ..contract import Column

# Подписи полей записи журнала — как ``LABELS`` в ``app/ui/point_tools.py`` (тот файл импортирует Streamlit).
LABELS = {'well': 'Скважина', 'date': 'Дата', 'kind': 'Тип', 'horizon': 'Горизонт', 'method': 'Метод',
          'study': 'Исследование', 'q': 'Q', 'dp2': 'ΔP²', 'level': 'Уровень, м', 'pressure': 'Рпл привед.',
          'file': 'Файл', 'sheet': 'Лист', '_row': 'Строка', 'reason': 'Причина', 'excluded_utc': 'Исключено (UTC)',
          'metric': 'Показатель', 'module': 'Модуль', 'work_hours': 'Часы работы', 'gas_volume_m3': 'Объем газа, м³',
          'water_volume_m3': 'Объем воды, м³', 'water_rate': 'Расход воды, м³/сут', 'water_flag': 'Вода',
          'bottom_m': 'Низ / забой, м', 'top_m': 'Верх, м', 'tool_diameter_mm': 'Диаметр шаблона, мм',
          'fact': 'Фактическое давление', 'model': 'Модельное давление', 'scenario': 'Сценарий', 'object': 'Объект',
          'fond': 'Фонд', 'element': 'Элемент', 'diameter_mm': 'Наружный диаметр, мм',
          'inner_diameter_mm': 'Внутренний диаметр, мм', 'comment': 'Комментарий'}
METRICS = {'level': 'Уровень жидкости', 'pressure': 'Приведенное давление'}
SERVICE = ('id', 'module', 'metric', 'reason', 'excluded_utc', 'batch')
NUMERIC = ('q', 'dp2', 'level', 'pressure', '_row', 'work_hours', 'gas_volume_m3', 'water_volume_m3', 'water_rate',
           'bottom_m', 'top_m', 'tool_diameter_mm', 'fact', 'model', 'diameter_mm', 'inner_diameter_mm')


def module_label(module: Any) -> str:
    return MODULES.get(str(module), str(module))


def journal(excluded: Mapping[str, dict]) -> pd.DataFrame:
    """``exclusions.journal`` 5.8; новые исключения сверху."""
    d = legacy.journal({'excluded_points': dict(excluded)})
    if d.empty:
        return d
    if 'excluded_utc' in d:
        d = d.sort_values('excluded_utc', ascending=False, kind='stable')
    return d.reset_index(drop=True)


def table(d: pd.DataFrame) -> tuple[pd.DataFrame, list[Column]]:
    """Журнал для показа: модуль и показатель подписаны, служебный ``batch`` скрыт, ``id`` остаётся для действий."""
    out = d.copy()
    out['module_label'] = out['module'].map(module_label) if 'module' in out else ''
    metric = out['metric'] if 'metric' in out else pd.Series('', index=out.index)
    module = out['module'] if 'module' in out else pd.Series('', index=out.index)
    out['metric_label'] = [METRICS.get(m, '') if mod == 'response' else '' for m, mod in zip(metric, module)]
    columns = [Column('module_label', 'Модуль'), Column('metric_label', 'Показатель')]
    for key, label in LABELS.items():
        if key in SERVICE or key not in out or not out[key].notna().any():
            continue
        if key == 'date':
            out[key] = pd.to_datetime(out[key], errors='coerce')
            columns.append(Column(key, label, kind='date'))
        elif key in NUMERIC:
            out[key] = pd.to_numeric(out[key], errors='coerce')
            columns.append(Column(key, label, kind='number'))
        else:
            out[key] = [None if v is None or (isinstance(v, float) and v != v) else str(v) for v in out[key]]
            columns.append(Column(key, label))
    for key in ('reason', 'excluded_utc'):
        if key in out:
            columns.append(Column(key, LABELS[key], kind='date' if key == 'excluded_utc' else 'text'))
    return out, columns


def details_of(text: Any) -> dict[str, Any]:
    try:
        value = json.loads(text) if isinstance(text, str) else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def filter_records(history: pd.DataFrame) -> list[tuple[pd.Series, dict[str, Any]]]:
    """Записи журнала проекта с состоянием фильтра до и после (как отбирает «История фильтра» 5.8)."""
    out = []
    for _, row in history.iterrows():
        details = details_of(row['Подробности'])
        if 'before_exclusions' in details:
            out.append((row, details))
    return out
