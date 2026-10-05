"""Динамика коэффициентов ГДИ и рейтинг скважин: паритет с gdi_history 5.8, ухудшение находится и стоит первым."""
import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from app.core.config import DEFAULT_SETTINGS
from app.core.demo import well_demo_frames
from app.core.storage import Store
from app.modules import well_analysis as legacy
from atlas.api import create_app
from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules.gdi_trend import GdiTrendModule, VERDICTS, histories, rating
from atlas.projects import Projects

PARAMS = {'wells': [], 'methods': [], 'threshold': 0.95, 'change': 10.0, 'last_n': 0}


def degraded():
    g = well_demo_frames()['gdi'].copy()
    g.loc[g.well.eq('31') & g.date.gt('2025-01-01'), 'dp2'] *= 1.3      # у скважины 31 отдача упала
    return g


def table(result, tid):
    return next(t for t in result.tables if t.id == tid).frame


def test_history_is_gdi_history_of_58_per_well():
    g = degraded()
    mine = histories(g, 0.95, [])
    for well, part in g.groupby('well'):
        theirs = legacy.gdi_history(part, 0.95)
        got = mine[mine.well.eq(well)].reset_index(drop=True)
        for col in ('a', 'b', 'r2', 'reliable', 'q_reference'):
            pd.testing.assert_series_equal(got[col], theirs[col], check_names=False, check_dtype=False)


def test_degraded_well_is_first_in_rating():
    result = GdiTrendModule().run(Data({DatasetKind.GDI: degraded()}), PARAMS)
    rows = table(result, 'rating')
    assert rows.iloc[0].well == '31' and rows.iloc[0].verdict == VERDICTS['down'] and rows.iloc[0]['rank'] == 1
    assert rows.iloc[0].change == pytest.approx(
        (rows.iloc[0].q_last - rows.iloc[0].q_first) / rows.iloc[0].q_first * 100)
    assert rows.iloc[0].a_change > 0 and rows.iloc[0].b_change > 0       # a и b выросли
    assert set(rows.iloc[1:].verdict) == {VERDICTS['same']}
    assert [c.id for c in result.charts] == ['trend-q', 'trend-a', 'trend-b'] and len(result.charts[0].series) == 8
    stats = {s.label: s.value for s in result.summary}
    assert stats['Скважин'] == '8' and stats['С ухудшением'] == '1'


def test_threshold_decides_verdict_and_few_studies():
    history = histories(degraded(), 0.95, [])
    assert rating(history, 50).iloc[0].verdict == VERDICTS['same']       # −11% при пороге 50% — не ухудшение
    one = history[history.date.eq(history.date.min())]
    assert set(rating(one, 10).verdict) == {VERDICTS['few']} and rating(one, 10)['rank'].isna().all()


def test_last_n_limits_studies_and_empty_selection_is_a_note():
    module = GdiTrendModule()
    two = module.run(Data({DatasetKind.GDI: degraded()}), {**PARAMS, 'last_n': 2})
    assert table(two, 'rating').reliable.max() == 2
    none = module.run(Data({DatasetKind.GDI: degraded()}), {**PARAMS, 'wells': ['нет такой']})
    assert not none.tables and none.notes[0].level == 'warning'


def test_spec_through_api(tmp_path):
    store = Store(tmp_path)
    pid = store.create('Объект', demo=True)
    store.commit(pid, {**well_demo_frames(), 'gdi': degraded()}, settings={**DEFAULT_SETTINGS}, action='Загрузка')
    client = TestClient(create_app(Projects(tmp_path)))
    spec = next(s for s in client.get('/api/modules').json() if s['id'] == 'gdi_trend')
    assert spec['needs'] == ['gdi'] and any(p['formula'] for p in spec['params'])
    body = client.post('/api/modules/gdi_trend/run', json={'project': pid, 'params': {}}).json()
    assert body['tables'][0]['id'] == 'rating' and len(body['charts']) == 3
