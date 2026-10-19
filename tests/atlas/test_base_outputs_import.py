"""Выгрузки «Базы ПХГ» в Атласе: роли файлов папки, межколонки, группа из ГСП, сводные листы, книги со своим разбором.

Колонки — как в настоящих выгрузках модулей all_scripts (проверено на образцах Egor от 2026-10-15)."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas import project_folder as pf
from atlas.api import create_app
from atlas.engine.core import config
from atlas.engine.core.loader import column_map, detect_layout, load_file
from atlas.imports import Imports, base_book
from atlas.projects import Projects


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path / 'storage')
    return TestClient(create_app(Projects(tmp_path / 'storage')))


def touch(folder, *names):
    for n in names:
        (folder / n).write_bytes(b'x')


def roles(folder):
    return {f['name']: f['role'] for f in pf.scan(str(folder))['files']}


def test_base_flow_db_and_check_reports_get_right_roles(tmp_path):
    touch(tmp_path, 'Сводка_закачка_отбор_обновленный_скрипт.xlsx', 'Часы_ненулевые_расход_нулевой.xlsx',
          'Журнал_нормировки_ПЗРГ.xlsx', 'Даты_к_проверке.xlsx', 'Пересчёт_давлений.xlsx', 'БД_давлений_по_замерам.xlsx')
    assert roles(tmp_path) == {
        'Сводка_закачка_отбор_обновленный_скрипт.xlsx': 'production',     # итог «Создание базы данных расходов»
        'Часы_ненулевые_расход_нулевой.xlsx': None,                       # отчёт проверки, не расходы
        'Журнал_нормировки_ПЗРГ.xlsx': None,
        'Даты_к_проверке.xlsx': None,
        'Пересчёт_давлений.xlsx': 'pressure',
        'БД_давлений_по_замерам.xlsx': None,
    }
    touch(tmp_path, 'БД_расходы_нормированная_ПЗРГ.xlsx')
    r = roles(tmp_path)
    assert r['Сводка_закачка_отбор_обновленный_скрипт.xlsx'] is None and r['БД_расходы_нормированная_ПЗРГ.xlsx'] == 'production'


def test_superseded_flow_db_keeps_role_from_manifest(tmp_path):
    touch(tmp_path, 'БД_расходы.xlsx', 'БД_расходы_нормированная_ПЗРГ.xlsx')
    pf.save_manifest(str(tmp_path), {'БД_расходы.xlsx': {'role': 'production'}})
    assert roles(tmp_path)['БД_расходы.xlsx'] == 'production'


def annulus_book(path):
    pd.DataFrame({'дата': pd.to_datetime(['2023-04-01', '2023-04-01']), 'год': [2023, 2023], 'месяц': ['Апрель'] * 2,
                  'сезон': ['Сезон отбора 2022-2023'] * 2, 'номер_скважины': [1, 4],
                  'расход_газа_МК_сут': [0.0, 0.4], 'расход_газа_МК_мес': [0.0, 12.0], 'давление_МК': [0.0, 3.5]}).to_excel(path, index=False)


def test_annulus_db_loads_from_folder_and_reload_does_not_double(client, tmp_path):
    folder = tmp_path / 'выгрузки'
    folder.mkdir()
    annulus_book(folder / 'БД_межколонки.xlsx')
    pid = client.post('/api/projects', json={'name': 'П'}).json()['id']
    for _ in range(2):
        r = client.post(f'/api/projects/{pid}/folder/load', json={'folder': str(folder), 'files': ['БД_межколонки.xlsx']})
        assert r.status_code == 200 and r.json()['results'][0]['status'] == 'loaded', r.text
    projects = Projects(tmp_path / 'storage')
    frame = projects._raw_frames(pid, projects.manifest(pid))['annulus']
    assert len(frame) == 2 and sorted(frame['p'].tolist()) == [0.0, 3.5]


def test_gsp_column_wins_over_source_file_name():
    labels = ['Скважина', 'Дата', 'Горизонт', 'Категория', 'Руст, кгс/см2', 'Уровень жидкости, м',
              'Рпл приведённое (на 670 м), кгс/см2', 'Источник', 'ГСП']
    rows = [[2, None, 'Щигровский', 'Наблюдательные', None, -44.3, 83.7, 'Результат замеров сентябрь.xlsx', None],
            [56, None, 'Щигровский', 'Эксплуатационные', 89.1, None, 94.6, 'ФАЙЛ_ДЛЯ_СКРИПТА.xlsx', 'ГСП-1']]
    assert column_map(labels, rows)['group'] == labels.index('ГСП')
    # «Источник» с названием группы остаётся группой; в базе расходов колонки ГСП нет, группа — «Источник» (файл ГСП)
    assert column_map(labels, [r[:7] + ['ГСП 5', 7] for r in rows])['group'] == labels.index('Источник')
    assert column_map(['Скважина', 'Дата', 'Суточный расход газа', 'Источник'], [[1, None, 5.0, 'ГСП-9']])['group'] == 3


def test_well_pivot_by_months_is_not_a_plan(tmp_path):
    head = [['Скважина', '2006-06', '2006-08', '2006-09'], [56, 72.1, None, 73.0], [83, 71.6, 71.0, None]]
    assert detect_layout(head)['module'] is None
    plan = [['Группа', '2025-05', '2025-06'], ['ГСП 1', 10.0, 12.0]]
    assert detect_layout(plan)['module'] == 'plan'


def test_pressure_recalc_rows_keep_gsp_group(tmp_path):
    path = tmp_path / 'Пересчёт_давлений.xlsx'
    pd.DataFrame({'Скважина': [2, 56], 'Дата': pd.to_datetime(['2026-09-18', '2008-07-07']),
                  'Горизонт': ['Щигровский'] * 2, 'Категория': ['Наблюдательные', 'Эксплуатационные'],
                  'Руст, кгс/см2': [None, 89.1], 'Уровень жидкости, м': [-44.3, None],
                  'Рпл приведённое (на 670 м), кгс/см2': [83.7, 94.6], 'Источник': ['Результат замеров сентябрь.xlsx',
                                                                            'ФАЙЛ_ДЛЯ_СКРИПТА.xlsx'],
                  'ГСП': [None, 'ГСП-1']}).to_excel(path, sheet_name='Пересчёт', index=False)
    r = load_file(path)
    frame = r.frames['response']
    assert r.rejected == 0 and frame.set_index('well').loc['56', 'group'] == 'ГСП 1'      # единая схема имён, как в расходах
    assert not frame['group'].astype(str).str.contains('xlsx').any()


def test_elpro_and_gas_db_books_are_sent_to_sources(tmp_path):
    elpro = {'Данные': pd.DataFrame([['Дата', 'Режим', 'ГСП', 'Скважина', '№ п/п', 'Y кру, %', 'Q газа, тыс. м³/сут']])}
    gas = {'БД': pd.DataFrame([['Режим', 'Дата', 'Год', 'Месяц', 'Сезон', 'Файл', 'Лист', 'Отбор из ПХГ, тыс. м³/сут']])}
    assert base_book(elpro) == 'база ЭЛПРО' and base_book(gas) == '«БД по учету газа»'
    assert base_book({'Отборы': pd.DataFrame([['Скважина', 'Дата', 'Суточный расход газа', 'Источник']])}) == ''

    path = tmp_path / 'БД_ЭЛПРО.xlsx'
    pd.DataFrame([[pd.Timestamp('2022-11-01'), 'Отбор', 'ГСП-4', 90, 1, 99, 120.5]],
                 columns=elpro['Данные'].iloc[0].tolist()).to_excel(path, sheet_name='Данные', index=False)
    imports = Imports(Projects(tmp_path / 'storage'))
    token = imports.upload(path.name, path.read_bytes())['token']
    rows, _problems, options, _errors = imports.simple([{'token': token}], 'auto')
    assert rows[0]['book'] and 'Источники' in rows[0]['status'] and token not in options
    assert rows[0]['base'] == 'elpro'

    pid = imports.projects.create_demo()
    out = imports.base_load(pid, {'token': token})
    assert 'ЭЛПРО' in out['message'] and 'elpro' in imports.projects.data(pid)
