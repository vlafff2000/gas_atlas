"""Предельный расход при предельной депрессии: падает вместе с Рпл, согласуется с депрессией из passport_depression."""
import pytest

from atlas import limit_flow as lf, passport_depression as pdp


def test_flow_at_limit_gives_exactly_the_limit_depression():
    q = lf.q_at_limit(100.0, 0.5, 0.002, 4.1)
    assert round(pdp.depression(100.0, 0.5, 0.002, q), 6) == 4.1


def test_flow_falls_with_reservoir_pressure():
    qs = [lf.q_at_limit(p, 0.5, 0.002, 4.1) for p in (100, 90, 80, 70)]
    assert qs == sorted(qs, reverse=True) and qs[0] > qs[-1]


def test_linear_case_and_no_solution():
    assert lf.q_at_limit(100.0, 2.0, 0.0, 5.0) == (2 * 100 * 5 - 25) / 2.0
    assert lf.q_at_limit(100.0, 0.0, 0.0, 5.0) is None
    assert lf.q_at_limit(100.0, 1.0, 0.1, None) is None
    assert lf.q_at_limit(0.0, 1.0, 0.1, 5.0) is None


def test_depression_cannot_exceed_pressure():
    assert lf.q_at_limit(3.0, 1.0, 0.1, 10.0) == lf.q_at_limit(3.0, 1.0, 0.1, 3.0)


def test_grid_and_manual_limit_wins():
    assert lf.pressure_grid(120, 10, 4) == [120, 110, 100, 90] and lf.pressure_grid(15, 10, 4) == [15, 5]
    assert lf.parse_limits('523=0,73; 527 = 0.918\nплохо') == {'523': 0.73, '527': 0.918}
    assert lf.pick_limit('523', {'523': 0.73}, 4.1, 'расширка') == (0.73, 'задан вручную')
    assert lf.pick_limit('1', {}, 4.1, 'расширка') == (4.1, 'по конструкции: расширка')
    assert lf.pick_limit('1', {}, None) == (None, 'предел не задан')


def test_rough_mark_outside_gdi_range():
    row = lf.flow_row(0.5, 0.002, 4.1, [100.0, 60.0], 100.0, q_max_gdi=lf.q_at_limit(100.0, 0.5, 0.002, 4.1) / 1.5)
    assert row['rough'] == [100.0, 60.0] or 100.0 in row['rough']
