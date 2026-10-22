"""Замеры выноса воды по скважинам за месяц (старый формат Карт ГСП) → таблица ``water``, одна строка на скважину и месяц.

Лист: строка на скважину. Первый столбец — номер, второй — водный фактор («1,2/0,5», «1,2», «нет воды»; «песок»,
«ремонт», «не идет» — нет данных), третий — газ, четвёртый (если есть) — расход воды, л/ч. Или вариант «литров за час …
ВФ» (ВФ в последнем столбце). Месяц и год — из имени файла или из первых строк листа.
Разбор повторяет ``gsp_maps/inputs.py`` (all_scripts), чтобы Карты и Атлас читали файл одинаково. Пропуск остаётся
пропуском: песок и ремонт не считаются нулём.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

import numpy as np
import pandas as pd

from . import tabular

COLUMNS = ['well', 'date', 'water_rate', 'water_factor_l', 'water_flag', 'comment']
MONTH_STEMS = (('январ', 1), ('феврал', 2), ('март', 3), ('апрел', 4), ('май', 5), ('мая', 5), ('июн', 6), ('июл', 7),
               ('август', 8), ('сентябр', 9), ('октябр', 10), ('ноябр', 11), ('декабр', 12))
NO_DATA = ('песок', 'ремонт', 'не идет')


def _num(text) -> float | None:
    try:
        return float(str(text).strip().replace(',', '.').replace(' ', ''))
    except ValueError:
        return None


def _leading(text) -> float | None:
    found = re.match(r'\s*(-?\d+(?:[.,]\d+)?)', str(text))
    return float(found.group(1).replace(',', '.')) if found else None


def _present(vals: list, i: int) -> bool:
    return len(vals) > i and vals[i] is not None and not (isinstance(vals[i], float) and np.isnan(vals[i]))


def well_number(value) -> str | None:
    """Номер скважины из ячейки: 500, 500.0, «500»; текст и пустые ячейки — None."""
    number = _num(value)
    return str(int(number)) if number is not None and number > 0 and float(number).is_integer() else None


def parse_row(vals: list, has_flow: bool) -> tuple[float | None, float | None, str]:
    """Строка старого формата: (водный фактор л/1000 м³, расход воды л/ч, примечание). None — нет данных."""
    factor: float | None = 0.0
    flow: float | None = 0.0
    gas = 0.0
    note = ''
    if _present(vals, 1):
        text = str(vals[1]).strip().lower()
        if 'нет воды' in text or text in ('', 'nan'):
            factor, flow = 0.0, 0.0
        elif any(word in text for word in NO_DATA):
            note = str(vals[1]).strip()
            factor, flow = None, None
        elif '1000м³/' in text or '1000м3/' in text:
            found = re.search(r'/(\d+[.,]?\d*)\s*л', text)
            factor = (_num(found.group(1)) or 0.0) if found else factor
        elif '/' in text:
            factor = _num(text.split('/')[0]) or 0.0
        else:
            factor = _num(text) or 0.0
    if _present(vals, 2):
        gas = _num(vals[2]) or 0.0
    if has_flow and _present(vals, 3):
        text = str(vals[3]).strip()
        if text and text.lower() not in ('nan', 'песок в ремонт', 'не идет'):
            flow = _num(text) or 0.0
    elif not has_flow and factor and factor > 0 and gas > 0:
        flow = round(gas * factor / 1000, 1)
    return factor, flow, note


def month_year(name: str, head: list[str]) -> tuple[int, int] | None:
    """Месяц и год: из имени файла («ноябрь 2022», «2022_11»), затем из заголовков листа."""
    numeric = re.search(r'(20\d{2})[_.\- ](\d{1,2})(?!\d)', name)
    if numeric and 1 <= int(numeric.group(2)) <= 12:
        return int(numeric.group(2)), int(numeric.group(1))
    for text in [name] + head:
        year = re.search(r'(20\d{2})', text)
        for word in re.findall(r'[а-яё]+', text.lower()):
            for stem, month in MONTH_STEMS:
                if year and word.startswith(stem):
                    return month, int(year.group(1))
    return None


def _factor_cell(value) -> bool:
    """Ячейка водного фактора: число, «1,2/0,5», «нет воды», «песок»… Даты сюда не относятся (это другой формат)."""
    if isinstance(value, dt.date) or value is None or (isinstance(value, float) and np.isnan(value)):
        return False
    text = str(value).strip().lower()
    return bool(text) and text != 'nan' and not re.match(r'^(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4})', text)


def _head(raw: pd.DataFrame) -> list[str]:
    return [' '.join(str(v) for v in raw.iloc[i].tolist() if isinstance(v, str)) for i in range(min(3, len(raw)))]


def looks_like(tables: dict[str, pd.DataFrame], name: str) -> bool:
    """Файл с замерами воды за месяц: месяц и год в имени (или в заголовке листа), слово «вод» в имени либо
    заголовок «ВФ», и хотя бы две строки «скважина, фактор» по листу."""
    for raw in tables.values():
        if raw is None or raw.empty or raw.shape[1] < 2:
            continue
        head = _head(raw)
        marks = ' '.join(head).lower()
        if 'вод' not in name.lower() and 'вф' not in marks.split():
            continue
        if month_year(name, head) is None:
            continue
        rows = sum(1 for r in raw.itertuples(index=False) if well_number(r[0]) and _factor_cell(r[1]))
        if rows >= 2:
            return True
    return False


def build(name: str, content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Таблица ``water`` из файла и предупреждения. Нет месяца или строк — ValueError."""
    _, tables = tabular.read_content(content, name, None)
    frames: list[dict[str, Any]] = []
    warn: list[str] = []
    month = None
    for sheet, raw in tables.items():
        if sheet == 'Инструкция' or raw is None or raw.empty:
            continue
        head = _head(raw)
        found = month_year(name, head)
        if found is None:
            warn.append(f'{sheet}: не найден месяц и год — лист пропущен')
            continue
        month = month or found
        marks = ' '.join(head).lower()
        litres = 'литров' in marks or ('вф' in marks.split() and raw.shape[1] > 5)
        has_flow = raw.shape[1] >= 4
        for row in raw.itertuples(index=False):
            vals = list(row)
            well = well_number(vals[0])
            if well is None:
                continue
            if litres:
                lh = _leading(vals[1]) if len(vals) > 1 else None
                gas = _num(vals[3]) if len(vals) > 3 else None
                vf = _num(vals[-1]) if len(vals) > 5 else None
                if vf is None and lh is not None and gas:
                    vf = lh / gas
                factor, flow, note = (vf * 1000 if vf is not None else 0.0), (lh or 0.0), ''
            else:
                factor, flow, note = parse_row(vals, has_flow)
            if factor is None and not note:
                continue
            frames.append({'well': well, 'date': pd.Timestamp(found[1], found[0], 1), 'water_rate': flow,
                           'water_factor_l': factor, 'water_flag': 'Да' if factor and factor > 0 else 'Нет' if factor == 0 else 'Неизвестно',
                           'comment': note})
    if month is None or not frames:
        raise ValueError('В файле нет строк «скважина, водный фактор» с месяцем и годом')
    out = pd.DataFrame(frames, columns=COLUMNS).drop_duplicates(['well', 'date'], keep='last')
    return out.sort_values(['well', 'date'], key=lambda s: s.astype(int) if s.name == 'well' else s).reset_index(drop=True), warn
