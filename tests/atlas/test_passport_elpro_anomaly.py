"""Давление ЭЛПРО против группы, расходов и пластового: эпизоды аномалий и причина."""
from __future__ import annotations

import numpy as np
import pandas as pd

from atlas import passport_blocks
from atlas import passport_elpro_anomaly as an

DAYS = pd.date_range('2025-01-01', periods=120)


def make(well_drop: float, group_drop: float, res_drop: float = 0.0):
    """Скважина 1 и две соседки по группе: на 80-е сутки давление ЭЛПРО скважины падает на ``well_drop``, соседок — на ``group_drop``."""
    rows, prod = [], []
    for w, drop in (('1', well_drop), ('2', group_drop), ('3', group_drop)):
        p = np.where(np.arange(len(DAYS)) >= 80, 30.0 - drop, 30.0)
        rows += [{'well': w, 'date': d, 'kind': 'withdrawal', 'p': v} for d, v in zip(DAYS, p)]
        prod += [{'well': w, 'date': d, 'kind': 'withdrawal', 'q': 100000.0} for d in DAYS]
    pres = pd.DataFrame({'date': [DAYS[10], DAYS[75], DAYS[110]], 'pressure': [100.0, 100.0 - res_drop, 100.0 - res_drop]})
    group = {'1': 'ГСП-1', '2': 'ГСП-1', '3': 'ГСП-1'}
    return an.series(pd.DataFrame(rows), pd.DataFrame(prod), pres, '1', group)


def test_only_this_well_when_group_stays():
    df = make(well_drop=5.0, group_drop=0.0)
    (ep,) = an.episodes(df)
    assert ep['dp'] < -4.0 and 'только у этой скважины' in ep['cause'] and ep['direction'] == 'упало'
    assert abs(ep['dq']) < 1 and ep['dq_obj'] is not None                  # расход не менялся


def test_moves_with_group_or_with_reservoir():
    assert 'вместе с группой' in an.episodes(make(well_drop=5.0, group_drop=5.0))[0]['cause']
    (ep,) = an.episodes(make(well_drop=5.0, group_drop=0.0, res_drop=6.0))
    assert 'вместе с пластовым' in ep['cause'] and round(ep['dp_res']) == -6


def test_no_anomaly_below_threshold_and_missing_elpro_is_empty_not_zero():
    assert an.episodes(make(well_drop=1.0, group_drop=0.0)) == []
    assert an.series(None, None, None, '1', {}).empty and an.episodes(pd.DataFrame()) == []
    gap = make(5.0, 0.0).copy()
    gap.loc[gap.index[85:100], 'p'] = np.nan                             # пропуск ЭЛПРО — не ноль, давление не «падает» до нуля
    assert (gap.p.dropna() > 0).all() and all(abs(e['dp']) < 6 for e in an.episodes(gap))


def test_chart_and_table_use_common_core():
    data = {'rows': an.episodes(make(5.0, 0.0)), 'series': {'date': [d.strftime('%Y-%m-%d') for d in make(5.0, 0.0).index],
            **{c: [None if pd.isna(v) else float(v) for v in make(5.0, 0.0)[c]] for c in ('p', 'grp_p', 'q', 'p_res')}}}
    chart, table = passport_blocks.elpro_pressure_chart(data), passport_blocks.elpro_anomaly_table(data)
    assert chart.id == 'passport-elpro-p' and chart.style['annotations'][0]['kind'] == 'vband' and table.id == 'passport-elpro-anomalies'
    assert [s.name for s in chart.series][:2] == ['Давление ЭЛПРО скважины', 'Давление ЭЛПРО: медиана по группе']
