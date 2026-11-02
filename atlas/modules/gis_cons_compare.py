"""Сравнение конструкций проекта с другим файлом конструкций: что не сходится по скважине, дате и элементу. Подсказка, не приговор:
сводит базы инженер в «Работе с исходными данными» (модуль «Сведение баз конструкций»)."""
from __future__ import annotations

import pandas as pd

COLUMNS = ['Скважина', 'Дата', 'Элемент', 'Расхождение', 'В проекте: верх', 'В проекте: низ', 'В проекте: диаметр',
           'В файле: верх', 'В файле: низ', 'В файле: диаметр']


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df[['well', 'date', 'element', 'top_m', 'bottom_m'] + (['diameter_mm'] if 'diameter_mm' in df else [])].copy()
    if 'diameter_mm' not in out:
        out['diameter_mm'] = float('nan')
    out['well'] = out['well'].astype(str).str.strip()
    out['date'] = pd.to_datetime(out['date'], errors='coerce').dt.normalize()
    out['element'] = out['element'].astype(str).str.strip()
    out['n'] = out.sort_values(['top_m', 'bottom_m']).groupby(['well', 'date', 'element']).cumcount().reindex(out.index)
    return out.dropna(subset=['date'])


def _close(a, b, tol: float) -> bool:
    return (pd.isna(a) and pd.isna(b)) or (not pd.isna(a) and not pd.isna(b) and abs(a - b) <= tol)


def compare(project: pd.DataFrame, other: pd.DataFrame, tol: float = 0.5, wells: list[str] | None = None) -> pd.DataFrame:
    a, b = _prepare(project), _prepare(other)
    if wells:
        a, b = a[a['well'].isin(wells)], b[b['well'].isin(wells)]
    m = a.merge(b, on=['well', 'date', 'element', 'n'], how='outer', suffixes=('_a', '_b'), indicator=True)
    rows = []
    for _, r in m.sort_values(['well', 'date', 'element', 'n']).iterrows():
        if r['_merge'] == 'left_only':
            kind = 'только в проекте'
        elif r['_merge'] == 'right_only':
            kind = 'только в файле'
        else:
            deep = not (_close(r['top_m_a'], r['top_m_b'], tol) and _close(r['bottom_m_a'], r['bottom_m_b'], tol))
            diam = not (pd.isna(r['diameter_mm_a']) or pd.isna(r['diameter_mm_b'])) and r['diameter_mm_a'] != r['diameter_mm_b']
            if not (deep or diam):
                continue
            kind = 'глубины различаются' if deep else 'диаметр различается'
        rows.append([r['well'], r['date'].strftime('%d.%m.%Y'), r['element'], kind, r['top_m_a'], r['bottom_m_a'], r['diameter_mm_a'],
                     r['top_m_b'], r['bottom_m_b'], r['diameter_mm_b']])
    return pd.DataFrame(rows, columns=COLUMNS)
