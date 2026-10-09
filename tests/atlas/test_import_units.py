"""Единицы при импорте: заголовок колонки главнее выбора по умолчанию, МПа пересчитываются везде, смешение единиц видно."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.engine.core.import_rules import PSI_TO_KGF, to_kgf
from atlas.engine.core.loader import load_file, pressure_factor, rate_unit, volume_factor
from atlas.quality import units


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


def test_rate_unit_prefixes_and_unknown_fallback():
    assert rate_unit('Q, млн м³/сут', 'м³/сут') == 'млн м³/сут'
    assert rate_unit('Q, тыс. м3/сут', 'м³/сут') == 'тыс. м³/сут'
    assert rate_unit('Q, м³/сут', 'тыс. м³/сут') == 'м³/сут'
    assert rate_unit('Q', 'тыс. м³/сут') == 'тыс. м³/сут'
    assert volume_factor('Накопленный, млн м³') == 10 ** 6 and volume_factor('Объём, тыс. м³') == 1000 and volume_factor('Объём') == 1


def test_pressure_factor_from_header():
    assert pressure_factor('Рпл, МПа') == pytest.approx(PSI_TO_KGF)
    assert pressure_factor('Рзаб (МПа)') == pytest.approx(PSI_TO_KGF)
    assert pressure_factor('Рпл, кгс/см²') is None
    assert pressure_factor('Рпл, бар') == pytest.approx(1.0197162129779)
    assert pressure_factor('Рпл, кПа') is None


def test_production_million_m3_header_is_not_read_as_m3(tmp_path):
    path = write(tmp_path, 'prod.csv', 'Дата;Скважина;Q, млн м³/сут\n2024-01-01;7;1,5\n2024-01-02;7;1,25\n')
    r = load_file(path, 'production', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    q = r.frames['production'].q.tolist()
    assert q == pytest.approx([1.5e6, 1.25e6])
    assert any('Единица расхода взята из заголовка' in i['Причина'] for i in r.issues)


def test_gdi_mpa_header_converts_without_user_choice_and_million_q(tmp_path):
    path = write(tmp_path, 'gdi.csv', 'Скважина;Дата;Q, млн м³/сут;Рпл, МПа;Рзаб, МПа\n7;2024-03-01;0,25;7,5;6,5\n')
    r = load_file(path, 'gdi', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    g = r.frames['gdi']
    assert g.q.iloc[0] == pytest.approx(250.0)                       # тыс. м³/сут
    assert g.p_res.iloc[0] == pytest.approx(7.5 * PSI_TO_KGF)
    assert g.p_bh.iloc[0] == pytest.approx(6.5 * PSI_TO_KGF)
    assert g.dp2.iloc[0] == pytest.approx((7.5 ** 2 - 6.5 ** 2) * PSI_TO_KGF ** 2)
    assert r.by_header['gdi'] >= {'p_res', 'p_bh'}


def test_header_conversion_is_not_repeated_when_user_also_chose_mpa(tmp_path):
    path = write(tmp_path, 'gdi.csv', 'Скважина;Дата;Q;Рпл, МПа;Рзаб\n7;2024-03-01;250;7,5;6,5\n')
    r = load_file(path, 'gdi', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    to_kgf(r.frames, skip=r.by_header)           # пользователь выбрал «МПа»: колонка с единицей в заголовке уже пересчитана
    g = r.frames['gdi']
    assert g.p_res.iloc[0] == pytest.approx(7.5 * PSI_TO_KGF)          # один раз
    assert g.p_bh.iloc[0] == pytest.approx(6.5 * PSI_TO_KGF)           # колонка без единицы пересчитана выбором пользователя


def test_to_kgf_converts_pressure_book():
    frames = {'pressure_match': pd.DataFrame({'fact': [10.0, np.nan], 'model': [11.0, 12.0]})}
    to_kgf(frames)
    out = frames['pressure_match']
    assert out.fact.iloc[0] == pytest.approx(10 * PSI_TO_KGF) and out.model.tolist() == pytest.approx([11 * PSI_TO_KGF, 12 * PSI_TO_KGF])


def test_units_check_sees_mpa_file_inside_kgf_set():
    gdi = pd.DataFrame({'file': ['a.xlsx'] * 3 + ['b.xlsx'] * 3, 'p_res': [100.0, 102.0, 104.0, 10.1, 10.2, 10.3]})
    out = units({'gdi': gdi})
    assert len(out) == 1 and 'b.xlsx' in out[0].details.iloc[0] and len(out[0]) == 1
    assert units({'gdi': gdi[gdi.file == 'a.xlsx']}) == []


@pytest.mark.parametrize('header,value,expected', [('План, м³', '150000000', 150.0), ('План, тыс. м³', '150000', 150.0),
                                                    ('План, млн м³', '150', 150.0), ('План, млрд м³', '0,15', 150.0)])
def test_plan_units_by_prefix(tmp_path, header, value, expected):
    path = write(tmp_path, 'plan.csv', f'Группа;Дата;{header}\nГСП 2;2024-01-01;{value}\n')
    r = load_file(path, 'plan', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert r.frames['plan'].plan_volume.iloc[0] == pytest.approx(expected)
