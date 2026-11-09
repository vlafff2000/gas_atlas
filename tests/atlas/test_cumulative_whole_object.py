"""Накопленный объём объекта (ось X) не зависит от фильтра скважин вкладки: фильтр лишь выбирает показанные кривые."""
import numpy as np
import pandas as pd

from atlas import well_filter
from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.engine.modules import production as legacy
from atlas.modules._production import Selection

PROD = DatasetKind.PRODUCTION


def _data():
    dates = pd.date_range('2025-11-01', periods=4)
    rows = [(d, w, 'withdrawal', '2025-2026', q) for w, q in (('1', 1000.0), ('2', 3000.0)) for d in dates]
    frame = pd.DataFrame(rows, columns=['date', 'well', 'kind', 'period', 'q'])
    data = Data({PROD: frame}, {PROD: frame}, {})
    data.mapping = {'1': {'group': 'ГСП 1'}, '2': {'group': 'ГСП 2'}}
    data.wells = ['1', '2']
    return data


def test_curve_x_is_whole_object_when_well_filter_keeps_one_well():
    data = _data()
    narrowed = well_filter.apply(data, {'groups': [], 'wells': ['1']})
    sel = Selection(narrowed, {'kind': 'withdrawal', 'periods': ['2025-2026'], 'groups': ['ГСП 1'], 'wells': ['1']})
    out = legacy.curve_data(sel.df, sel.kind, sel.periods, ['1'], whole=sel.whole)
    assert set(out.well) == {'1'}
    assert np.allclose(out.cumulative, [0.004, 0.008, 0.012, 0.016])      # 1000 + 3000 м³/сут на объект, а не 1000
