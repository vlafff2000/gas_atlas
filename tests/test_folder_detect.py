"""Папка проекта: тип файлов Базы ПХГ узнаётся по содержимому, причина видна, роль меняется вручную.
Данные — литеральные, прямо в тесте."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas import project_folder
from atlas.api import create_app
from atlas.projects import Projects

PACKS = pd.DataFrame({'Скважина': ['115', '115', '113'], 'Дата': ['01.10.2024', '01.10.2024', '01.10.2024'], 'Сезон': ['осень'] * 3,
                      'Пачка': ['верхняя', '', 'верхняя'], 'hг эф, м': [1.5, 2.0, 3.0], 'Кг ср.взв': [0.3, 0.2, 0.5],
                      'ГВК а.о., м': [-1000.0, -1001.0, -990.0]})
INTERVALS = pd.DataFrame({'Скважина': ['115', '115'], 'Дата': ['01.10.2024'] * 2, 'Пачка': ['верхняя', ''],
                          'От, м': [1000.0, 1010.0], 'До, м': [1002.0, 1012.0], 'Кг': [0.3, 0.2]})
OBS = pd.DataFrame({'Скважина': ['115', '113'], 'Дата': ['01.10.2024'] * 2, 'Статус': ['есть данные'] * 2, 'Пачек': [1, 1]})


@pytest.fixture()
def folder(tmp_path):
    out = tmp_path / 'export'
    out.mkdir()
    with pd.ExcelWriter(out / 'выгрузка_осень.xlsx') as xw:           # имя не подсказывает тип
        PACKS.to_excel(xw, sheet_name='Свод', index=False)
        PACKS[PACKS['Пачка'] == 'верхняя'].to_excel(xw, sheet_name='верхняя', index=False)      # повтор Свода: не грузится дважды
        INTERVALS.to_excel(xw, sheet_name='Интервалы', index=False)
        OBS.to_excel(xw, sheet_name='Замеры', index=False)
    pd.DataFrame({'well': ['115'], 'date': ['2024-10-01'], 'status': ['ok'], 'packs': [1]}).to_csv(
        out / 'данные.csv', index=False, sep=';', decimal=',', encoding='utf-8-sig')
    pd.DataFrame({'a': [1]}).to_excel(out / 'Часы_ненулевые_расход_нулевой.xlsx', index=False)
    pd.DataFrame({'x': [1]}).to_excel(out / 'что-то.xlsx', index=False)
    return out


def _by_name(scan):
    return {f['name']: f for f in scan['files']}


def test_gis_book_and_csv_recognised_by_content_with_reason(folder):
    files = _by_name(project_folder.scan(str(folder)))
    book = files['выгрузка_осень.xlsx']
    assert book['role'] == 'gis' and book['role_source'] == 'content'
    assert 'лист «Свод» — пачки' in book['role_reason'] and 'лист «Интервалы» — интервалы' in book['role_reason']
    assert files['данные.csv']['role'] == 'gis'


def test_reports_and_unknown_files_stay_unassigned(folder):
    files = _by_name(project_folder.scan(str(folder)))
    assert files['Часы_ненулевые_расход_нулевой.xlsx']['role'] is None
    assert files['что-то.xlsx']['role'] is None and files['что-то.xlsx']['known'] == ''


def test_manual_role_wins_and_says_what_content_looks_like(folder):
    project_folder.save_manifest(str(folder), {'выгрузка_осень.xlsx': {'role': 'production'}})
    book = _by_name(project_folder.scan(str(folder)))['выгрузка_осень.xlsx']
    assert book['role'] == 'production' and book['role_source'] == 'manifest'
    assert 'похож на «База ГИС' in book['role_reason']


def test_gis_book_loads_all_three_tables_without_unassigned_rows(folder, tmp_path):
    projects = Projects(tmp_path / 'storage')
    api = TestClient(create_app(projects))
    pid = api.post('/api/projects/demo').json()['id']
    out = api.post(f'/api/projects/{pid}/folder/load', json={'folder': str(folder), 'files': ['выгрузка_осень.xlsx'], 'policy': 'new'}).json()
    assert out['results'][0]['status'] == 'loaded', out
    tables = api.get(f'/api/projects/{pid}').json()['tables']
    assert (tables['gis_packs'], tables['gis_intervals'], tables['gis_observations']) == (2, 1, 2)


def test_signatures_recognise_outputs_under_any_name(tmp_path):
    out = tmp_path / 'x'
    out.mkdir()
    with pd.ExcelWriter(out / 'a.xlsx') as xw:
        pd.DataFrame({'Скважина': ['1'], 'Дата': ['2024-01-01'], 'Категория': ['Эксплуатационные'], 'Руст': [10.0]}).to_excel(xw, sheet_name='Данные', index=False)
    with pd.ExcelWriter(out / 'b.xlsx') as xw:
        pd.DataFrame({'Скважина': ['1'], 'Дата': ['2024-01-01'], 'Давление, бар': [100.0]}).to_excel(xw, sheet_name='include_эксплуатационные', index=False)
    with pd.ExcelWriter(out / 'c.xlsx') as xw:
        pd.DataFrame({'a': [1]}).to_excel(xw, sheet_name='Отборы', index=False)
        pd.DataFrame({'a': [1]}).to_excel(xw, sheet_name='Закачка', index=False)
    files = _by_name(project_folder.scan(str(out)))
    assert files['a.xlsx']['role'] is None and 'Пересчёт_давлений' in files['a.xlsx']['role_reason']      # узнан, но не грузится: причина видна
    assert files['b.xlsx']['role'] == 'pressure' and files['c.xlsx']['role'] == 'production'
    assert 'листы «Закачка», «Отборы»' in files['c.xlsx']['role_reason']


def test_registry_lists_every_known_output_family():
    labels = ' '.join(r['label'] for r in project_folder.registry())
    for word in ('ЭЛПРО', 'учету газа', 'База ГИС', 'расходов', 'ГДИ', 'воды', 'межколонок', 'Пересчёт давлений', 'шахматка'):
        assert word in labels
