"""Вид названий сезонов отбора на экране и в выгрузках: «2025-2026» (тире) или «2025/2026» (слэш).

Только отображение: внутри расчёта и в сохранённых проектах ключи сезонов не меняются. Подмена идёт по готовому
результату модуля: подписи графиков, легенды, подсказки, ячейки и заголовки таблиц."""
from __future__ import annotations

import dataclasses
import re
from typing import Any

import pandas as pd

FORMATS = {'dash': '-', 'slash': '/'}
DEFAULT = 'dash'
_SEASON = re.compile(r'(?<!\d)(\d{4})[-–/](\d{4})(?!\d)')


def format_of(settings: Any) -> str:
    value = (settings or {}).get('season_format')
    return value if value in FORMATS else DEFAULT


def text(value: str, fmt: str = DEFAULT) -> str:
    sep = FORMATS.get(fmt, '-')
    return _SEASON.sub(lambda m: f'{m.group(1)}{sep}{m.group(2)}' if int(m.group(2)) == int(m.group(1)) + 1 else m.group(0), value)


def relabel(value: Any, fmt: str = DEFAULT) -> Any:
    """Копия ``value`` (результат модуля, список, словарь, строка…) с названиями сезонов в выбранном виде."""
    if isinstance(value, str):
        return text(value, fmt)
    if isinstance(value, pd.DataFrame):
        frame = value.copy()
        frame.columns = [text(c, fmt) if isinstance(c, str) else c for c in frame.columns]
        for name in frame.columns:
            if not pd.api.types.is_numeric_dtype(frame[name]) and not pd.api.types.is_datetime64_any_dtype(frame[name]):
                frame[name] = frame[name].map(lambda v: text(v, fmt) if isinstance(v, str) else v)
        return frame
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.replace(value, **{f.name: relabel(getattr(value, f.name), fmt)
                                             for f in dataclasses.fields(value) if f.init})
    if isinstance(value, list):
        return [relabel(v, fmt) for v in value]
    if isinstance(value, tuple):
        return tuple(relabel(v, fmt) for v in value)
    if isinstance(value, dict):
        return {relabel(k, fmt): relabel(v, fmt) for k, v in value.items()}
    return value
