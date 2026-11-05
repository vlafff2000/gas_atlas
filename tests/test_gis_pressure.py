"""Давление ГИС, приведённое к −670 м а.о.: две ближайшие по глубине точки, плотность жидкости, причина в тексте, ручное исключение."""
import pandas as pd
import pytest

from atlas.modules._gis_pressure import reduce_pressure

DATE = pd.Timestamp('2024-03-30')
GEO = pd.DataFrame({'well': ['5'], 'altitude': [110.0]})       # MD 780 м = −670 м а.о.


def _thermo(rows, well='5'):
    return pd.DataFrame({'well': well, 'date': DATE, 'depth_m': [r[0] for r in rows], 'pressure_kgs': [r[1] for r in rows]})


def _one(thermo, filling=None, geo=GEO, **kw):
    out = reduce_pressure(thermo, filling, geo, **kw)
    assert len(out) == 1
    return out.iloc[0]


def test_example_from_engineer_740_and_800_md_gives_mid_trend_at_780():
    r = _one(_thermo([(740, 70.0), (800, 76.0)]))
    assert r.pressure == pytest.approx(74.0) and r.method == 'интерполяция' and r.check == ''
    assert '740,0 м MD' in r.reason and '800,0 м MD' in r.reason and '-670,0 м а.о.' in r.reason


def test_two_nearest_points_are_used_not_the_whole_profile():
    r = _one(_thermo([(100, 20.0), (740, 70.0), (800, 76.0), (900, 99.0)]))
    assert r.pressure == pytest.approx(74.0)


def test_surface_zero_pressure_row_is_ignored():
    r = _one(_thermo([(0, 0.0), (740, 70.0), (800, 76.0)]))
    assert r.pressure == pytest.approx(74.0)


def test_measurement_at_reduction_depth_is_taken_as_is():
    r = _one(_thermo([(779, 73.9), (900, 90.0)]))
    assert r.pressure == pytest.approx(73.9) and r.method == 'замер на глубине приведения'


def test_liquid_density_from_filling_table_replaces_linear_trend_and_says_so():
    filling = pd.DataFrame({'well': ['5'], 'date': [DATE], 'from_m': [700.0], 'to_m': [850.0], 'density_min': [1.0], 'density_max': [1.2], 'fill': ['вода']})
    r = _one(_thermo([(740, 70.0), (800, 76.0)]), filling)
    # ближайшая — 800 м MD (−690 а.о., 20 м от цели): 76 + 1,1/10 · (−690 + 670) = 73,8; линейно было бы 74,0
    assert r.pressure == pytest.approx(73.8) and r.method == 'по плотности жидкости' and 'линейно было бы 74,0' in r.reason


def test_gas_filling_without_density_keeps_linear_value():
    filling = pd.DataFrame({'well': ['5'], 'date': [DATE], 'from_m': [700.0], 'to_m': [850.0], 'fill': ['газ']})
    assert _one(_thermo([(740, 70.0), (800, 76.0)]), filling).method == 'интерполяция'


def test_extrapolation_flagged_and_limited_by_distance():
    r = _one(_thermo([(700, 60.0), (740, 64.0)]))      # обе выше глубины приведения
    assert r.method == 'продолжение тренда' and r.pressure == pytest.approx(68.0) and 'продолжение' in r.check
    far = _one(_thermo([(300, 30.0), (400, 40.0)]))
    assert pd.isna(far.pressure) and far.method == 'нет значения' and 'дальше' in far.reason


def test_single_point_without_density_gives_reason_not_a_number():
    r = _one(_thermo([(740, 70.0)]))
    assert pd.isna(r.pressure) and 'один замер' in r.reason


def test_pressure_falling_with_depth_is_marked_for_check():
    assert 'падает с глубиной' in _one(_thermo([(740, 76.0), (800, 70.0)])).check


def test_report_depth_ao_is_used_without_altitude_and_disagreement_is_flagged():
    thermo = _thermo([(740, 70.0), (800, 76.0)]).assign(depth_abs_m=[-630.0, -690.0])
    assert _one(thermo, geo=None).pressure == pytest.approx(74.0)
    clash = thermo.assign(depth_abs_m=[-600.0, -660.0])        # альтитуда проекта даёт −630/−690: расхождение 30 м
    assert 'расходится с альтитудой проекта' in _one(clash).check


def test_no_altitude_and_no_report_depth_means_no_row():
    assert reduce_pressure(_thermo([(740, 70.0), (800, 76.0)]), None, None).empty


def test_other_depth_of_reduction_and_wells_filter():
    t = pd.concat([_thermo([(740, 70.0), (800, 76.0)]), _thermo([(740, 1.0), (800, 2.0)], well='9')])
    out = reduce_pressure(t, None, pd.DataFrame({'well': ['5', '9'], 'altitude': [110.0, 110.0]}), target=-630.0, wells=['5'])
    assert out.well.tolist() == ['5'] and out.pressure[0] == pytest.approx(70.0)
