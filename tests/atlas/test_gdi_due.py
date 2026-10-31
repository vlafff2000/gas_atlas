"""«Кому пора на ГДИ»: признаки, причины и ручное решение инженера."""
import pandas as pd
import pytest

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules.gdi_due import GdiDueModule, STATE_ADDED, STATE_AUTO, STATE_REMOVED, apply_manual, build, relative_drop, season_flows

P = DatasetKind.PRODUCTION
PARAMS = {'years': 5.0, 'gap': 15.0, 'threshold': 0.95, 'change': 10.0, 'kru_priority': 2, 'add': [], 'remove': [],
          'today': '2026-10-31'}


def production():
    rows = []
    # две скважины одной группы стабильны (−0%), третья упала на 40%, четвёртая — в другой группе без второго сезона
    for w, prev, last in (('1', 100, 100), ('2', 100, 100), ('3', 100, 60)):
        for period, q, start in (('2024-2025', prev, '2024-11-01'), ('2025-2026', last, '2025-11-01')):
            for d in pd.date_range(start, periods=10):
                rows.append(dict(well=w, date=d, q=q * 1e3, kind='withdrawal', period=period))
    for d in pd.date_range('2025-11-01', periods=10):
        rows.append(dict(well='4', date=d, q=50e3, kind='withdrawal', period='2025-2026'))
    return pd.DataFrame(rows)


def gdi(well, year, scale=1.0):
    rows = []
    for q in (45., 90., 140., 190.):
        dp2 = (0.7 * q + 0.012 * q * q) * scale
        rows.append(dict(well=well, date=pd.Timestamp(f'{year}-12-10'), q=q, p_res=75., p_bh=(75. ** 2 - dp2) ** .5, dp2=dp2,
                         a_db=0.7, b_db=0.012, method='Установившиеся отборы', study='', season=f'{year}-{year + 1}', group='ГСП-1'))
    return rows


def data(with_gdi=True, kru=None):
    frames = {P: production()}
    frames[DatasetKind.GDI] = pd.DataFrame(gdi('1', 2024) + gdi('2', 2018) + gdi('3', 2025)) if with_gdi else pd.DataFrame()
    if kru is not None:
        frames[DatasetKind.KRS_PRIORITY] = kru
    d = Data(frames)
    d.mapping = {'1': {'group': 'ГСП-1'}, '2': {'group': 'ГСП-1'}, '3': {'group': 'ГСП-1'}, '4': {'group': 'ГСП-2'}}
    d.wells = ['1', '2', '3', '4']
    return d


def test_flows_use_withdrawal_seasons_only_and_group_median():
    flows = relative_drop(season_flows(production()), {'1': 'A', '2': 'A', '3': 'A', '4': 'B'})
    row = flows.set_index('well')
    assert row.at['3', 'change'] == pytest.approx(-40)
    assert row.at['3', 'gap'] == pytest.approx(-40)           # медиана группы 0%
    assert pd.isna(row.at['4', 'change'])                     # нет предыдущего сезона — не нуль, а пропуск


def test_flags_and_reasons():
    t = build(data(), PARAMS).set_index('well')
    assert bool(t.at['2', 'f_age']) and 'лет назад' in t.at['2', 'reason']            # ГДИ 2018 года
    assert not t.at['1', 'f_age'] and t.at['1', 'score'] == 0                          # ГДИ 2024, расход стабилен
    assert bool(t.at['3', 'f_flow']) and 'упал на 40%' in t.at['3', 'reason']
    assert bool(t.at['4', 'f_age']) and t.at['4', 'reason'] == 'надёжного ГДИ нет'     # исследований нет


def test_priority_flag_follows_param():
    kru = pd.DataFrame({'well': ['1'], 'priority': [1.]})
    assert bool(build(data(kru=kru), PARAMS).set_index('well').at['1', 'f_kru'])
    off = {**PARAMS, 'kru_priority': -1}
    assert not build(data(kru=kru), off).f_kru.any()


def test_manual_decision_beats_calculation():
    t = apply_manual(build(data(), PARAMS), add=['1'], remove=['2']).set_index('well')
    assert t.at['1', 'in_list'] and t.at['1', 'state'] == STATE_ADDED
    assert not t.at['2', 'in_list'] and t.at['2', 'state'] == STATE_REMOVED
    assert 'лет назад' in t.at['2', 'reason']                       # расчёт остаётся виден
    assert t.at['3', 'state'] == STATE_AUTO and t.at['3', 'in_list']


def test_module_runs_and_empty_project_is_a_note():
    result = GdiDueModule().run(data(), PARAMS)
    table = next(t for t in result.tables if t.id == 'gdi-due').frame
    assert table.well.tolist()[0] in {'2', '3', '4'} and len(table) == 4
    empty = GdiDueModule().run(Data({}), PARAMS)
    assert not empty.tables and empty.notes
