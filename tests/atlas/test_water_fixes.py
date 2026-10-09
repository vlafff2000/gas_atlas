"""Водный фактор: газ сравнивается с водой тех же суток; приставки в таблице «вынос воды по объекту»."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.engine.core.loader import load_file
from atlas.modules.water import WaterModule, season_frame


def write(tmp_path, header):
    path = tmp_path / 'wf.csv'
    path.write_text(f'Дата;Накопленный расход газа, {header[0]};Накопленная вода, {header[1]};Объем газа в пласте, {header[0]}\n'
                    f'2024-11-01;1000;10;5000000\n2024-11-02;2000;30;4999000\n', encoding='utf-8')
    return path


@pytest.mark.parametrize('gas_unit,expected', [('млн м³', 1000.0), ('тыс. м³', 1.0), ('млрд м³', 1_000_000.0), ('м³', 0.001)])
def test_water_factor_table_prefixes(tmp_path, gas_unit, expected):
    r = load_file(write(tmp_path, (gas_unit, 'м³')), 'water_factor', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    frame = r.frames['water_factor']
    assert frame.gas_cum.iloc[0] == pytest.approx(expected)                  # хранится в млн м³
    assert frame.water_cum.iloc[1] == pytest.approx(30.0)


def test_water_factor_table_water_in_thousand_m3(tmp_path):
    r = load_file(write(tmp_path, ('млн м³', 'тыс. м³')), 'water_factor', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert r.frames['water_factor'].water_cum.tolist() == pytest.approx([10_000.0, 30_000.0])    # хранится в м³


def balance(days=30, gas=1.0e6):
    index = pd.date_range('2024-11-01', periods=days)
    return pd.DataFrame({'withdrawal': gas, 'v': 1000.0}, index=index), pd.Series('2024-2025', index=index)


def test_cumulative_factor_uses_gas_of_measured_days_only():
    """30 суток по 1 млн м³, вода 5 м³ замерена один раз: 5 л/тыс. м³, а не 0,17."""
    bal, seasons = balance()
    f = season_frame(bal, seasons, pd.Series([5.0], index=[pd.Timestamp('2024-11-10')]), '2024-2025')
    assert f.cumulative.dropna().iloc[-1] == pytest.approx(5.0)
    assert f.cum_gas.iloc[-1] == pytest.approx(30e6)
    assert np.isnan(f.cumulative.iloc[0])


def test_cumulative_factor_is_unchanged_when_water_is_measured_every_day():
    bal, seasons = balance(10)
    f = season_frame(bal, seasons, pd.Series(2.0, index=bal.index), '2024-2025')
    assert f.cumulative.iloc[-1] == pytest.approx(2.0)


def test_season_table_factor_matches_measured_gas():
    bal, seasons = balance()
    water = pd.Series([5.0, 15.0], index=[pd.Timestamp('2024-11-10'), pd.Timestamp('2024-11-20')])
    row = WaterModule.table({'2024-2025': season_frame(bal, seasons, water, '2024-2025')}).frame.iloc[0]
    assert row['gas'] == pytest.approx(30.0) and row['gas_measured'] == pytest.approx(2.0)
    assert row['factor'] == pytest.approx(10.0)          # 20 м³ / 2 млн м³
