"""Ускорение «Пакета по фонду»: хеш общей таблицы считается один раз, графики строятся по индексу, рисуются процессами; результат прежний."""
import gc
import hashlib
import pickle

import numpy as np
import pandas as pd

from atlas import api_export, parallel
from atlas.engine.core import performance
from atlas.engine.core.reporting import FigureJob
from atlas.engine.modules import charts, production


def daily_production(days=3000):
    """Четыре скважины, оба режима, по строке в сутки (24 000 строк — больше порога учёта хешей и индекса)."""
    dates = pd.date_range('2012-01-01', periods=days)
    rng = np.random.default_rng(5)
    parts = [pd.DataFrame({'well': well, 'date': dates, 'kind': kind, 'q': rng.normal(50000, 9000, days), 'group': 'Г', 'subgroup': '',
                           'file': 'f', 'sheet': 's', '_row': np.arange(days), '_point_id': [f'{well}:{kind}:{i}' for i in range(days)]})
             for well in ('1', '2', '31', '132') for kind in ('withdrawal', 'injection')]
    return production.periods(pd.concat(parts, ignore_index=True), 11, 4)


def direct_digest(df):
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes() + str(list(df.columns)).encode('utf8')).hexdigest()


def test_frame_digest_equals_direct_hash_and_is_remembered():
    d = daily_production()
    assert performance.frame_digest(d) == direct_digest(d)
    assert id(d) in performance._DIGESTS
    assert performance.frame_digest(d) == direct_digest(d)
    other = d.assign(q=d.q + 1)
    assert performance.frame_digest(other) != performance.frame_digest(d)
    key = id(other)
    del other
    gc.collect()
    assert key not in performance._DIGESTS


def test_with_index_gives_same_curves_and_own_cache_token():
    plain = daily_production()
    plain.attrs['_atlas_token'] = 'stale-token-of-the-prepared-table'
    indexed = performance.with_index(plain.copy(), 'production')
    assert performance.index_for(indexed) is not None and performance.index_for(plain) is None
    assert indexed.attrs['_atlas_token'] != 'stale-token-of-the-prepared-table'
    periods = production.periods(indexed, 11, 4).period.unique().tolist()[:3]
    for kind in ('withdrawal', 'injection'):
        pd.testing.assert_frame_equal(production.curve_data(indexed, kind, periods, ['2', '31']),
                                      production.curve_data(plain, kind, periods, ['2', '31']))
        assert production.period_colors(indexed, kind) == production.period_colors(plain, kind)


def test_chart_with_index_equals_chart_without():
    plain = daily_production()
    indexed = performance.with_index(plain.copy(), 'production')
    ps = production.periods(plain, 11, 4).period.unique().tolist()[:2]
    a = charts.production_curve(indexed, 'withdrawal', ps, ['31'], interactive=False)
    b = charts.production_curve(plain, 'withdrawal', ps, ['31'], interactive=False)
    assert a.to_json() == b.to_json()


def test_pack_init_reattaches_index_after_pickle():
    d = performance.with_index(daily_production(), 'production')
    job = FigureJob('Отбор · 31', None, {})
    job.factory = __import__('functools').partial(charts.production_curve, d, 'withdrawal', ['2012-2013'], ['31'])
    jobs, indexed = pickle.loads(pickle.dumps(([job], [f for f in api_export._job_frames([job]) if performance.index_for(f) is not None])))
    frame = jobs[0].factory.args[0]
    assert performance.index_for(frame) is None          # объект новый — прежняя привязка по id потеряна
    api_export._pack_init(jobs, (), indexed)
    assert performance.index_for(frame) is not None


def test_pack_init_does_not_adopt_foreign_index():
    """У копии таблицы в ``attrs`` остаётся индекс исходной: он не её, и привязывать его нельзя (иной состав периодов — иные цвета)."""
    source = performance.with_index(daily_production(), 'production')
    copy = source.copy()
    assert performance.index_for(copy) is None
    job = FigureJob('Отбор · 31', None, {})
    job.factory = __import__('functools').partial(charts.production_curve, copy, 'withdrawal', ['2012-2013'], ['31'])
    jobs, indexed = pickle.loads(pickle.dumps(([job], [f for f in api_export._job_frames([job]) if performance.index_for(f) is not None])))
    assert indexed == []
    api_export._pack_init(jobs, (), indexed)
    assert performance.index_for(jobs[0].factory.args[0]) is None


# --- пул процессов -----------------------------------------------------------------------------------------------

_STATE = {}


def _set(value):
    _STATE['value'] = value


def _times(i):
    return _STATE['value'] * i


def test_map_jobs_initializer_in_process(monkeypatch):
    monkeypatch.setenv('PXG_WORKERS', '1')
    assert parallel.map_jobs(_times, range(5), initializer=_set, initargs=(3,)) == [0, 3, 6, 9, 12]


def test_map_jobs_initializer_in_pool(monkeypatch):
    monkeypatch.setenv('PXG_WORKERS', '2')
    monkeypatch.setenv('PXG_PARALLEL_MIN', '1')
    assert parallel.map_jobs(_times, range(6), initializer=_set, initargs=(4,)) == [0, 4, 8, 12, 16, 20]
