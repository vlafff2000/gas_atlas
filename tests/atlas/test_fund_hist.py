"""Гистограммы по фондам: число скважин по фондам и деление эксплуатационных на группы."""
import pandas as pd

from atlas import well_funds
from atlas.contract import Data, DatasetKind
from atlas.modules.fund_hist import FundHistModule, UNKNOWN


def make() -> Data:
    gis = pd.DataFrame({'well': ['7', '8', '9'], 'date': pd.to_datetime(['2025-01-01'] * 3), 'pack': ['A'] * 3})
    geo = pd.DataFrame({'well': ['8'], 'perf_top': [-900.0], 'perf_bottom': [-950.0]})
    data = Data({DatasetKind('gis_packs'): gis, DatasetKind('well_geo'): geo})
    data.mapping = {'1': {'group': 'ГСП 1', 'subgroup': 'a'}, '2': {'group': 'ГСП 1', 'subgroup': 'b'}, '3': {'group': 'ГСП 2', 'subgroup': 'a'}}
    data.wells = ['1', '2', '3', '7', '8', '9']
    data.settings = well_funds.with_funds({}, {'9': 'control'})
    return data


def test_counts_by_fund_and_group():
    res = FundHistModule().run(make(), {'split': 'group', 'funds': []})
    funds = dict(zip(res.charts[0].series[0].x, res.charts[0].series[0].y))
    assert funds['Эксплуатационная'] == 3 and funds['Наблюдательная'] == 1
    assert funds['Геофизическая'] == 1 and funds['Контрольная'] == 1 and funds[UNKNOWN] == 0
    groups = dict(zip(res.charts[1].series[0].x, res.charts[1].series[0].y))
    assert groups == {'ГСП 1': 2, 'ГСП 2': 1}
    sub = FundHistModule().run(make(), {'split': 'subgroup', 'funds': ['Контрольная']})
    assert list(sub.charts[0].series[0].x) == ['Контрольная']
    assert dict(zip(sub.charts[1].series[0].x, sub.charts[1].series[0].y)) == {'a': 2, 'b': 1}


def test_no_data_is_a_note():
    res = FundHistModule().run(Data({}), {'split': 'group', 'funds': []})
    assert not res.charts and res.notes
