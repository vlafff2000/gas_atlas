"""Справка предельных депрессий и расходов: расход по свежему ГДИ, предел вручную главнее, песок КРУ в примечании."""
import pandas as pd

from atlas import limit_flow as lf
from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules.gdi_limits import GdiLimitsModule, auto_start

G, P = DatasetKind.GDI, DatasetKind.KRS_PRIORITY
PARAMS = {'threshold': 0.95, 'p_start': 0, 'p_step': 10, 'p_count': 3, 'limits': '', 'old_years': 3.0}


def study(well, date, scale=1.0):
    rows = []
    for q in (45., 90., 140., 190.):
        dp2 = (0.7 * q + 0.012 * q * q) * scale
        rows.append(dict(well=well, date=pd.Timestamp(date), q=q, p_res=75., p_bh=(75. ** 2 - dp2) ** .5, dp2=dp2, a_db=0.7 * scale, b_db=0.012 * scale,
                         method='Установившиеся отборы', study='', season='2025-2026'))
    return rows


def run(params=None, priority=None):
    frames = {G: pd.DataFrame(study('1', '2023-12-10') + study('1', '2025-12-10', 1.5) + study('2', '2025-12-10'))}
    if priority is not None:
        frames[P] = priority
    d = Data(frames)
    d.mapping = {'1': {'group': 'ГСП-1'}, '2': {'group': 'ГСП-2'}}
    return GdiLimitsModule().run(d, {**PARAMS, **(params or {})})


def test_flow_uses_latest_reliable_study_and_manual_limit():
    t = run({'limits': '1=2,0'}).tables[0].frame.set_index('well')
    assert t.loc['1', 'dp'] == 2.0 and t.loc['1', 'source'] == 'задан вручную'
    assert round(t.loc['1', 'q_80'], 6) == round(lf.q_at_limit(80.0, 1.05, 0.018, 2.0), 6)      # a, b — свежего ГДИ (×1,5), а не старого
    assert t.loc['1', 'q_80'] > t.loc['1', 'q_70'] > t.loc['1', 'q_60'] and t.loc['1', 'drop'] < 0


def test_no_limit_means_no_flow_not_zero_and_note():
    t = run().tables[0].frame.set_index('well')
    assert pd.isna(t.loc['2', 'dp']) and pd.isna(t.loc['2', 'q_80']) and 'предел депрессии не задан' in t.loc['2', 'note']


def test_sand_in_kru_goes_to_note_and_auto_start():
    prio = pd.DataFrame([dict(well='1', sand='2023-2024')])
    t = run({'limits': '1=2'}, prio).tables[0].frame.set_index('well')
    assert 'песок в ревизиях 2023-2024' in t.loc['1', 'note']
    assert auto_start(pd.Series([75.0, 77.0]), 10) == 80.0
