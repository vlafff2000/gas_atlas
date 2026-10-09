"""Таблица «вынос воды по объекту»: приставки «тыс.», «млн», «млрд» в заголовках колонок."""
from __future__ import annotations

import pytest

from atlas.engine.core.loader import load_file


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
