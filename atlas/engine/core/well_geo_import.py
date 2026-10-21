"""Положение и перфорация скважин → таблица ``well_geo`` (одна строка на скважину).

Столбцы: ``well`` (номер текстом), ``x``, ``y`` (координаты устья, tNavigator), ``altitude`` (альтитуда устья, м),
``perf_top``, ``perf_bottom`` (верх и низ перфорации, абсолютные отметки, м: как в файле «Глубины перфораций»).
Пропуск — NaN: «нет данных» не заменяется нулём.

Принимаются:
- текст или таблица «скважина X Y» (табуляция, пробелы, «;», запятая; имя вида ``W500``, ``Скв_500``) и траектории ``WELLTRACK``;
- таблица Excel с заголовками (Скважина, X, Y, Альтитуда, Верх перфорации, Низ перфорации — любой набор);
- книга «Глубины_перфораций.xlsx» с листами «перфорации» (столбцы 1, 5, 6) и «альтитуды» (столбцы 1, 2).
Разбор XY повторяет ``gsp_maps/wellmap.py`` (all_scripts), чтобы Карты ГСП и Атлас читали файл одинаково.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ['well', 'x', 'y', 'altitude', 'perf_top', 'perf_bottom']
VALUES = COLUMNS[1:]
EXCEL = ('.xlsx', '.xlsm', '.xls')
# заголовки таблицы: подстрока (в нижнем регистре, без «ё») → столбец; проверяются по порядку
HEADERS = (('perf_top', ('верх перф', 'кровля', 'perf_top', 'perf top')),
           ('perf_bottom', ('низ перф', 'подошва', 'perf_bottom', 'perf bottom')),
           ('altitude', ('альтитуд', 'altitude', 'отметка устья')),
           ('x', ('x', 'х', 'восток', 'easting')),
           ('y', ('y', 'север', 'northing')),
           ('well', ('скважин', 'well', 'скв', '№', 'номер')))
_NUM = re.compile(r'^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$')


def _float(token) -> float | None:
    text = str(token).strip().strip('\'"')
    return float(text.replace(',', '.')) if _NUM.match(text) else None


def well_id(name) -> str | None:
    """Номер скважины из имени: ``500``, ``W500``, ``Скв_500`` → ``'500'``; ``500.0`` → ``'500'``."""
    text = str(name).strip().strip('\'"')
    number = _float(text)
    if number is not None:
        return str(int(number)) if float(number).is_integer() else None
    found = re.match(r'^\D*(\d+)\D*$', text) or re.search(r'(\d+)', text)
    return str(int(found.group(1))) if found else None


def parse_xy_lines(lines: list[str]) -> tuple[dict[str, tuple[float, float]], list[str]]:
    """Таблица «скважина X Y …» или WELLTRACK (первая точка — устье). Возвращает (координаты, предупреждения)."""
    xy: dict[str, tuple[float, float]] = {}
    warn: list[str] = []
    if re.search(r'\bWELLTRACK\b', '\n'.join(lines), re.I):
        name = None
        for line in lines:
            found = re.match(r'\s*WELLTRACK\s+(\S+)', line, re.I)
            if found:
                name = found.group(1)
                continue
            if name is not None:
                nums = [_float(t) for t in line.replace('/', ' ').split()]
                if len(nums) >= 2 and nums[0] is not None and nums[1] is not None:
                    wid = well_id(name)
                    if wid is not None:
                        xy[wid] = (nums[0], nums[1])
                    name = None
        if xy:
            return xy, warn
    skipped = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(('#', '--', '//')):
            continue
        if '\t' in line:
            tokens = line.split('\t')
        elif ';' in line:
            tokens = line.split(';')
        elif line.count(',') >= 2 and not re.search(r'\d,\d+\s', line):
            tokens = line.split(',')
        else:
            tokens = line.split()
        tokens = [t.strip() for t in tokens if t.strip() != '']
        if len(tokens) < 3:
            skipped += 1 if tokens and _float(tokens[0]) is not None else 0
            continue
        values = [_float(t) for t in tokens]
        if all(v is None for v in values):      # заголовок таблицы
            continue
        wid = well_id(tokens[0]) if values[0] is None or float(values[0]).is_integer() else None
        nums = [v for v in values[1:] if v is not None]
        if wid is None or len(nums) < 2:
            skipped += 1
            continue
        xy[wid] = (nums[0], nums[1])
    if skipped:
        warn.append(f'Координаты: не разобрано строк — {skipped}')
    return xy, warn


def _decode(content: bytes) -> list[str]:
    for encoding in ('utf-8-sig', 'cp1251'):
        try:
            return content.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return []


def _key(value) -> str:
    return str(value).strip().lower().replace('ё', 'е')


def _column(headers: list[str], kind: str, taken: set) -> int | None:
    parts = dict(HEADERS)[kind]
    for i, head in enumerate(headers):
        if i in taken:
            continue
        if kind in ('x', 'y'):
            if head in parts or any(head.startswith(p + ' ') or head.endswith(' ' + p) for p in parts):
                return i
        elif any(p in head for p in parts):
            return i
    return None


def _table(raw: pd.DataFrame) -> pd.DataFrame | None:
    """Таблица с заголовками: ищем строку заголовков среди первых 10 строк (скважина + хотя бы одно значение)."""
    for i in range(min(10, len(raw))):
        headers = [_key(v) for v in raw.iloc[i].tolist()]
        taken: set = set()
        found = {}
        for kind in ('perf_top', 'perf_bottom', 'altitude', 'x', 'y', 'well'):
            col = _column(headers, kind, taken)
            if col is not None:
                found[kind] = col
                taken.add(col)
        if 'well' in found and len(found) >= 2 and ('x' in found) == ('y' in found):
            body = raw.iloc[i + 1:]
            out = pd.DataFrame({'well': body.iloc[:, found['well']].map(well_id)})
            for kind in VALUES:
                out[kind] = pd.to_numeric(body.iloc[:, found[kind]].astype(str).str.replace(',', '.', regex=False)
                                          .str.strip(), errors='coerce') if kind in found else np.nan
            return out.dropna(subset=['well'])
    return None


def _legacy_depths(book: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    """«Глубины_перфораций.xlsx» Карт ГСП: лист перфораций (скважина, … , верх, низ в столбцах 5 и 6) и лист альтитуд."""
    perf = next((df for name, df in book.items() if 'перфор' in name.lower()), None)
    alt = next((df for name, df in book.items() if 'альтитуд' in name.lower()), None)
    if perf is None and alt is None:
        return None
    rows: dict[str, dict] = {}
    if perf is not None:
        for r in perf.itertuples(index=False):
            wid = well_id(r[0]) if len(r) > 5 else None
            top, bottom = (_float(r[4]), _float(r[5])) if len(r) > 5 else (None, None)
            if wid and top and bottom:
                rows.setdefault(wid, {}).update(perf_top=top, perf_bottom=bottom)
    if alt is not None:
        for r in alt.itertuples(index=False):
            wid = well_id(r[0]) if len(r) > 1 else None
            z = _float(r[1]) if len(r) > 1 else None
            if wid and z is not None:
                rows.setdefault(wid, {})['altitude'] = z
    return pd.DataFrame([{'well': w, **v} for w, v in rows.items()], columns=COLUMNS)


def looks_like(tables: dict[str, pd.DataFrame]) -> bool:
    """Книга с положением скважин, перфорацией или альтитудами (по названиям листов и заголовкам). Для общего импорта."""
    if any(('перфор' in n.lower() or 'альтитуд' in n.lower()) for n in tables):
        return True
    for raw in tables.values():
        if raw is None or raw.empty:
            continue
        headers = [_key(v) for v in raw.iloc[0].tolist()]
        has = {kind: _column(headers, kind, set()) is not None for kind in ('well', 'x', 'y', 'altitude', 'perf_top', 'perf_bottom')}
        if has['well'] and not any(h in ('дата', 'date') for h in headers) and (
                (has['x'] and has['y']) or has['altitude'] or (has['perf_top'] and has['perf_bottom'])):
            return True
    return False


def build(name: str, content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Таблица ``well_geo`` из файла и предупреждения. Пустая таблица — файл не распознан."""
    warn: list[str] = []
    suffix = Path(name).suffix.lower()
    if suffix in EXCEL:
        book = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
        legacy = _legacy_depths(book)
        if legacy is not None and not legacy.empty:
            return legacy.sort_values('well', key=lambda s: s.astype(int)).reset_index(drop=True), warn
        frames = [t for t in (_table(raw) for raw in book.values()) if t is not None and len(t)]
        if frames:
            out = pd.concat(frames, ignore_index=True)
        else:                                            # таблица без заголовков: «скважина X Y»
            lines = ['\t'.join('' if v != v else str(v) for v in row) for raw in book.values()
                     for row in raw.itertuples(index=False)]
            xy, warn = parse_xy_lines(lines)
            out = pd.DataFrame([{'well': w, 'x': a, 'y': b} for w, (a, b) in xy.items()], columns=COLUMNS)
    else:
        lines = _decode(content)
        table = _table(pd.DataFrame([re.split(r'[\t;]', ln) for ln in lines])) if lines and re.search(r'[\t;]', lines[0]) else None
        if table is not None and len(table):
            out = table
        else:
            xy, warn = parse_xy_lines(lines)
            out = pd.DataFrame([{'well': w, 'x': a, 'y': b} for w, (a, b) in xy.items()], columns=COLUMNS)
    for col in COLUMNS:
        if col not in out:
            out[col] = np.nan
    out = out[COLUMNS].drop_duplicates('well', keep='last')
    if not out.empty:
        out = out.sort_values('well', key=lambda s: s.astype(int)).reset_index(drop=True)
    return out, warn


def merge(old: pd.DataFrame | None, new: pd.DataFrame, keep_old: bool = False) -> pd.DataFrame:
    """Объединение по скважине. Пустое значение нового файла не стирает прежнее; при ``keep_old`` прежнее значение
    сильнее нового (новое только заполняет пропуски)."""
    if old is None or old.empty:
        return new.reset_index(drop=True)
    top, bottom = (old, new) if keep_old else (new, old)
    merged = top.set_index('well')[VALUES].combine_first(bottom.set_index('well')[VALUES])
    out = merged.reset_index()[COLUMNS]
    return out.sort_values('well', key=lambda s: s.astype(int)).reset_index(drop=True)
