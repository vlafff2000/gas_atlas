"""Положение и перфорация скважин (X, Y, альтитуды, перфорация) → таблица ``well_geo``."""
import io

import numpy as np
import pandas as pd
import pytest

from atlas import project_folder as pf
from atlas.engine.core import config, well_geo_import as g
from atlas.imports import Imports, base_book
from atlas.projects import Projects


def xlsx(sheets):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(w, sheet_name=name, header=False, index=False)
    return buf.getvalue()


def test_text_xy_variants_and_welltrack():
    out, warn = g.build('xy.txt', 'скв X Y\nW500\t1000,5\t2000,25\nСкв_501 10.5 20.5\n502;7;8\n'.encode('cp1251'))
    assert out.set_index('well')[['x', 'y']].to_dict('index') == {'500': {'x': 1000.5, 'y': 2000.25},
                                                                  '501': {'x': 10.5, 'y': 20.5}, '502': {'x': 7.0, 'y': 8.0}}
    assert out.altitude.isna().all() and not warn
    track = b"WELLTRACK 'W7'\n 100 200 0 0\n 101 201 50 50 /\n"
    assert g.build('t.inc', track)[0].iloc[0].to_dict()['x'] == 100.0


def test_legacy_depth_book_keeps_absolute_marks_and_gaps():
    perf = [['Скв', 'a', 'b', 'c', 'Верх', 'Низ'], [31, 0, 0, 0, -1500.5, -1520], [32, 0, 0, 0, np.nan, np.nan]]
    out, _ = g.build('Глубины_перфораций.xlsx', xlsx({'перфорации': perf, 'альтитуды': [['Скв', 'Z'], [31, 85.2], [33, 90]]}))
    rows = out.set_index('well')
    assert rows.loc['31', ['perf_top', 'perf_bottom', 'altitude']].tolist() == [-1500.5, -1520.0, 85.2]
    assert '32' not in rows.index and rows.loc['33', 'altitude'] == 90 and np.isnan(rows.loc['33', 'perf_top'])


def test_header_table_any_subset_of_columns():
    book = xlsx({'Лист1': [['Скважина', 'X', 'Y', 'Альтитуда'], ['W5', 1, 2, 70], ['6', 3, 4, None]]})
    out, _ = g.build('geo.xlsx', book)
    assert out.set_index('well').loc['5', ['x', 'y', 'altitude']].tolist() == [1.0, 2.0, 70.0]
    assert np.isnan(out.set_index('well').loc['6', 'altitude'])
    assert g.looks_like({'Лист1': pd.DataFrame([['Скважина', 'X', 'Y']])})
    assert not g.looks_like({'Расход': pd.DataFrame([['Скважина', 'Дата', 'X', 'Y']])})


def test_merge_new_fills_but_never_erases_and_old_policy_keeps_values():
    old = pd.DataFrame({'well': ['1'], 'x': [1.0], 'y': [2.0], 'altitude': [50.0], 'perf_top': [np.nan], 'perf_bottom': [np.nan]})
    new = pd.DataFrame({'well': ['1', '2'], 'x': [9.0, 5.0], 'y': [8.0, 6.0], 'altitude': [np.nan, 70.0],
                        'perf_top': [-1.0, np.nan], 'perf_bottom': [-2.0, np.nan]})
    got = g.merge(old, new).set_index('well')
    assert got.loc['1', ['x', 'altitude', 'perf_top']].tolist() == [9.0, 50.0, -1.0] and got.loc['2', 'x'] == 5.0
    kept = g.merge(old, new, keep_old=True).set_index('well')
    assert kept.loc['1', ['x', 'altitude', 'perf_top']].tolist() == [1.0, 50.0, -1.0]


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path / 'storage')
    projects = Projects(tmp_path / 'storage')
    return projects, Imports(projects), projects.store.create('Тест')


def test_geo_load_saves_table_survives_backup_and_second_file_merges(project):
    projects, imports, pid = project
    first = imports.geo_load(pid, 'xy.txt', b'500\t1\t2\n501\t3\t4\n', 'new')
    assert 'скважин 2' in first['message']
    imports.geo_load(pid, 'Глубины_перфораций.xlsx',
                     xlsx({'перфорации': [['s', 0, 0, 0, 'в', 'н'], [500, 0, 0, 0, -10, -20]], 'альтитуды': [['s', 'z'], [500, 80]]}), 'new')
    m, data = projects.store.load(pid)
    assert m['tables']['well_geo'] == 2
    assert data['well_geo'].set_index('well').loc['500'].tolist() == [1.0, 2.0, 80.0, -10.0, -20.0]
    copy = projects.store.restore(projects.store.backup(pid))          # резервная копия и восстановление
    assert projects.store.load(copy if isinstance(copy, str) else copy['id'])[1]['well_geo'].shape == (2, 6)


def test_geo_load_refuses_unrecognized_file(project):
    _, imports, pid = project
    with pytest.raises(Exception, match='не нашлось'):
        imports.geo_load(pid, 'x.txt', 'просто текст'.encode(), 'new')


def test_folder_roles_and_special_book_detection(tmp_path):
    for n in ('Глубины_перфораций.xlsx', 'координаты_tNav.txt', 'XY скважин.txt', 'БД_расходы.xlsx'):
        (tmp_path / n).write_bytes(b'x')
    found = {f['name']: f['role'] for f in pf.scan(str(tmp_path))['files']}
    assert found == {'Глубины_перфораций.xlsx': 'geo', 'координаты_tNav.txt': 'geo', 'XY скважин.txt': 'geo',
                     'БД_расходы.xlsx': 'production'}
    assert base_book({'Данные': pd.DataFrame([['Скважина', 'X', 'Y']])}).startswith('файл положения')


def test_well_water_book_keeps_water_factor_column(tmp_path):
    from atlas.engine.core.loader import load_file
    path = tmp_path / 'БД_замеров_воды.xlsx'
    pd.DataFrame({'Скважина': [56, 57], 'Дата': pd.to_datetime(['2025-01-01', '2025-01-01']), 'Водопроявление': ['Да', 'Нет'],
                  'Расход воды': [0.8, 0.0], 'Водный фактор': [12.5, 0.0], 'Примечание': ['Ок', 'Ок']}
                 ).to_excel(path, sheet_name='Данные', index=False)
    frame = load_file(path).frames['water']
    assert frame.set_index('well').loc['56', 'water_factor_l'] == 12.5 and frame.set_index('well').loc['56', 'water_rate'] == 0.8
