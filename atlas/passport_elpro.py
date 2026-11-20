"""ЭЛПРО в паспорте скважины: открытие КРУ по сезонам отбора, расход на 1 % КРУ и давление при том же расходе.

Только выбор данных и представление, настроек нет: пороги фиксированы и видны в подсказке. Расход берётся из БД суточных расходов (как
в разделе «Комплексный анализ продуктивности»), а не из ЭЛПРО; пропуск суток ЭЛПРО — не ноль, такие сутки в расчёт не идут.
Вывод по сезону — подсказка с причиной, решает инженер.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from atlas.modules._elpro_series import daily_values

HIGH_OPEN = 90.0        # КРУ раскрыт почти полностью: запас регулирования исчерпан
HIGH_SHARE = 30.0       # доля таких суток сезона, % — после неё сезон помечается
MIN_OPEN = 10.0         # при меньшем раскрытии расход на 1 % КРУ не считается (знаменатель мал)
BAND = 0.15             # «тот же расход» для давления: ±15 % от медианного расхода скважины
MIN_DAYS = 5
DROP = -15.0            # падение расхода на 1 % КРУ к прошлому сезону, %, после которого сезон помечается

HOW_TO_READ = (
    'КРУ, % — степень открытия регулирующего устройства: чем больше, тем больше запас уже выбран. Если КРУ почти полностью открыт (≥ 90 %) '
    'много суток, а расход падает, регулировать больше нечем — причина в скважине или шлейфе, не в режиме.',
    'Расход на 1 % КРУ — ключевой показатель: сколько газа даёт один процент открытия. Падает от сезона к сезону — растёт сопротивление '
    '(песок, забой, ПЗП); падает у всей группы — смотрите шлейф и пластовое давление.',
    'Давление устья при том же расходе (±15 % от обычного расхода скважины): растёт — сопротивление в скважине растёт; падает — '
    'пластовое давление или режим шлейфа.',
    'Сезон без записей ЭЛПРО остаётся пустым, ноль туда не подставляется. «Внимание» — подсказка с причиной, а не приговор: решает инженер.')


def season_rows(elpro: pd.DataFrame | None, daily: pd.DataFrame, well: str) -> list[dict[str, Any]]:
    """Сезоны отбора по порядку: суток с ЭЛПРО, КРУ среднее/макс, доля суток ≥ 90 %, расход на 1 % КРУ, давление при обычном расходе, вывод."""
    if elpro is None or elpro.empty or daily is None or daily.empty or not {'p', 'y'} <= set(elpro.columns):
        return []
    e = daily_values(elpro, 'withdrawal', well).reset_index()
    if e.empty:
        return []
    d = daily[daily.gas_volume_m3.notna()].assign(date=lambda x: pd.to_datetime(x.date).dt.normalize(), q=lambda x: x.gas_volume_m3 / 1000)
    d = d.groupby(['date', 'period'], as_index=False).q.sum().merge(e, on='date', how='left')
    typical = d.loc[d.q.gt(0), 'q'].median()
    rows: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    for period, g in d.groupby('period', sort=False):
        have = g[g.cru.notna()]
        if have.empty:
            rows.append({'period': str(period), 'days': 0, 'mean_open': None, 'max_open': None, 'high_share': None, 'eff': None, 'eff_change': None,
                         'p_same_q': None, 'p_change': None, 'verdict': 'нет данных ЭЛПРО', 'reason': ''})
            continue
        eff_days = have[have.q.gt(0) & have.cru.ge(MIN_OPEN)]
        eff = float((eff_days.q / eff_days.cru).median()) if len(eff_days) >= MIN_DAYS else None
        band = have[have.p.notna() & have.q.between(typical * (1 - BAND), typical * (1 + BAND))] if pd.notna(typical) else have.iloc[0:0]
        p_same = float(band.p.median()) if len(band) >= MIN_DAYS else None
        share = float(have.cru.ge(HIGH_OPEN).mean() * 100)
        row = {'period': str(period), 'days': int(len(have)), 'mean_open': float(have.cru.mean()), 'max_open': float(have.cru.max()), 'high_share': share,
               'eff': eff, 'eff_change': None, 'p_same_q': p_same, 'p_change': None}
        if prev:
            if eff is not None and prev['eff']:
                row['eff_change'] = (eff / prev['eff'] - 1) * 100
            if p_same is not None and prev['p_same_q']:
                row['p_change'] = p_same - prev['p_same_q']
        reasons = []
        if share >= HIGH_SHARE:
            reasons.append(f'КРУ ≥ {HIGH_OPEN:g} % в {share:.0f} % суток: запас регулирования выбран')
        if row['eff_change'] is not None and row['eff_change'] <= DROP:
            reasons.append(f'расход на 1 % КРУ упал на {abs(row["eff_change"]):.0f} % к прошлому сезону')
        row['verdict'] = 'внимание' if reasons else 'норма'
        row['reason'] = '; '.join(reasons)
        rows.append(row)
        prev = row
    return rows


def cru_series(elpro: pd.DataFrame | None, well: str) -> tuple[list[str], list[float | None]]:
    """Открытие КРУ по суткам для правой оси суточного графика; пропуск суток — разрыв (None)."""
    if elpro is None or elpro.empty or 'y' not in elpro:
        return [], []
    e = daily_values(elpro, 'withdrawal', well)
    e = e[e.cru.notna()]
    return [d.strftime('%Y-%m-%d') for d in e.index], [float(v) for v in e.cru]
