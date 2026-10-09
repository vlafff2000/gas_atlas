"""Статистические сигналы: смена состава группы, изменение a и b по малому числу точек, разброс ошибки сверки."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.engine.modules import pressure_match, well_analysis
from atlas.modules import gdi_trend


def daily(group_wells_last, share_first=25.0, share_last=19.7, volume_first=1000.0, volume_last=770.0):
    """Скважина 7: 40 суток отбора; в последних 14 суток доля в группе упала, а в группе стало больше скважин."""
    dates = pd.date_range('2025-01-01', periods=40)
    first_days = dates < dates[0] + pd.Timedelta(days=14)
    last_days = dates > dates[-1] - pd.Timedelta(days=14)
    volume = np.where(first_days, volume_first, np.where(last_days, volume_last, 900.0)) * 1000
    share = np.where(first_days, share_first, np.where(last_days, share_last, 22.0))
    wells = np.where(last_days, group_wells_last, 4)
    return pd.DataFrame({'date': dates, 'period': '2024-2025', 'gas_volume_m3': volume, 'share_group': share, 'work_hours': 24.0,
                         'active': True, 'group_wells': wells})


def signal_text(d):
    empty = pd.DataFrame()
    s = well_analysis.signals(d, pd.DataFrame(columns=['coverage']), empty, empty, empty, empty, threshold=10)
    return ' '.join(s[s['Раздел'] == 'Эксплуатация']['Вывод'])


def test_deterioration_signal_requires_stable_group_composition():
    assert 'Косвенный сигнал относительного ухудшения' in signal_text(daily(group_wells_last=4))
    text = signal_text(daily(group_wells_last=5))
    assert 'Косвенный сигнал' not in text
    assert 'Число работающих скважин группы изменилось (4 → 5)' in text


def test_signal_unchanged_without_group_composition_column():
    d = daily(group_wells_last=5).drop(columns='group_wells')
    assert 'Косвенный сигнал относительного ухудшения' in signal_text(d)


def history(fit_first, fit_last):
    return pd.DataFrame({'well': ['7', '7'], 'method': ['', ''], 'date': pd.to_datetime(['2023-01-01', '2024-01-01']),
                         'reliable': [True, True], 'q_reference': [100.0, 80.0], 'a': [1.0, 1.3], 'b': [0.01, 0.012],
                         'reference_dp2': [500.0, 500.0], 'fit_points': [fit_first, fit_last]})


def test_a_and_b_change_hidden_for_few_fit_points():
    few = gdi_trend.rating(history(3, 4), 10).iloc[0]
    assert np.isnan(few.a_change) and np.isnan(few.b_change)
    assert few.change == pytest.approx(-20.0) and few.fit_first == 3 and few.fit_last == 4      # расход по-прежнему
    enough = gdi_trend.rating(history(5, 6), 10).iloc[0]
    assert enough.a_change == pytest.approx(30.0) and enough.b_change == pytest.approx(20.0)


def test_signed_error_spread_uses_n_minus_one():
    d = pd.DataFrame({'error': np.abs([2.0, -2.0, 2.0, -2.0]), 'signed_error': [2.0, -2.0, 2.0, -2.0],
                      'relative_error': [1.0] * 4, 'valid_threshold': [True] * 4, 'within': [True, True, False, False]})
    stats = pressure_match.statistics(d)
    assert stats['Стандартное отклонение'] == pytest.approx(0.0)           # прежнее: по модулю ошибки, ddof=0
    assert stats['Разброс ошибки (σ, со знаком, n−1)'] == pytest.approx(np.std([2, -2, 2, -2], ddof=1))
