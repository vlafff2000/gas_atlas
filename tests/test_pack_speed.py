"""Ускорение «Пакета по фонду»: хеш общей таблицы считается один раз, графики строятся по индексу, рисуются процессами; результат прежний."""
import gc
import hashlib
import pickle

import numpy as np
import pandas as pd

from atlas import chart_labels, parallel, render_pool
from atlas.engine.core import performance
from atlas.engine.core.reporting import FigureJob
from atlas.engine.core.demo import demo_frames
from atlas.engine.modules import charts, production, well_analysis


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
    jobs, indexed = pickle.loads(pickle.dumps(([job], [f for f in render_pool.job_frames([job]) if performance.index_for(f) is not None])))
    frame = jobs[0].factory.args[0]
    assert performance.index_for(frame) is None          # объект новый — прежняя привязка по id потеряна
    render_pool._init(0, jobs, indexed, None, None)
    assert performance.index_for(frame) is not None


def test_pack_init_does_not_adopt_foreign_index():
    """У копии таблицы в ``attrs`` остаётся индекс исходной: он не её, и привязывать его нельзя (иной состав периодов — иные цвета)."""
    source = performance.with_index(daily_production(), 'production')
    copy = source.copy()
    assert performance.index_for(copy) is None
    job = FigureJob('Отбор · 31', None, {})
    job.factory = __import__('functools').partial(charts.production_curve, copy, 'withdrawal', ['2012-2013'], ['31'])
    jobs, indexed = pickle.loads(pickle.dumps(([job], [f for f in render_pool.job_frames([job]) if performance.index_for(f) is not None])))
    assert indexed == []
    render_pool._init(0, jobs, indexed, None, None)
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


# --- общий пул построения графиков ---------------------------------------------------------------------------------

def _name_and_payload(job, params, payload):
    if job.name == 'bad':
        raise ValueError('не построился')
    return job.name + params + str(payload)


def test_render_pool_keeps_order_and_isolates_errors(monkeypatch):
    monkeypatch.setenv('PXG_WORKERS', '1')
    jobs = [FigureJob(name, None, {}) for name in ('a', 'bad', 'c')]
    assert render_pool.run(jobs, _name_and_payload, '!', payloads=[1, 2, 3]) == [('a!1', None), (None, 'не построился'), ('c!3', None)]
    assert render_pool.run(jobs, _name_and_payload, '!', indices=[2]) == [('c!None', None)]


def test_render_pool_in_pool_matches_in_process(monkeypatch):
    jobs = [FigureJob(f'g{i}', None, {}) for i in range(30)]
    monkeypatch.setenv('PXG_WORKERS', '1')
    single = render_pool.run(jobs, _name_and_payload, '?')
    monkeypatch.setenv('PXG_WORKERS', '2')
    monkeypatch.setenv('PXG_PARALLEL_MIN', '2')
    assert render_pool.run(jobs, _name_and_payload, '?') == single


def test_labelled_job_survives_pickling():
    """Без охраны ``__getattr__`` разбор при передаче процессу уходил в бесконечную рекурсию (``_job`` ещё нет)."""
    job = chart_labels.LabelledJob(FigureJob('Отбор · 31', None, {}, module='production'), {'title': 'x'})
    copy = pickle.loads(pickle.dumps(job))
    assert copy.name == 'Отбор · 31' and copy.module == 'production'

# --- общие расчёты «Поскважинного анализа» ---------------------------------------------------------------------------

def old_seasons(d, all_data):
    """Сезонная таблица до ускорения: база объекта и группы отбирается по всей таблице для каждой скважины и периода."""
    rows = []
    for period, g in d.groupby('period', sort=False):
        base = all_data[all_data.kind.eq(g.kind.iloc[0]) & all_data.period.eq(period)]
        dates = base.loc[base.gas_volume_m3.notna(), 'date'].drop_duplicates()
        group = base.loc[base.group.eq(g.group.iloc[0]), 'gas_volume_m3'].sum(min_count=1)
        obj = base.gas_volume_m3.sum(min_count=1)
        volume = g.gas_volume_m3.sum(min_count=1)
        rows.append({'period': period, 'object_days': len(dates), 'obj': obj, 'group': group,
                     'group_share': volume / group * 100 if group > 0 else np.nan})
    return pd.DataFrame(rows)


def test_shared_season_base_matches_per_well_selection():
    frames = {'production': production.periods(demo_frames()['production'], 11, 4)}
    settings = {'season_start': 11, 'season_end': 4}
    wells = sorted(frames['production'].well.unique())[:4]
    mapping = {w: {'group': 'ГСП 2' if i % 2 else 'ГСП 1'} for i, w in enumerate(wells)}
    context = well_analysis.dataset(frames, settings, mapping)['daily']
    for well in wells:
        for kind in ('withdrawal', 'injection'):
            result = well_analysis.analyze(frames, settings, mapping, well, kind)
            if result['daily'].empty:
                continue
            old = old_seasons(result['daily'], context)
            new = result['seasons'].set_index('period').loc[old.period]
            np.testing.assert_allclose(new.object_days.to_numpy(float), old.object_days.to_numpy(float))
            np.testing.assert_allclose(new.group_share.to_numpy(float), old.group_share.to_numpy(float), equal_nan=True)
            entry = [well_analysis.season_base(context, kind, p) for p in old.period]
            np.testing.assert_allclose([e[2] for e in entry], old.obj.to_numpy(float), equal_nan=True)


def test_until_is_shared_between_wells():
    frame = well_analysis.dataset({'production': production.periods(demo_frames()['production'], 11, 4)}, {}, {})['daily']
    cutoff = frame.date.median()
    assert well_analysis.until(frame, cutoff) is well_analysis.until(frame, cutoff)
    pd.testing.assert_frame_equal(well_analysis.until(frame, cutoff), frame[frame.date.le(cutoff)])
    assert well_analysis.until(frame, None) is frame