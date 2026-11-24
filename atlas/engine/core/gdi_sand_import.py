"""Специальные ГДИ на вынос песка: итоговая таблица «Максимальные депрессии (по затрубу), при которых отсутствует вынос твёрдых частиц»
(колонки «№ скв», «dP(затр), кгс/см²», «Q, тыс. м³/сут», «КРУ, %») из Word, Excel или CSV → таблица проекта ``gdi_sand``.

Одна строка на скважину и исследование: ``well``, ``date`` (дата исследования; пусто, если не указана), ``dp_annulus`` (кгс/см²),
``q`` (тыс. м³/сут), ``kru`` (КРУ, %), ``note``, ``source`` («импорт» или «вручную»). Пропуск остаётся пропуском, значения не пересчитываются.
Это подсказка: последнее слово за инженером, строки правятся вручную (общая таблица данных проекта).
"""
from __future__ import annotations

import io
import re
import zipfile

import pandas as pd

from . import tabular

KIND = 'gdi_sand'
COLUMNS = ['well', 'date', 'dp_annulus', 'q', 'kru', 'note', 'source']


def _norm(value) -> str:
    return re.sub(r'\s+', '', str('' if pd.isna(value) else value)).lower().replace('δ', 'd').replace('∆', 'd')


def _field(value) -> str | None:
    t = _norm(value)
    if re.match(r'^(№|n|no)?скв', t) or t in ('скважина', 'well'):
        return 'well'
    if ('затр' in t or 'annul' in t) and re.match(r'^(dp|d[рp]|депресс)', t):
        return 'dp_annulus'
    if re.match(r'^q[,(]?', t) and ('тыс' in t or 'м3' in t or 'м³' in t or t == 'q'):
        return 'q'
    if t.startswith('кру') or t.startswith('kru'):
        return 'kru'
    if t.startswith('примеч'):
        return 'note'
    if t.startswith('дата'):
        return 'date'
    return None


def _header(raw: pd.DataFrame) -> dict[str, int] | None:
    if raw is None or raw.empty:
        return None
    found: dict[str, int] = {}
    for j, v in enumerate(raw.iloc[0].tolist()):
        f = _field(v)
        if f and f not in found:
            found[f] = j
    return found if {'well', 'dp_annulus', 'q'} <= set(found) else None


def looks_like(tables: dict[str, pd.DataFrame]) -> bool:
    return any(_header(raw) for raw in tables.values())


def _num(value) -> float:
    t = str('' if pd.isna(value) else value).strip().replace('\xa0', '').replace(' ', '').replace(',', '.').rstrip('%')
    try:
        return float(t)
    except ValueError:
        return float('nan')


def _well(value) -> str:
    t = str('' if pd.isna(value) else value).strip()
    if re.fullmatch(r'\d+\.0', t):
        t = t[:-2]
    return t if re.fullmatch(r'\d+[A-Za-zА-Яа-я]?', t) else ''


def parse_date(text: str) -> pd.Timestamp:
    """«03.11.2025», «2025-11-03»; из имени файла — первая дата подряд; не найдено — NaT."""
    m = re.search(r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})', str(text))
    if m:
        return pd.to_datetime(f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}', errors='coerce')
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', str(text))
    return pd.to_datetime(m.group(0), errors='coerce') if m else pd.NaT


def read(name: str, content: bytes, date: str = '') -> tuple[pd.DataFrame, list[str]]:
    if str(name).lower().endswith('.docx'):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                z.getinfo('word/document.xml')
        except (zipfile.BadZipFile, KeyError) as e:
            raise ValueError('файл не похож на документ Word') from e
    _, tables = tabular.read_content(content, name)
    warnings: list[str] = []
    rows: list[dict] = []
    stamp = parse_date(date) if str(date).strip() else parse_date(name)
    seen = False
    for raw in tables.values():
        head = _header(raw)
        if not head:
            continue
        seen = True
        for i in range(1, len(raw)):
            r = raw.iloc[i].tolist()
            get = lambda f: r[head[f]] if f in head and head[f] < len(r) else ''
            well = _well(get('well'))
            if not well:
                continue
            row_date = parse_date(get('date')) if 'date' in head else pd.NaT
            rows.append({'well': well, 'date': row_date if pd.notna(row_date) else stamp, 'dp_annulus': _num(get('dp_annulus')),
                         'q': _num(get('q')), 'kru': _num(get('kru')) if 'kru' in head else float('nan'),
                         'note': str(get('note')).strip() if 'note' in head and pd.notna(get('note')) else '', 'source': 'импорт'})
    if not seen:
        raise ValueError('нет таблицы с колонками «№ скв», «dP(затр)», «Q»')
    df = pd.DataFrame(rows, columns=COLUMNS)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    if df.date.isna().any():
        warnings.append('Дата исследования не определена по файлу: укажите её при импорте (например, 03.11.2025).')
    bad = df[df.dp_annulus.isna() | df.q.isna()].well.tolist()
    if bad:
        warnings.append('Нет числа в dP или Q (строка сохранена как есть): ' + ', '.join(bad))
    dup = df.duplicated(['well', 'date'], keep='first')
    if dup.any():
        warnings.append('Повтор скважины с той же датой убран: ' + ', '.join(sorted(set(df[dup].well))))
        df = df[~dup]
    return df.reset_index(drop=True), warnings


def merge(old: pd.DataFrame | None, new: pd.DataFrame, keep_old: bool = False) -> pd.DataFrame:
    """Новый файл заменяет исследования тех же скважины и даты (правки вручную по другим строкам остаются); «оставить прежние» — только новые пары."""
    if old is None or old.empty:
        return new.reset_index(drop=True)
    key = lambda d: set(zip(d.well, d.date.astype(str)))
    pairs = lambda d: list(zip(d.well, d.date.astype(str)))
    if keep_old:
        have = key(old)
        keep = new[[p not in have for p in pairs(new)]]
        return pd.concat([old, keep], ignore_index=True)
    fresh = key(new)
    stay = old[[p not in fresh for p in pairs(old)]]
    return pd.concat([stay, new], ignore_index=True)


def summary(df: pd.DataFrame) -> str:
    return f'скважин {df.well.nunique()}, строк {len(df)}, dP затруб от {df.dp_annulus.min():g} до {df.dp_annulus.max():g} кгс/см²'
