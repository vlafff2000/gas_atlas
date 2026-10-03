"""Ускорения открытия проекта и поскважинного анализа не меняют расчёты: новое сравнивается со старой реализацией."""
import numpy as np
import pandas as pd
import pytest

from app.core import exclusions, performance
from app.core.demo import demo_frames
from app.modules import production, well_analysis


def old_periods(df, start=11, end=4):
    """Сезоны 5.8 до ускорения (построчно, строковые операции над всей колонкой)."""
    d = df.copy(); year = d.date.dt.year; month = d.date.dt.month
    if start > end:
        y = np.where(month.ge(start), year, year - 1)
        derived = pd.Series(y, index=d.index).astype(str) + '-' + pd.Series(y + 1, index=d.index).astype(str)
        derived = derived.where(month.ge(start) | month.le(end), 'Вне сезона ' + year.astype(str))
    else:
        derived = year.astype(str).where(month.between(start, end), 'Вне сезона ' + year.astype(str))
    season = d.get('season', pd.Series('', index=d.index)).fillna('').astype(str).str.replace(r'[–—]', '-', regex=True).str.replace(r'\s', '', regex=True)
    supplied = d.get('year', pd.Series('', index=d.index)).fillna('').astype(str).str.replace(r'\.0$', '', regex=True)
    inj = supplied.where(supplied.str.fullmatch(r'\d{4}'), year.astype(str))
    d['period'] = np.where(d.kind.eq('injection'), inj, season.where(season.ne(''), derived))
    return d


def old_identify(df, module):
    d = df.copy()
    values = pd.DataFrame(index=d.index)
    for field in exclusions.KEYS[module]:
        if field == 'date': values[field] = pd.to_datetime(d[field]).astype('datetime64[ns]')
        elif field in ('q', 'dp2', 'top_m', 'bottom_m', 'diameter_mm'): values[field] = pd.to_numeric(d[field], errors='coerce').astype(float) if field in d else np.nan
        else: values[field] = d[field].fillna('').astype(str) if field in d else ''
    hashed = pd.util.hash_pandas_object(values, index=False)
    if module == 'gdi':
        values['_occurrence'] = hashed.groupby(hashed).cumcount()
        hashed = pd.util.hash_pandas_object(values, index=False)
    d['_point_id'] = module + ':' + hashed.astype(str)
    return d


def messy_production(n=4000, seed=3):
    rng = np.random.default_rng(seed)
    dates = pd.Timestamp('2019-01-01') + pd.to_timedelta(rng.integers(0, 365 * 5, n), unit='D')
    return pd.DataFrame({
        'well': rng.choice(['1', '2', '31', '132'], n), 'date': dates, 'q': rng.normal(50000, 9000, n),
        'kind': rng.choice(['withdrawal', 'injection'], n),
        'season': rng.choice(['', '2020–2021', '2020 - 2021', None, '2021—2022', 'Лето'], n),
        'year': rng.choice(['', '2020', '2021.0', None, 'abcd'], n), 'group': 'Г', 'subgroup': '',
        'file': 'f', 'sheet': 's', '_row': np.arange(n)})


@pytest.mark.parametrize('rule', [(11, 4), (10, 3), (4, 11), (1, 12)])
def test_periods_match_old_implementation(rule):
    frame = messy_production()
    pd.testing.assert_frame_equal(production.periods(frame, *rule), old_periods(frame, *rule))


def test_periods_on_demo_and_without_optional_columns():
    frame = demo_frames()['production']
    pd.testing.assert_frame_equal(production.periods(frame), old_periods(frame))
    bare = messy_production().drop(columns=['season', 'year'])
    pd.testing.assert_frame_equal(production.periods(bare), old_periods(bare))
    assert production.periods(frame.iloc[0:0]).period.dtype == object


@pytest.mark.parametrize('module', ['production', 'gdi', 'response'])
def test_identify_matches_old_implementation(module):
    frame = demo_frames()[module]
    pd.testing.assert_frame_equal(exclusions.identify(frame, module), old_identify(frame, module))
    pd.testing.assert_frame_equal(exclusions.identify(frame, module, copy=False), old_identify(frame, module))


def test_identify_copy_false_does_not_touch_a_shared_frame():
    frame = demo_frames()['response']
    exclusions.identify(frame, 'response')
    assert '_point_id' not in frame


def test_memory_estimate_is_close_to_deep_count():
    frame = old_identify(messy_production(60000), 'production')
    deep = int(frame.memory_usage(index=True, deep=True).sum())
    assert abs(performance.memory_bytes(frame) - deep) / deep < 0.05
    small = frame.iloc[:100]
    assert performance.memory_bytes(small) == int(small.memory_usage(index=True, deep=True).sum())


def test_daily_without_operations_is_identical_to_outer_merge():
    frames = {'production': production.periods(old_identify(demo_frames()['production'], 'production'))}
    mapping = {'31': {'group': 'ГСП 2'}}
    settings = {'season_start': 11, 'season_end': 4}
    fast = well_analysis._daily(frames, settings, mapping)
    keys = ['well', 'date', 'kind']
    plain = well_analysis.plain(frames['production'])
    p = production.periods(plain, 11, 4)[keys + ['q', 'period']].rename(columns={'q': 'daily_q', 'period': 'prod_period'})
    ops = pd.DataFrame(columns=keys + ['ops_period'])
    # прежний путь: внешнее слияние с пустой таблицей операций
    merged = p.merge(ops, on=keys, how='outer', validate='one_to_one')
    assert len(fast) == len(merged)
    assert fast.prod_period.tolist() == merged.sort_values(['kind', 'well', 'date']).prod_period.tolist()
    assert fast.ops_period.isna().all() and fast.ops_period.dtype == object
    assert fast.group.isin(['ГСП 2', 'Без группы']).all()


def test_compact_strings_keeps_dtype_values_and_gaps():
    frame = old_identify(messy_production(30000), 'production')
    before = frame.copy()
    after = performance.compact_strings(frame)
    pd.testing.assert_frame_equal(after, before)       # None в строковых колонках становится NaN: для pandas это один пропуск
    assert all(after[c].dtype == before[c].dtype for c in before.columns)
    assert after.well.map(id).nunique() <= 4 and after._point_id.map(id).nunique() == after._point_id.nunique()   # общие объекты на значение
    small = messy_production(100)
    assert performance.compact_strings(small) is small
