"""Динамика коэффициентов ГДИ и рейтинг скважин: паритет с gdi_history 5.8, ухудшение находится и стоит первым."""
import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.engine.core.config import DEFAULT_SETTINGS
from atlas.engine.core.demo import well_demo_frames
from atlas.engine.core.storage import Store
from atlas.engine.modules import well_analysis as legacy
from atlas.api import create_app
from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules.gdi_trend import GdiTrendModule, VERDICTS, histories, quality_filter, rating
from atlas.projects import Projects

PARAMS = {'wells': [], 'quality': 'all', 'threshold': 0.95, 'change': 10.0, 'last_n': 0}


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


def test_quality_filter_splits_by_r2_threshold():
    history = histories(degraded(), 0.95, [])
    good = quality_filter(history, 'good', 0.95)
    low = quality_filter(history, 'low', 0.95)
    assert len(good) + len(low) == len(history) and good.r2.ge(0.95).all() and not low.r2.ge(0.95).any()
    assert quality_filter(history, 'all', 0.95) is history
    module = GdiTrendModule()
    only_low = module.run(Data({DatasetKind.GDI: degraded()}), {**PARAMS, 'quality': 'low', 'threshold': 1.01})
    assert table(only_low, 'studies').shape[0] == len(history) and not only_low.charts
    assert table(only_low, 'rating').verdict.eq(VERDICTS['few']).all()


def coef_only():
    rows = [dict(well='9', date=pd.Timestamp(d), method='М', study='', q=np.nan, dp2=np.nan, a_db=a, b_db=.012, p_res=np.nan, p_bh=np.nan)
            for d, a in (('2024-12-01', .7), ('2025-12-01', 1.5))]
    return pd.DataFrame(rows)


def test_only_a_and_b_studies_show_coef_change_and_need_reference_dp2():
    """ГДИ только с a и b (нет Q, давлений): без опорного ΔP² — изменение a и b, с ним — изменение расхода."""
    data = Data({DatasetKind.GDI: coef_only()}, {})
    res = GdiTrendModule().run(data, PARAMS)
    t = table(res, 'rating').iloc[0]
    assert t.verdict == VERDICTS['coef'] and abs(t.a_change - 114.286) < .01 and pd.isna(t.change)
    assert any('Опорный ΔП²'.replace('П', 'P') in n.text or 'Опорный ΔP²' in n.text for n in res.notes)
    res2 = GdiTrendModule().run(data, {**PARAMS, 'dp2_ref': 500.0})
    t2 = table(res2, 'rating').iloc[0]
    assert t2.change < 0 and t2.verdict == VERDICTS['down'] and t2.dp2 == 500.0


def test_boundary_rate_picks_reference_dp2_automatically_beyond_data():
    """Граничный расход: опорный ΔP² = ΔP² первого надёжного исследования при Q; кривая продолжается за режимы, данными не ограничена."""
    rows = []
    for d, k in (('2024-12-01', 1.0), ('2025-12-01', 1.3)):
        for q in (20., 50., 80., 120.):
            rows.append(dict(well='1', date=pd.Timestamp(d), method='М', study='', q=q, dp2=(.7 * q + .012 * q * q) * k, a_db=np.nan, b_db=np.nan))
    data = Data({DatasetKind.GDI: pd.DataFrame(rows)}, {})
    t = table(GdiTrendModule().run(data, {**PARAMS, 'q_max': 300.0}), 'rating').iloc[0]
    assert abs(t.q_first - 300) < 1e-6 and t.q_last < 300 and t.change < -10 and t.verdict == VERDICTS['down']
    assert abs(t.dp2 - (.7 * 300 + .012 * 300 ** 2)) < 1e-6
    t0 = table(GdiTrendModule().run(Data({DatasetKind.GDI: coef_only()}, {}), {**PARAMS, 'q_max': 300.0}), 'rating').iloc[0]
    assert abs(t0.q_first - 300) < 1e-6 and t0.change < 0
