"""Программа ГДИ на сезон (Word-таблица «Программа 25-26»: этапы, причины, номера скважин по ГСП) → таблица проекта ``gdi_program``.

Одна строка на скважину в программе: ``well``, ``group`` (ГСП), ``season`` («2025-2026»), ``stage`` («I этап»), ``reason`` (причина как
в файле), ``reason_kind`` (``filter`` — после КР, замена фильтра; ``coil`` — после КР, промывка и СКО; ``krs_plan`` — в плане КР на
год, то есть ГДИ после ремонта в сезоне закачки; ``gap`` — ГДИ не проводились более N лет; ``other``), ``krs_injection`` (True для ``krs_plan``).
Программа — подсказка: исправляет и решает инженер. Группу файла сверяют с группами проекта (``reconcile``): при расхождении берётся
группа проекта и пишется замечание; одна скважина в двух ГСП файла — оставляется строка с группой проекта.
"""
from __future__ import annotations

import io
import re
import zipfile

import pandas as pd

from . import tabular

KIND = 'gdi_program'
COLUMNS = ['well', 'group', 'season', 'stage', 'reason', 'reason_kind', 'krs_injection']
REASONS = {'filter': 'после КР: замена фильтра', 'coil': 'после КР: промывка и СКО', 'krs_plan': 'КР в сезоне закачки (план КР)',
           'gap': 'ГДИ давно не проводились', 'other': 'другое'}
LINE = re.compile(r'^\s*(?:ГСП|GSP)\s*[-–—\s]?\s*(\d+)\s*[:：]\s*(.*)$', re.I)
STAGE = re.compile(r'^\s*([IVX]+)\s*этап', re.I)
HEAD = ('Номера исследуемых скважин', 'Кол-во скважин')


def looks_like(tables: dict[str, pd.DataFrame]) -> bool:
    return any(HEAD[0] in {str(v).strip() for v in raw.iloc[0].tolist()} for raw in tables.values() if raw is not None and not raw.empty)


def season_from_name(name: str) -> str:
    """«Программа 25-26 для ГА.docx» → «2025-2026»; не найдено — пусто (вводится при импорте руками)."""
    m = re.search(r'(?<!\d)(\d{2}|\d{4})\s*[-–—]\s*(\d{2}|\d{4})(?!\d)', name)
    if not m:
        return ''
    a, b = (int(x) + 2000 if len(x) == 2 else int(x) for x in m.groups())
    return f'{a}-{b}' if 0 < b - a <= 1 else ''


def reason_kind(text: str) -> str:
    t = text.lower()
    if 'план' in t and 'кап' in t:
        return 'krs_plan'
    if 'противопес' in t or 'фильтр' in t or re.search(r'(?<![а-яa-z])ппф(?![а-яa-z])|(?<![а-яa-z])п\.?\s?п\.?\s?ф\.?(?![а-яa-z])', t):
        return 'filter'          # «замена противопесочного фильтра», «замена фильтра», «замена ППФ»
    if re.search(r'колтюб|кислотн|промыв|(?<![а-яa-z])ско(?![а-яa-z])|обработк', t):
        return 'coil'
    if 'не проводил' in t or re.search(r'более\s*\d+\s*лет', t):
        return 'gap'
    return 'other'


def group_name(number: str) -> str:
    return f'ГСП-{int(number)}'


def well_ids(text: str) -> list[str]:
    return [p for p in (x.strip() for x in re.split(r'[,;\s]+', text)) if re.fullmatch(r'\d+[A-Za-zА-Яа-я]?', p)]


def read(name: str, content: bytes, season: str = '') -> tuple[pd.DataFrame, list[str]]:
    if not str(name).lower().endswith('.docx'):
        raise ValueError('нужен файл Word с таблицей программы ГДИ (.docx)')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            z.getinfo('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError('файл не похож на документ Word') from e
    _, tables = tabular.read_content(content, name)
    table = next((t for t in tables.values() if looks_like({'x': t})), None)
    if table is None:
        raise ValueError('в документе нет таблицы с колонкой «Номера исследуемых скважин»')
    season = season.strip() or season_from_name(name)
    rows: list[dict] = []
    warnings: list[str] = []
    for _, r in table.iloc[1:].iterrows():
        cells = [('' if pd.isna(v) else str(v)) for v in r.tolist()]
        m = STAGE.match(cells[0]) if cells else None
        if not m or len(cells) < 3:
            continue
        stage, reason, declared = f'{m.group(1).upper()} этап', '', cells[1].strip()
        got = 0
        for line in cells[2].splitlines():
            line = line.strip()
            if not line:
                continue
            mm = LINE.match(line)
            if not mm:
                reason = line
                continue
            for w in well_ids(mm.group(2)):
                rows.append({'well': w, 'group': group_name(mm.group(1)), 'season': season, 'stage': stage, 'reason': reason,
                             'reason_kind': reason_kind(reason), 'krs_injection': reason_kind(reason) == 'krs_plan'})
                got += 1
        if declared.isdigit() and int(declared) != got:
            warnings.append(f'{stage}: в файле указано скважин {declared}, в перечне найдено {got}')
    df = pd.DataFrame(rows, columns=COLUMNS)
    if not season:
        warnings.append('Сезон программы не определён по имени файла: укажите его при импорте (например, 2025-2026).')
    return df, warnings


def reconcile(df: pd.DataFrame, project_groups: dict[str, str]) -> tuple[pd.DataFrame, list[str]]:
    """Группа из данных проекта главнее группы файла; дубль скважины в двух ГСП файла разрешается по проекту. Решает инженер: только подсказка."""
    warnings: list[str] = []
    out = df.copy()
    for i, r in out.iterrows():
        pg = project_groups.get(r['well'])
        if pg and norm_group(pg) != norm_group(r['group']):
            warnings.append(f'Скважина {r["well"]}: в файле {r["group"]}, в проекте {pg} — взята группа проекта')
            out.at[i, 'group'] = pg
    many = out.groupby('well').group.nunique()
    for w in many[many > 1].index:
        names = sorted(set(out[out.well == w].group))
        if not project_groups.get(w):
            warnings.append(f'Скважина {w}: в файле разные группы ({", ".join(names)}), в проекте группы нет — проверьте вручную')
    dup = out.duplicated(['well', 'season', 'reason_kind'], keep='first')
    if dup.any():
        warnings.append('Повтор скважины внутри одного блока убран: ' + ', '.join(sorted(set(out[dup].well))))
        out = out[~dup]
    return out.reset_index(drop=True), warnings


def norm_group(value: str) -> str:
    m = re.search(r'(\d+)', str(value))
    return m.group(1) if m else str(value).strip().lower()


def merge(old: pd.DataFrame | None, new: pd.DataFrame, keep_old: bool = False) -> pd.DataFrame:
    """Новая программа заменяет прежнюю того же сезона; «оставить прежние» — добавляются только сезоны, которых ещё нет."""
    if old is None or old.empty:
        return new.reset_index(drop=True)
    seasons = set(new.season)
    if keep_old:
        return pd.concat([old, new[~new.season.isin(set(old.season))]], ignore_index=True)
    return pd.concat([old[~old.season.isin(seasons)], new], ignore_index=True)


def summary(df: pd.DataFrame) -> str:
    parts = [f'{REASONS[k]}: {n}' for k, n in df.reason_kind.value_counts().items()]
    return f'скважин {df.well.nunique()}, сезон {", ".join(sorted(set(df.season))) or "не указан"}; ' + '; '.join(parts)
