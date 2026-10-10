"""Книги с служебными листами, пустые дубли колонок, таблица давлений по скважинам, давление объекта по датам."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.api import create_app
from atlas.engine.core import config
from atlas.engine.core.loader import load_file
from atlas.projects import Projects


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path)
    return TestClient(create_app(Projects(tmp_path)))


def upload(client, path):
    r = client.post('/api/import/files', params={'name': path.name}, content=path.read_bytes())
    assert r.status_code == 200, r.text
    return r.json()['token']


def inspect(client, path):
    return client.post('/api/import/inspect', json={'view': 'simple', 'mode': 'auto',
                                                    'files': [{'token': upload(client, path)}]}).json()


def response_rows():
    return pd.DataFrame({'Скважина': ['1', '1', '2'], 'Дата': pd.to_datetime(['2025-01-01', '2025-02-01', '2025-01-01']),
                         'Горизонт': ['Щигровский'] * 3, 'Уровень жидкости': [100.0, 110.0, 120.0]})


def test_book_with_service_sheets_is_not_blocked(client, tmp_path):
    path = tmp_path / 'obs.xlsx'
    with pd.ExcelWriter(path) as w:
        response_rows().to_excel(w, sheet_name='Данные', index=False)
        pd.DataFrame({'Итог': ['сводка'], 'Значение': [3]}).to_excel(w, sheet_name='Статистика', index=False)
        pd.DataFrame({'Файл': ['a.xls']}).to_excel(w, sheet_name='Файлы', index=False)
    j = inspect(client, path)
    assert j['blocked'] is False
    assert {r['sheet']: r['use'] for r in j['rows']} == {'Данные': True, 'Статистика': False, 'Файлы': False}
    pid = client.post('/api/projects', json={'name': 'obs'}).json()['id']
    tok = upload(client, path)
    r = client.post(f'/api/projects/{pid}/import/check', json={'view': 'simple', 'mode': 'auto', 'files': [{'token': tok}]})
    assert r.status_code == 200, r.text
    assert r.json()['counts'][0] == {'module': 'response', 'label': r.json()['counts'][0]['label'], 'rows': 3}


def test_book_with_nothing_recognised_is_still_blocked(client, tmp_path):
    path = tmp_path / 'junk.xlsx'
    pd.DataFrame({'Фамилия': ['А'], 'Город': ['Б']}).to_excel(path, index=False)
    assert inspect(client, path)['blocked'] is True


def test_empty_duplicate_columns_are_ignored(tmp_path):
    rows = pd.DataFrame({'Скважина': ['1', '2'], 'Дата': pd.to_datetime(['2025-01-01', '2025-01-01']),
                         'Суточный расход газа': [100.0, 200.0], 'date': [None, None], 'well_number': [None, None]})
    path = tmp_path / 'otbory.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    r = load_file(path, 'auto', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert r.frames['production']['q'].tolist() == [100.0, 200.0]


def test_two_filled_date_columns_still_an_error(tmp_path):
    rows = pd.DataFrame({'Скважина': ['1'], 'Дата': pd.to_datetime(['2025-01-01']), 'Суточный расход газа': [100.0],
                         'date': pd.to_datetime(['2025-01-02'])})
    path = tmp_path / 'two.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    with pytest.raises(ValueError):
        load_file(path, 'auto', 'withdrawal', 'м³/сут', 'тыс. м³/сут')


def test_well_pressure_table_is_not_a_plan(client, tmp_path):
    rows = pd.DataFrame({'Скважина': ['83', '84', '85'], 'Номер ГСП': [2, 2, 3],
                         'Дата': pd.to_datetime(['2006-08-02', '2006-08-03', '2006-08-04']),
                         'Месяц': ['Август'] * 3, 'Год': [2006] * 3,
                         'Устьевое давление': [89.1, 88.0, 90.2], 'Пластовое давление': [94.7, 93.1, 95.0]})
    path = tmp_path / 'wp.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    j = inspect(client, path)
    assert j['rows'][0]['found'] != 'plan'


def test_real_plan_matrix_is_still_a_plan(client, tmp_path):
    plan = pd.DataFrame({'Группа': ['ГСП 1', 'ГСП 2'], 'Январь': [10.0, 20.0], 'Февраль': [11.0, 21.0], 'Март': [12.0, 22.0]})
    path = tmp_path / 'plan.xlsx'
    plan.to_excel(path, index=False, sheet_name='План')
    assert inspect(client, path)['rows'][0]['found'] == 'plan'


def test_object_pressure_same_day_is_averaged(tmp_path):
    rows = pd.DataFrame({'Дата замера': pd.to_datetime(['2025-10-31'] * 3 + ['2025-10-30']),
                         'Пласт': ['Щигровский'] * 4, 'Приведенное давление': [90.0, 100.0, 110.0, 80.0]})
    path = tmp_path / 'op.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    r = load_file(path, 'object_pressure', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    f = r.frames['object_pressure'].set_index('date')['pressure']
    assert f[pd.Timestamp('2025-10-31')] == pytest.approx(100.0) and f[pd.Timestamp('2025-10-30')] == 80.0
    assert any('усреднены' in i['Причина'] for i in r.issues)


def test_object_pressure_horizons_on_same_date_kept(tmp_path):
    rows = pd.DataFrame({'Дата замера': pd.to_datetime(['2025-10-31'] * 2), 'Пласт': ['Щигровский', 'Окский'],
                         'Приведенное давление': [90.0, 95.0]})
    path = tmp_path / 'op2.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    r = load_file(path, 'object_pressure', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert len(r.frames['object_pressure']) == 2 and not any('усреднены' in i['Причина'] for i in r.issues)
