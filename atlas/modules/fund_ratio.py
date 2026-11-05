"""«Аналитика фонда»: сезон А к сезонам Б по каждой скважине.

Значение каждого показателя в сезоне А делится на среднее значение этого показателя по сезонам Б. Среднее Б — по сезонам,
где у скважины есть записи (сезон без записей — «нет данных», а не ноль). Нет данных в А, в Б или среднее Б равно нулю —
ячейка пуста и причина записана в колонке «Примечание»: деление на ноль не падает и не даёт бесконечность.
"""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from atlas.engine.modules import group_analysis

# (ключ в рейтинге, подпись, единица)
METRICS: tuple[tuple[str, str, str], ...] = (
    ('Средний_тыс_м3_сут', 'Средний расход', 'тыс. м³/сут'),
    ('Объем_млн_м3', 'Объем', 'млн м³'),
    ('Активных_дней', 'Активных дней', 'сут'),
    ('Записей', 'Записей', ''),
    ('Нулевых', 'Нулевых записей', ''),
)


def season_metrics(prod: pd.DataFrame, mapping: Mapping, periods: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Показатели по скважинам для каждого сезона (скважина — индекс): тот же расчёт, что у рейтинга."""
    out = {}
    for period in periods:
        one = prod[prod['period'].eq(period)]
        out[period] = (group_analysis.ranking(one, mapping).set_index('Скважина') if not one.empty else pd.DataFrame())
    return out


def ratio_table(metrics: Mapping[str, pd.DataFrame], base: str, against: Sequence[str],
                keys: Sequence[tuple[str, str, str]] = METRICS) -> pd.DataFrame:
    """Строка на скважину: Скважина, Группа, отношение А/ср.Б по каждому показателю, Примечание."""
    against = [p for p in against if p != base]
    a = metrics.get(base, pd.DataFrame())
    b = [metrics[p] for p in against if p in metrics and not metrics[p].empty]
    wells = sorted(set(a.index) | {w for m in b for w in m.index}, key=lambda w: (len(str(w)), str(w)))
    rows = []
    for well in wells:
        row: dict = {'Скважина': well, 'Группа': next((m.at[well, 'Группа'] for m in [a, *b] if well in m.index), '')}
        why = []
        in_a = well in a.index
        seasons_b = [m for m in b if well in m.index]
        if not in_a:
            why.append(f'нет записей в сезоне {base}')
        if not seasons_b:
            why.append('нет записей в сезонах Б')
        for key, label, _ in keys:
            value = float(a.at[well, key]) if in_a and key in a.columns else np.nan
            mean = float(np.mean([float(m.at[well, key]) for m in seasons_b])) if seasons_b else np.nan
            if np.isnan(value) or np.isnan(mean):
                row[key] = np.nan
            elif mean == 0:
                row[key] = np.nan
                why.append(f'«{label}»: среднее по Б равно 0')
            else:
                row[key] = value / mean
        row['Примечание'] = '; '.join(why)
        rows.append(row)
    return pd.DataFrame(rows, columns=['Скважина', 'Группа', *[k for k, _, _ in keys], 'Примечание'])
