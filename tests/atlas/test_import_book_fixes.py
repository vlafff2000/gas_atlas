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


def test_gsp_column_gives_group_name(tmp_path):
    rows = pd.DataFrame({'№скв': ['31', '32'], 'дата': pd.to_datetime(['2025-01-01'] * 2), 'ГСП': [1, 2],
                         'Qгаза тыс.м3/сут': [100.0, 120.0], 'Рпл, кгс/см2': [90.0, 91.0], 'Рзаб, кгс/см2': [80.0, 81.0]})
    path = tmp_path / 'gdi.xlsx'
    rows.to_excel(path, index=False, sheet_name='ГДИ')
    r = load_file(path, 'gdi', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert r.frames['gdi']['group'].tolist() == ['ГСП 1', 'ГСП 2']


def test_group_column_wins_over_gsp(tmp_path):
    rows = pd.DataFrame({'Скважина': ['1'], 'Дата': pd.to_datetime(['2025-01-01']), 'Суточный расход газа': [100.0],
                         'Источник': ['ГСП 5'], 'ГСП': [7]})
    path = tmp_path / 'both.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    r = load_file(path, 'auto', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert r.frames['production']['group'].tolist() == ['ГСП 5']


def test_duplicate_day_keeps_the_row_with_flow():
    from atlas.engine.core.loader import merge_frames
    new = pd.DataFrame({'well': ['195', '195', '196'], 'date': pd.to_datetime(['2024-04-01'] * 3),
                        'kind': ['withdrawal'] * 3, 'q': [191958.0, 0.0, 0.0]})
    merged, removed = merge_frames(None, new, 'production')
    got = merged.set_index('well')['q']
    assert got['195'] == 191958.0 and got['196'] == 0.0 and removed == 1


def test_duplicate_day_both_zero_or_both_flow_keeps_last():
    from atlas.engine.core.loader import merge_frames
    new = pd.DataFrame({'well': ['1', '1', '2', '2'], 'date': pd.to_datetime(['2024-04-01'] * 4),
                        'kind': ['withdrawal'] * 4, 'q': [100.0, 120.0, 0.0, 0.0]})
    merged, removed = merge_frames(None, new, 'production')
    assert merged.set_index('well')['q'].to_dict() == {'1': 120.0, '2': 0.0} and removed == 2


def test_production_group_wins_over_gdi_group(client, tmp_path):
    prod = pd.DataFrame({'Скважина': ['11', '12'], 'Дата': pd.to_datetime(['2025-01-01'] * 2),
                         'Суточный расход газа': [100.0, 200.0], 'Источник': ['ГСП 1', 'ГСП 1']})
    gdi = pd.DataFrame({'№скв': ['11', '11', '12'], 'дата': pd.to_datetime(['2024-01-01', '2025-01-01', '2025-01-01']),
                        'ГСП': [1, 2, 1], 'Qгаза тыс.м3/сут': [60.0, 70.0, 80.0],
                        'Рпл, кгс/см2': [90.0, 90.0, 90.0], 'Рзаб, кгс/см2': [80.0, 80.0, 80.0]})
    p1, p2 = tmp_path / 'prod.xlsx', tmp_path / 'gdi.xlsx'
    prod.to_excel(p1, index=False, sheet_name='Отбор')
    gdi.to_excel(p2, index=False, sheet_name='ГДИ')
    pid = client.post('/api/projects', json={'name': 'g'}).json()['id']
    toks = [upload(client, p) for p in (p1, p2)]
    pend = client.post(f'/api/projects/{pid}/import/check', json={'view': 'simple', 'mode': 'auto',
                                                                   'files': [{'token': t} for t in toks]}).json()
    client.post(f'/api/projects/{pid}/import/apply', json={'pending': pend['id'], 'policy': 'new', 'accept': True})
    data = Projects(tmp_path).data(pid)
    assert data.mapping['11']['group'] == 'ГСП 1' and data.mapping['12']['group'] == 'ГСП 1'


def test_gsp_spellings_are_one_group(tmp_path):
    rows = pd.DataFrame({'Скважина': ['1', '2', '3', '4'], 'Дата': pd.to_datetime(['2025-01-01'] * 4),
                         'Суточный расход газа': [1.0, 2.0, 3.0, 4.0],
                         'Источник': ['ГСП 4', 'ГСП_4', 'гсп-4', 'ГСП  4']})
    path = tmp_path / 'sp.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    r = load_file(path, 'auto', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert set(r.frames['production']['group']) == {'ГСП 4'}


def test_other_group_names_are_untouched(tmp_path):
    rows = pd.DataFrame({'Скважина': ['1', '2'], 'Дата': pd.to_datetime(['2025-01-01'] * 2),
                         'Суточный расход газа': [1.0, 2.0], 'Источник': ['Куст 4', 'ГСП_4Б']})
    path = tmp_path / 'sp2.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    r = load_file(path, 'auto', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert set(r.frames['production']['group']) == {'Куст 4', 'ГСП_4Б'}


def test_well_pressure_history_is_recognised(client, tmp_path):
    rows = pd.DataFrame({'Скважина': [83, 84], 'Номер ГСП': [2, 2],
                         'Дата': pd.to_datetime(['2006-08-02', '2006-08-03']), 'Месяц': ['Август', 'Август'],
                         'Год': [2006, 2006], 'Устьевое давление': [89.1, 88.0], 'Пластовое давление': [94.7, 93.1],
                         'Среднее давление': [94.7, 93.1]})
    path = tmp_path / 'wp.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    j = inspect(client, path)
    assert j['rows'][0]['found'] == 'operations' and j['blocked'] is False
    r = load_file(path, 'auto', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    o = r.frames['operations']
    assert o['well'].tolist() == ['83', '84']
    assert o['p_wellhead'].tolist() == [89.1, 88.0] and o['p_res'].tolist() == [94.7, 93.1]
    assert o['group'].tolist() == ['ГСП 2', 'ГСП 2']


def test_gdi_with_pressures_is_still_gdi_and_response_still_response(client, tmp_path):
    gdi = pd.DataFrame({'№скв': ['31'], 'дата': pd.to_datetime(['2025-01-01']), 'Qгаза тыс.м3/сут': [100.0],
                        'Рпл, кгс/см2': [90.0], 'Рзаб, кгс/см2': [80.0]})
    p1 = tmp_path / 'g.xlsx'
    gdi.to_excel(p1, index=False, sheet_name='ГДИ')
    assert inspect(client, p1)['rows'][0]['found'] == 'gdi'
    resp = pd.DataFrame({'Скважина': ['1'], 'Дата': pd.to_datetime(['2025-01-01']), 'Горизонт': ['Щ'],
                         'Уровень жидкости': [100.0], 'Пластовое давление': [90.0]})
    p2 = tmp_path / 'r.xlsx'
    resp.to_excel(p2, index=False, sheet_name='Данные')
    assert inspect(client, p2)['rows'][0]['found'] == 'response'


def test_group_spellings_are_unified_within_file(tmp_path):
    rows = pd.DataFrame({'Скважина': ['1', '2', '3', '4', '5'], 'Дата': pd.to_datetime(['2025-01-01'] * 5),
                         'Суточный расход газа': [1.0] * 5,
                         'Источник': ['Куст Северный', 'куст  северный', 'Куст_Северный', 'Куст Северный', 'Куст Южный']})
    path = tmp_path / 'u.xlsx'
    rows.to_excel(path, index=False, sheet_name='Sheet1')
    r = load_file(path, 'auto', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert sorted(set(r.frames['production']['group'])) == ['Куст Северный', 'Куст Южный']


def test_group_spelling_follows_already_loaded_data():
    from atlas.engine.core.loader import merge_frames
    old = pd.DataFrame({'well': ['1'], 'date': pd.to_datetime(['2025-01-01']), 'kind': ['withdrawal'], 'q': [1.0],
                        'group': ['Куст Северный']})
    new = pd.DataFrame({'well': ['2'], 'date': pd.to_datetime(['2025-01-02']), 'kind': ['withdrawal'], 'q': [2.0],
                        'group': ['куст_северный']})
    merged, _ = merge_frames(old, new, 'production')
    assert set(merged['group']) == {'Куст Северный'}
