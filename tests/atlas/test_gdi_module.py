"""Паритет с 5.8: раздел ГДИ возвращает ровно то, что считает и рисует app.modules.gdi / charts.gdi_chart."""
import numpy as np
import pandas as pd
import pytest

from app.core import exclusions
from app.core.demo import demo_frames
from app.modules import charts
from app.modules import gdi as legacy
from atlas import registry
from atlas.contract import Data, Result
from atlas.domain import DatasetKind
from atlas.modules.gdi import select

GDI = DatasetKind.GDI


@pytest.fixture(scope='module')
def frame():
    d = demo_frames()['gdi']
    # Шум, чтобы подбор не был тривиальным; у одной скважины два метода в одну дату; один явный выброс.
    rng = np.random.default_rng(7)
    d['dp2'] = d.dp2 * (1 + rng.normal(0, .03, len(d)))
    extra = d[d.well.eq('31') & d.date.eq(d.date.max())].copy()
    extra['method'] = 'Изохронный'; extra['dp2'] *= 1.1
    d = pd.concat([d, extra], ignore_index=True)
    d.loc[(d.well == '45') & (d.date == d.date.max()) & (d.q == 140.), 'dp2'] *= 1.6
    return exclusions.identify(d, 'gdi')


def run(frame, excluded=None, **params):
    module = registry.get('gdi')
    raw = frame
    prepared = exclusions.apply({'gdi': raw}, {'excluded_points': excluded or {}})['gdi']
    return module.run(Data({GDI: prepared}, {GDI: raw}, excluded or {}), module.spec.coerce(params))


def table(result, tid):
    return next(t for t in result.tables if t.id == tid)


@pytest.mark.parametrize('last_n', [0, 1, 2, 3])
def test_selection_matches_legacy(frame, last_n):
    wells = ['31', '45', '540']
    order = ['well', 'date', 'method', 'q']
    ours = select(frame, wells, [], last_n).sort_values(order).reset_index(drop=True)
    theirs = legacy.select_studies(frame, wells, last_n).sort_values(order).reset_index(drop=True)
    pd.testing.assert_frame_equal(ours, theirs, check_dtype=False)
    seasons = ['2024-2025']
    ours = select(frame, wells, seasons, last_n).sort_values(order).reset_index(drop=True)
    theirs = legacy.select_studies(frame, wells, last_n, seasons).sort_values(order).reset_index(drop=True)
    pd.testing.assert_frame_equal(ours, theirs, check_dtype=False)


@pytest.mark.parametrize('last_n', [0, 1, 3])
def test_coefficients_bit_identical(frame, last_n):
    ours = table(run(frame, last_n=last_n, threshold=.97), 'studies').frame
    theirs = legacy.analyze(legacy.select_studies(frame, sorted(frame.well.unique()), last_n), .97)
    key = ['well', 'date', 'method', 'study']
    ours = ours.sort_values(key).reset_index(drop=True); theirs = theirs.sort_values(key).reset_index(drop=True)
    assert len(ours) == len(theirs) > 0
    for column in ('a', 'b', 'r2', 'a_calc', 'b_calc', 'r2_calc', 'a_db', 'b_db', 'r2_db', 'q_free', 'q_observed', 'p_res',
                   'points', 'fit_points'):
        assert np.array_equal(ours[column].to_numpy(float), theirs[column].to_numpy(float), equal_nan=True), column
    assert ours.source.tolist() == theirs.source.tolist()
    assert ours.note.tolist() == theirs.note.tolist()


def test_comparisons_match_legacy(frame):
    result = run(frame, last_n=3)
    chosen = legacy.select_studies(frame, sorted(frame.well.unique()), 3)
    ours = table(result, 'comparison').frame.rename(columns={'well': 'Скважина'})
    theirs = legacy.comparisons(chosen)
    key = ['Скважина', 'Метод', 'Исследование']
    pd.testing.assert_frame_equal(ours.sort_values(key).reset_index(drop=True)[theirs.columns],
                                  theirs.sort_values(key).reset_index(drop=True))
    ours3 = table(result, 'compare_three').frame.rename(columns={'well': 'Скважина'})
    theirs3 = legacy.compare_three(chosen)
    pd.testing.assert_frame_equal(ours3.sort_values(key).reset_index(drop=True)[theirs3.columns],
                                  theirs3.sort_values(key).reset_index(drop=True))
    assert table(result, 'compare_three').collapsed


def test_comparison_uses_selected_dates_like_58(frame):
    # В 5.8 сравнение строится по выбранным датам: при одной дате сравнивать не с чем.
    assert table(run(frame, last_n=1), 'comparison').frame.empty


def test_outliers_match_legacy_and_are_confirmable(frame):
    result = run(frame, last_n=1, outliers=True, outlier_threshold=15)
    found = table(result, 'outliers')
    theirs = legacy.outlier_suggestions(legacy.select_studies(frame, sorted(frame.well.unique()), 1), 15)
    assert sorted(found.frame.id) == sorted(theirs.id) and len(theirs) >= 1
    assert found.action.id_column == 'id' and found.action.reason == 'Подсказка выброса подтверждена инженером'
    assert all(t.id != 'outliers' for t in run(frame, last_n=1).tables)


def test_chart_matches_58_figure(frame):
    params = dict(wells=['31'], last_n=3)
    chart = run(frame, **params).charts[0]
    chosen = legacy.select_studies(frame, ['31'], 3)
    fig = charts.gdi_chart(chosen, '31', .95, 'standard', True, True, True, raw_df=chosen, show_excluded=True)
    old_points = [t for t in fig.data if t.mode == 'markers']
    new_points = [s for s in chart.series if s.kind == 'points']
    assert len(old_points) == len(new_points) == 4          # три даты + второй метод последней даты
    for old, new in zip(old_points, new_points):
        assert old.marker.color == new.color
        assert np.array_equal(np.asarray(old.x, float), np.asarray(new.x, float))
        assert np.array_equal(np.asarray(old.y, float), np.asarray(new.y, float))
    assert len([t for t in fig.data if t.mode == 'lines']) == len([s for s in chart.series if s.kind == 'line'])
    latest = chosen.date.max().strftime('%d.%m.%Y')
    assert {s.color for s in new_points if s.name.startswith(latest)} == {'#dc3545'}   # последняя дата — красная
    assert chart.crosshair is True


def test_view_toggles(frame):
    chart = run(frame, wells=['31'], curves=False, db_curves=False, orientation='swapped', crosshair=False).charts[0]
    assert all(s.kind == 'points' for s in chart.series)
    assert chart.x.label == 'ΔP²' and chart.crosshair is False
    only_db = run(frame, wells=['31'], curves=False).charts[0]
    assert all(s.dashed for s in only_db.series if s.kind == 'line')


def test_exclusion_changes_fit_and_shows_hollow_point(frame):
    target = frame[(frame.well == '45') & (frame.date == frame.date.max())].iloc[2]
    excluded = {target['_point_id']: {'id': target['_point_id'], 'module': 'gdi', 'reason': 'тест'}}
    before = table(run(frame, wells=['45'], last_n=1), 'studies').frame.iloc[0]
    result = run(frame, excluded, wells=['45'], last_n=1)
    after = table(result, 'studies').frame.iloc[0]
    assert after.fit_points == before.fit_points - 1
    gray = [s for s in result.charts[0].series if s.hollow]
    assert len(gray) == 1 and len(gray[0].x) == 1
    assert not [s for s in run(frame, excluded, wells=['45'], last_n=1, show_excluded=False).charts[0].series if s.hollow]
    points = table(result, 'points')
    row = points.frame[points.frame['_point_id'] == target['_point_id']].iloc[0]
    assert bool(row['_excluded']) and row['_reason'] == 'тест'
    assert points.action.checked_column == '_excluded' and points.collapsed


def test_empty_selection_is_a_note_not_an_error(frame):
    result = run(frame, seasons=['1999-2000'])
    assert isinstance(result, Result) and not result.charts and result.notes[0].level == 'warning'


def test_state_roundtrip_in_58_format(frame):
    module = registry.get('gdi')
    params = module.spec.coerce({'wells': ['31'], 'last_n': 2, 'orientation': 'swapped', 'crosshair': False})
    state = module.save_state(params, Data({GDI: frame}))
    assert state['wells'] == ['31'] and state['n'] == 2 and state['orientation'] == 'swapped'
    assert {**module.spec.coerce(module.load_state(state)), 'threshold': params['threshold']} == params
    everything = module.save_state(module.spec.coerce({}), Data({GDI: frame}))
    assert everything['wells'] == ['31', '45', '70', '73', '89', '132', '540', '541']
