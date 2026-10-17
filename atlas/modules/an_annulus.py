"""Авторский надзор, табл. 11.3: межколонные давления (МКД) и расход из межколонного пространства (МКП).

Вход — строки «База межколонок» (формат «Сбора данных по межколонным давлениям» из «Базы ПХГ»): скважина (``номер_скважины``), расход газа из МКП,
м³/сут (``расход_газа_МК_сут``), давление МКД, кгс/см² (``давление_МК``). Выбор сезонов или дат делает вызывающий код;
здесь — только агрегирование и классификация.

Правила, как в отчёте: в таблицу попадают скважины с расходом или давлением больше нуля; по каждой берутся максимумы
расхода и давления за выбранный период (как в скрипте «Анализ межколонных давлений»). Группы по давлению: нулевое
давление при расходе — «близкое к нулю»; до 28 кгс/см² включительно; свыше 28. Группы по расходу из МКП: до 10,
от 10 до 90 включительно, свыше 90 м³/сут.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

P_LIMIT = 28.0      # кгс/см²: граница групп 2 и 3 (РБ-2023, как в отчёте)
Q_SMALL = 10.0      # м³/сут: граница малого и среднего расхода из МКП
Q_LARGE = 90.0      # м³/сут: граница среднего и большого расхода из МКП

# Имена колонок набора «Межколонные давления» в Атласе (после импорта); в базе — «номер_скважины», «расход_газа_МК_сут», «давление_МК».
WELL, Q, P = 'well', 'q', 'p'
COLUMNS = ('№ скв.', 'Qм/к, м³/сут', 'Рм/к, кгс/см²', 'Группа')
GROUP_NEAR_ZERO, GROUP_LOW, GROUP_HIGH = 'Р≈0', 'Р≤28', 'Р>28'


def valid_rows(rows: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Строки с числовым номером скважины (целое); второй результат — встреченные некорректные номера («`», пустые)."""
    number = pd.to_numeric(rows[WELL], errors='coerce')
    good = number.notna() & number.eq(number.round())
    bad = sorted({str(v).strip() or '(пусто)' for v in rows.loc[~good, WELL]})
    return rows[good].assign(**{WELL: number[good].astype(int)}), bad


def annulus_wells(rows: pd.DataFrame) -> pd.DataFrame:
    """Скважины с расходом или давлением за период: максимумы Q и P, группа по давлению. Порядок — по номеру скважины."""
    if rows.empty:
        return pd.DataFrame(columns=['well', 'q_max', 'p_max', 'group'])
    rows = valid_rows(rows)[0]
    grouped = rows.groupby(WELL).agg(q_max=(Q, 'max'), p_max=(P, 'max')).reset_index()
    grouped = grouped[(grouped['q_max'] > 0) | (grouped['p_max'] > 0)]
    grouped = grouped.rename(columns={WELL: 'well'}).sort_values('well').reset_index(drop=True)
    grouped['group'] = [pressure_group(q, p) for q, p in zip(grouped['q_max'], grouped['p_max'])]
    return grouped


def pressure_group(q: float, p: float) -> str:
    if p <= 0:
        return GROUP_NEAR_ZERO
    return GROUP_LOW if p <= P_LIMIT else GROUP_HIGH


def flow_group(q: float) -> str:
    if q <= 0:
        return 'нет расхода'
    if q <= Q_SMALL:
        return 'малый'
    return 'средний' if q <= Q_LARGE else 'большой'


def table_11_3(wells: pd.DataFrame) -> pd.DataFrame:
    """Результаты замеров МКД: номер скважины, Qм/к, Рм/к и группа; значения округлены как в отчёте (Q — до десятых, P — целые)."""
    out = pd.DataFrame({
        COLUMNS[0]: wells['well'].astype(int),
        COLUMNS[1]: wells['q_max'].round(1),
        COLUMNS[2]: wells['p_max'].round(0).astype(int),
        COLUMNS[3]: wells['group'],
    })
    return out.reset_index(drop=True)


def _numbers(values: Iterable[int]) -> str:
    return ', '.join(str(int(v)) for v in values)


def classification_text(wells: pd.DataFrame) -> list[str]:
    """Абзацы статистики под табл. 11.3 в её формулировках: группы по давлению и по расходу из МКП, с номерами скважин."""
    if wells.empty:
        return ['В выбранном периоде межколонные давления и расход из МКП не отмечены.']
    count = len(wells)
    near = wells[wells['group'] == GROUP_NEAR_ZERO]
    low = wells[wells['group'] == GROUP_LOW]
    high = wells[wells['group'] == GROUP_HIGH]
    lines = [
        f'В выбранном периоде межколонные давления отмечаются на {count} скважинах (таблица «Результаты замеров МКД»).',
        'По величине МКД и расхода из МКП скважины разделены на 3 условных группы:',
        f'Скважины с наличием расхода, но с минимальным (близким к нулю) МКД - {len(near)} скв. '
        f'(№ {_numbers(near["well"])});' if len(near) else
        'Скважины с наличием расхода, но с минимальным (близким к нулю) МКД - 0 скв.;',
        f'Скважины с максимальным МКД до {P_LIMIT:g} кгс/см² - {len(low)} скв. '
        f'(№ {_numbers(low["well"])});' if len(low) else
        f'Скважины с максимальным МКД до {P_LIMIT:g} кгс/см² - 0 скв.;',
        f'Скважины с МКД свыше {P_LIMIT:g} кгс/см² - {len(high)} скв. '
        f'(№ {_numbers(high["well"])}).' if len(high) else
        f'Скважины с МКД свыше {P_LIMIT:g} кгс/см² - 0 скв.',
    ]
    return lines + flow_text(wells)


def flow_text(wells: pd.DataFrame) -> list[str]:
    """Абзац про расход из МКП: малый (0 < Q ≤ 10), средний (10 < Q ≤ 90), большой (Q > 90), как в отчёте."""
    groups = wells['q_max'].map(flow_group)
    parts = []
    for name, label in (('малый', f'малой величиной расхода из МКП (0 < Q ≤ {Q_SMALL:g})'),
                        ('средний', f'средней величиной расхода из МКП ({Q_SMALL:g} < Q ≤ {Q_LARGE:g})'),
                        ('большой', f'большой величиной расхода из МКП (Q > {Q_LARGE:g})')):
        sel = wells[groups == name]
        parts.append(f'скважины с {label} - {len(sel)} ед.'
                     + (f' (скв. № {_numbers(sel["well"])})' if len(sel) else ''))
    return ['По величине расхода из МКП скважины разделены на 3 условных группы: ' + '; '.join(parts) + '.']
