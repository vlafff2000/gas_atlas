"""ЭЛПРО в Атласе: разбор месячных файлов (xlsx и SpreadsheetML), дозапись, сравнение с БД расходов."""
import numpy as np
import pandas as pd
import pytest
from openpyxl import Workbook

from atlas.domain import DatasetKind
from atlas.engine.core import elpro_import as elpro
from atlas.imports import Imports
from atlas.modules.elpro_compare import ElproCompareModule
from atlas.contract import Data
from atlas.projects import Projects

PROD, ELPRO = DatasetKind.PRODUCTION, DatasetKind.ELPRO


def month_book(path, days):
    """Файл «Month_…» (настоящий xlsx, давление в кПа): шапка с датами и режимом, по строке на скважину."""
    wb = Workbook()
    ws = wb.active
    ws.append(['Параметры работы ГСП - 4'])
    ws.append(['режим: отбор', 'кПа', 'м3/ч'])     # единицы — отдельными ячейками, как в файлах ЭЛПРО
    ws.append(['Скважина', None] + [v for d in days for v in (d, 'Отбор газа', None, None, None)])
    # строка скважины: P (кПа), T, Y, Q (м³/сут), в работе
    row = ['', 101]
    for _ in days:
        row += [98.0665 * 50, 20.0, 80.0, 1500.0, 24.0]   # 50 кгс/см² в кПа
    ws.append(row)
    row = ['', 102]
    for _ in days:
        row += ['-', 19.0, 0.0, 0.0, 0.0]        # прочерк давления и простой (ноль)
    ws.append(row)
    wb.save(path)


def xml_book(path):
    """SpreadsheetML 2003 с расширением .xlsx (ГСП-1,2,3): подпись группы, блок дня, режим в шапке."""
    head = ('<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">'
            '<Worksheet ss:Name="Лист1" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Table>')
    def cell(v):
        if v is None:
            return '<Cell/>'
        if isinstance(v, str):
            return f'<Cell><Data ss:Type="String" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">{v}</Data></Cell>'
        return f'<Cell><Data ss:Type="Number" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">{v}</Data></Cell>'
    rows = [
        ['Параметры работы ГСП-1,2,3'],
        ['Скважина', None, '01.11.2022 отбор', None, None, None, None],
        ['ГСП-2'],
        ['', 7, 60.0, 15.0, 50.0, 2000.0, 24.0],
        ['', 8, 50.0, 14.0, 10.0, 0.0, 0.0],
    ]
    body = ''.join('<Row>' + ''.join(cell(v) for v in r) + '</Row>' for r in rows)
    path.write_text(head + body + '</Table></Worksheet></Workbook>', encoding='utf-8')


def test_month_file_units_outside_month_and_groups(tmp_path):
    path = tmp_path / 'Month_20221101_GSP4_Lift_20221021.xlsx'
    month_book(path, [pd.Timestamp('2022-11-01').date(), pd.Timestamp('2022-12-01').date()])
    data, info = elpro.read_file(str(path))
    assert info.fmt == 'xlsx' and info.groups == ['ГСП-4']
    assert info.outside == 2                                  # блок 01.12 — за дни следующего месяца, не загружен
    well101 = data[(data['Скважина'] == 101)]
    assert well101['P газа, кгс/см²'].iloc[0] == pytest.approx(50.0)     # кПа → кгс/см²
    assert set(well101['Режим']) == {'Отбор'}
    assert well101['Q газа, тыс. м³/сут'].iloc[0] == pytest.approx(1.5)  # м³ за сутки → тыс. м³
    assert data.loc[data['Скважина'] == 102, 'P газа, кгс/см²'].isna().all()   # прочерк — пропуск
    assert (data.loc[data['Скважина'] == 102, 'Q газа, тыс. м³/сут'] == 0).all()   # ноль — простой, не пропуск


def test_xml_file_groups_and_empty_values(tmp_path):
    path = tmp_path / '2022_11.xlsx'
    xml_book(path)
    data, info = elpro.read_file(str(path))
    assert info.fmt == 'XML'
    assert list(data['ГСП'].unique()) == ['ГСП-2']            # подпись «ГСП-2» стоит над блоком скважин
    assert list(data['Скважина']) == [7, 8]
    assert data.loc[data['Скважина'] == 7, 'Q газа, тыс. м³/сут'].iloc[0] == pytest.approx(2000.0)   # «т. м³» = тыс. м³/сут
    assert set(data['Режим']) == {'Отбор'}


def test_to_db_names_groups_and_merge_policy(tmp_path):
    path = tmp_path / 'Month_20221101_GSP4_Lift.xlsx'
    month_book(path, [pd.Timestamp('2022-11-01').date()])
    data, _, cov, _ = elpro.build([str(path)])
    db = elpro.to_db(data)
    assert set(db.columns) >= {'date', 'kind', 'group', 'well', 'np', 'p', 't', 'y', 'q', 'hours', 'file'}
    assert set(db.kind) == {'withdrawal'}
    assert set(db.group) == {'ГСП 4'}                       # «ГСП-4» из заголовка → «ГСП 4», как в импорте групп
    old = db.copy()
    old['q'] = 99.0
    merged_new, n = elpro.merge(old, db, 'new')
    assert n == len(db) and len(merged_new) == len(db)          # совпадения заменены, а не продублированы
    assert not (merged_new.q == 99.0).any()
    merged_old, _ = elpro.merge(old, db, 'old')
    assert (merged_old.q == 99.0).all()                         # «прежние» — оставлены старые значения


@pytest.fixture()
def ctx(tmp_path):
    projects = Projects(tmp_path)
    return projects, Imports(projects)


def test_compare_sums_only_common_days_and_flags(ctx):
    days = pd.to_datetime(['2025-06-01', '2025-06-02', '2025-06-03'])
    prod = pd.DataFrame({'well': ['101'] * 3 + ['102'] * 2, 'date': list(days) + list(days[:2]),
                         'q': [1000.0, 2000.0, 3000.0, 500.0, 500.0], 'kind': 'withdrawal'})
    elp = pd.DataFrame({'well': [101, 101, 102], 'date': list(days[:2]) + [days[0]], 'group': 'ГСП 4',
                        'kind': 'withdrawal', 'q': [1.0, 1.5, 0.0], 'np': '1', 'p': 50.0, 't': 15.0, 'y': 80.0,
                        'hours': 24.0, 'file': 'x'})
    data = Data({PROD: prod, ELPRO: elp})
    data.mapping = {'101': {'group': 'ГСП 4'}, '102': {'group': 'ГСП-4'}}
    data.settings = {}
    module = ElproCompareModule()
    result = module.run(data, module.spec.coerce({'kind': 'withdrawal', 'threshold': 10}))
    wells = next(t for t in result.tables if t.id == 'elpro-wells').frame.set_index('Скважина')
    # общие сутки скважины 101: 06-01 и 06-02 → БД расходов 1 + 2 = 3 тыс. м³, ЭЛПРО 1 + 1.5 = 2.5
    assert wells.loc['101', 'БД расходов'] == pytest.approx(3.0)
    assert wells.loc['101', 'ЭЛПРО'] == pytest.approx(2.5)
    assert wells.loc['101', 'Разница, %'] == pytest.approx(-100 / 6 * 1.0 * 0 + (2.5 - 3.0) / 3.0 * 100)
    assert wells.loc['101', 'Флаг'] == 'больше порога'
    # 102: в ЭЛПРО ноль — простой: сутки считаются, объём 0 и разница −100 %
    assert wells.loc['102', 'ЭЛПРО'] == 0.0
    assert wells.loc['102', 'Разница, %'] == pytest.approx(-100.0)
    assert wells.loc['102', 'Флаг'] == 'больше порога'


def test_project_load_adds_table_and_keeps_other_tables(tmp_path, ctx):
    projects, imports = ctx
    pid = projects.create_demo()
    before = len(projects.data(pid)[PROD])
    path = tmp_path / 'Month_20221101_GSP4_Lift.xlsx'
    month_book(path, [pd.Timestamp('2022-11-01').date()])
    res = imports.elpro_load(pid, path.name, path.read_bytes(), 'new')
    assert 'ЭЛПРО' in res['message'] and res['undo'] is not None
    data = projects.data(pid)
    assert ELPRO in data and not data[ELPRO].empty
    assert len(data[PROD]) == before                       # таблица расходов не тронута
    # повторная загрузка того же файла: строки заменяются, а не дублируются
    n = len(data[ELPRO])
    imports.elpro_load(pid, path.name, path.read_bytes(), 'new')
    assert len(projects.data(pid)[ELPRO]) == n


def test_folder_source_with_elpro_role_loads_through_elpro_path(tmp_path, ctx):
    """«Источники»: файл с ролью «ЭЛПРО» в папке проекта грузится своим разбором, не общим импортом."""
    from atlas import project_folder as pf
    projects, imports = ctx
    pid = projects.create_demo()
    folder = tmp_path / 'folder'
    folder.mkdir()
    name = 'Month_20221101_GSP4_Lift.xlsx'
    month_book(folder / name, [pd.Timestamp('2022-11-01').date()])
    pf.save_manifest(str(folder), {name: {'role': 'elpro'}})
    out = pf.load_files(imports, projects, pid, str(folder), [name], 'new')
    assert out['results'][0]['status'] == 'loaded', out['results']
    assert 'ЭЛПРО' in out['results'][0]['message']
    assert ELPRO in projects.data(pid)
