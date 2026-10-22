"""Замеры воды за месяц (старый формат Карт ГСП) → таблица ``water``."""
import io

import pandas as pd
import pytest

from atlas.engine.core import config, tabular, water_monthly_import as wm
from atlas.imports import Imports, base_book
from atlas.projects import Projects


def xlsx(rows, header=False):
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False, header=header)
    return buf.getvalue()


SHEET = [[500, '1,2/0,5', 1200, 0.8], [501, 'нет воды', 900, None], [502, 'песок в ремонт', None, None]]


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path / 'storage')
    projects = Projects(tmp_path / 'storage')
    return projects, Imports(projects), projects.store.create('Тест')


def test_month_comes_from_name_or_numeric_stamp_and_production_stays_out():
    assert wm.month_year('Вынос воды ноябрь 2022.xlsx', []) == (11, 2022)
    assert wm.month_year('Замеры_воды_2022_11.xlsx', []) == (11, 2022)
    assert wm.month_year('БД_замеров_воды.xlsx', []) is None
    tables = tabular.read_content(xlsx([[500, '2025-05-01', 3.2], [501, '2025-05-02', 1.1]]), '2025_05_вода.xlsx', 31)[1]
    assert not wm.looks_like(tables, '2025_05_вода.xlsx')
    assert not wm.looks_like(tabular.read_content(xlsx(SHEET), 'Учёт газа 2022_11.xlsx', 31)[1], 'Учёт газа 2022_11.xlsx')


def test_build_keeps_gaps_as_gaps_and_flags_water():
    out, warn = wm.build('Вынос воды ноябрь 2022.xlsx', xlsx(SHEET))
    rows = out.set_index('well')
    assert rows.loc['500', 'water_factor_l'] == 1.2 and rows.loc['500', 'water_rate'] == 0.8 and rows.loc['500', 'water_flag'] == 'Да'
    assert rows.loc['501', 'water_flag'] == 'Нет' and rows.loc['501', 'water_rate'] == 0
    assert pd.isna(rows.loc['502', 'water_factor_l']) and rows.loc['502', 'water_flag'] == 'Неизвестно'
    assert set(out['date']) == {pd.Timestamp(2022, 11, 1)} and warn == []


def test_header_variant_with_water_factor_and_flow_columns():
    out, _ = wm.build('Замеры_воды_2022_11.xlsx', xlsx([['Скважина', 'ВФ (л/м³)', 'Расход газа', 'Расход воды л/ч'], [500, 0.5, 1200, 0.8]]))
    assert out.loc[0, 'water_factor_l'] == 0.5 and out.loc[0, 'water_rate'] == 0.8


def test_loading_replaces_the_same_well_and_month_and_keeps_the_rest(project):
    projects, imports, pid = project
    imports.water_monthly_load(pid, 'Вынос воды ноябрь 2022.xlsx', xlsx(SHEET), 'new')
    imports.water_monthly_load(pid, 'Вынос воды декабрь 2022.xlsx', xlsx([[500, '2,0/0,5', 1000, 0.5]]), 'new')
    imports.water_monthly_load(pid, 'Вынос воды ноябрь 2022.xlsx', xlsx([[500, '3,0/0,5', 1000, 1.5]]), 'new')
    _, data = projects.store.load(pid)
    water = data['water'].set_index(['well', 'date'])
    assert len(water) == 4                                   # 501 и 502 за ноябрь, 500 за ноябрь (новое) и декабрь
    assert water.loc[('500', pd.Timestamp(2022, 11, 1)), 'water_factor_l'] == 3.0
    assert water.loc[('500', pd.Timestamp(2022, 12, 1)), 'water_factor_l'] == 2.0


def test_recognition_in_common_import_routes_to_water_loader():
    tables = tabular.read_content(xlsx(SHEET), 'Вынос воды ноябрь 2022.xlsx', 31)[1]
    assert base_book(tables, 'Вынос воды ноябрь 2022.xlsx').startswith('замеры воды')
    assert base_book(tables, 'Вынос воды.xlsx') == ''
