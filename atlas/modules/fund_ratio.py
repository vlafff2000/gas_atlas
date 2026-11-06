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


CRU_KEY = 'КРУ_среднее'
CRU_METRIC = (CRU_KEY, 'Среднее раскрытие КРУ', '%')


def mean_cru(prod: pd.DataFrame, elpro: pd.DataFrame | None) -> pd.Series:
    """Среднее раскрытие КРУ (0–100 %) по скважинам за период записей эксплуатации (ЭЛПРО, ``y``).

    Берутся все имеющиеся значения ЭЛПРО скважины между первыми и последними сутками этих записей (сезона): данных может быть
    мало и они не обязаны покрывать сезон или совпадать с сутками расхода из БД. Сутки без записи ЭЛПРО пропускаются, нулём
    не считаются. Скважина без значений ЭЛПРО за период — нет значения.
    """
    if elpro is None or elpro.empty or prod.empty:
        return pd.Series(dtype=float)
    e = elpro[elpro['kind'].isin(prod['kind'].unique()) & elpro['well'].astype(str).isin(set(prod['well'].astype(str)))]
    daily = pd.DataFrame({'well': e['well'].astype(str).to_numpy(), 'date': pd.to_datetime(e['date']).dt.normalize().to_numpy(),
                          'cru': e['y'].clip(0, 100).to_numpy()}).dropna()
    daily = daily.groupby(['well', 'date'], as_index=False).cru.mean()
    keep = pd.Series(False, index=daily.index)
    for _, part in (prod.groupby('period') if 'period' in prod else [(None, prod)]):   # окно каждого сезона, межсезонье не входит
        dates = pd.to_datetime(part['date'])
        keep |= daily['date'].between(dates.min().normalize(), dates.max().normalize())
    daily = daily[keep]
    return daily.groupby('well').cru.mean()


def with_cru(ranked: pd.DataFrame, prod: pd.DataFrame, elpro: pd.DataFrame | None) -> pd.DataFrame:
    """Рейтинг + столбец КРУ_среднее (если в проекте есть ЭЛПРО)."""
    if elpro is None or elpro.empty:
        return ranked
    out = ranked.copy()
    out[CRU_KEY] = out['Скважина'].astype(str).map(mean_cru(prod, elpro))
    return out


def season_metrics(prod: pd.DataFrame, mapping: Mapping, periods: Sequence[str], elpro: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Показатели по скважинам для каждого сезона (скважина — индекс): тот же расчёт, что у рейтинга (+ КРУ из ЭЛПРО)."""
    out = {}
    for period in periods:
        one = prod[prod['period'].eq(period)]
        out[period] = (with_cru(group_analysis.ranking(one, mapping), one, elpro).set_index('Скважина') if not one.empty else pd.DataFrame())
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
