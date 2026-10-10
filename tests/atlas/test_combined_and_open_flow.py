"""«54/80» делится поровну; сутки «скважина открыта, расхода нет» сохраняются и считаются отдельно."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas import quality
from atlas.api import create_app
from atlas.engine.core import config
from atlas.engine.core.loader import load_file
from atlas.projects import Projects


def book(tmp_path, rows, name='prod.xlsx', sheet='Отбор'):
    path = tmp_path / name
    pd.DataFrame(rows).to_excel(path, index=False, sheet_name=sheet)
    return path


def prod_rows(spec):
    """spec: список (скважина, дата, расход, часы)."""
    return [{'Скважина': w, 'Дата': pd.Timestamp(d), 'Часовой расход газа': q / 24 if q else 0, 'Время работы': h,
             'Суточный расход газа': q, 'Тип данных': 'отбор', 'Источник': 'ГСП 1'} for w, d, q, h in spec]


def load(path):
    return load_file(path, 'auto', 'withdrawal', 'м³/сут', 'тыс. м³/сут')


# ----------------------------------------------------------- составные скважины
def test_combined_well_flow_is_split_equally(tmp_path):
    path = book(tmp_path, prod_rows([('54/80', '2025-01-01', 1000, 24), ('12', '2025-01-01', 700, 24)]))
    r = load(path)
    p = r.frames['production'].set_index('well')['q']
    assert p['54'] == 500 and p['80'] == 500 and p['12'] == 700
    assert '54/80' not in set(r.frames['production']['well'])
    assert any('54/80' in i['Причина'] and i['Уровень'] == 'предупреждение' for i in r.issues)


def test_total_volume_is_conserved_by_split(tmp_path):
    rows = prod_rows([('54/80', '2025-01-0%d' % d, 100.0 * d, 24) for d in range(1, 6)] +
                     [('7', '2025-01-0%d' % d, 50.0, 24) for d in range(1, 6)])
    r = load(book(tmp_path, rows))
    assert r.frames['production']['q'].sum() == pytest.approx(sum(100.0 * d for d in range(1, 6)) + 250)


def test_split_adds_to_own_rows_of_the_same_day(tmp_path):
    path = book(tmp_path, prod_rows([('54/80', '2025-01-01', 1000, 24), ('54', '2025-01-01', 300, 24)]))
    p = load(path).frames['production'].set_index('well')['q']
    assert p['54'] == 800 and p['80'] == 500


def test_three_wells_and_semicolon(tmp_path):
    path = book(tmp_path, prod_rows([('10/11/12', '2025-01-01', 900, 24), ('20;21', '2025-01-01', 400, 24)]))
    p = load(path).frames['production'].set_index('well')['q']
    assert p['10'] == p['11'] == p['12'] == 300 and p['20'] == p['21'] == 200


def test_plain_numbers_and_dates_not_taken_for_pairs(tmp_path):
    path = book(tmp_path, prod_rows([('54', '2025-01-01', 1000, 24), ('80', '2025-01-01', 300, 24)]))
    r = load(path)
    assert sorted(r.frames['production']['well']) == ['54', '80']
    assert not r.issues


def test_gdi_combined_well_duplicated_not_divided(tmp_path):
    rows = [{'Скважина': '54/80', 'Дата': pd.Timestamp('2025-01-01'), 'Q, тыс. м3/сут': 100.0, 'Рпл': 90.0, 'Рзаб': 80.0}]
    r = load_file(book(tmp_path, rows, 'gdi.xlsx', 'ГДИ'), 'gdi', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    g = r.frames['gdi']
    assert sorted(g['well']) == ['54', '80'] and set(g['q']) == {100.0}


# ----------------------------------------------------------- время работы и нулевой расход
def test_hours_column_is_loaded(tmp_path):
    r = load(book(tmp_path, prod_rows([('1', '2025-01-01', 0, 24), ('1', '2025-01-02', 100, 12)])))
    assert r.frames['production']['hours'].tolist() == [24, 12]


def stats_for(tmp_path, spec):
    p = load(book(tmp_path, prod_rows(spec))).frames['production']
    return quality.open_without_flow(p)


def test_open_without_flow_counts_series(tmp_path):
    days = pd.date_range('2025-01-01', periods=10)
    spec = []
    for i, d in enumerate(days):
        zero = 2 <= i <= 4 or i == 7
        spec.append(('1', d, 0 if zero else 1000, 24))
    s = stats_for(tmp_path, spec)
    w = s['wells'].iloc[0]
    assert (w['open_days'], w['zero_days'], w['episodes'], w['longest']) == (10, 4, 2, 3)
    assert w['share'] == pytest.approx(40)
    assert w['first'] == pd.Timestamp('2025-01-03') and w['last'] == pd.Timestamp('2025-01-08')


def test_closed_well_is_not_open_without_flow(tmp_path):
    """Время работы 0 и расход 0 — скважина остановлена, а не «открыта без расхода»."""
    s = stats_for(tmp_path, [('1', '2025-01-01', 0, 0), ('1', '2025-01-02', 0, 0), ('1', '2025-01-03', 500, 24)])
    assert s['zero_days'] == 0


def test_group_mass_days_flag_meter_node(tmp_path):
    spec = []
    for d in pd.date_range('2025-01-01', periods=3):
        for w in ('1', '2', '3', '4'):
            spec.append((w, d, 0 if d == pd.Timestamp('2025-01-02') else 800, 24))
    s = stats_for(tmp_path, spec)
    g = s['groups'].iloc[0]
    assert g['mass_days'] == 1 and g['max_share'] == pytest.approx(100)


def test_no_hours_means_no_statistics(tmp_path):
    rows = [{'Скважина': '1', 'Дата': pd.Timestamp('2025-01-01'), 'Суточный расход газа': 0.0, 'Тип данных': 'отбор'}]
    p = load(book(tmp_path, rows)).frames['production']
    assert quality.open_without_flow(p) is None


def test_zero_rows_are_kept_in_project_and_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path / 's')
    projects = Projects(tmp_path / 's')
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects', json={'name': 'z'}).json()['id']
    path = book(tmp_path, prod_rows([('1', '2025-01-0%d' % d, 0 if d in (2, 3) else 500, 24) for d in range(1, 6)]))
    tok = client.post('/api/import/files', params={'name': path.name}, content=path.read_bytes()).json()['token']
    pend = client.post(f'/api/projects/{pid}/import/check', json={'view': 'simple', 'mode': 'auto', 'files': [{'token': tok}]}).json()
    client.post(f'/api/projects/{pid}/import/apply', json={'pending': pend['id'], 'policy': 'new', 'accept': True})
    _, data = projects.store.load(pid)
    assert len(data['production']) == 5 and (data['production']['q'] == 0).sum() == 2        # нули не удалены
    j = client.post('/api/modules/quality/run', json={'project': pid, 'params': {}}).json()
    ids = [t['id'] for t in j['tables']]
    assert 'open_no_flow_wells' in ids
    t = next(t for t in j['tables'] if t['id'] == 'open_no_flow_wells')
    keys = [c['key'] for c in t['columns']]
    assert t['rows'][keys.index('zero_days')][0] == 2
    assert any(s['label'] == 'Открыта, расхода нет' for s in j['summary'])


def test_split_works_across_read_chunks(tmp_path):
    """Своя строка скважины и строка пары попадают в разные куски файла: расходы всё равно складываются."""
    path = book(tmp_path, prod_rows([('54', '2025-01-01', 300, 24), ('12', '2025-01-01', 10, 24),
                                     ('54/80', '2025-01-01', 1000, 24)]))
    r = load_file(path, 'auto', 'withdrawal', 'м³/сут', 'тыс. м³/сут', chunk_size=1)
    p = r.frames['production'].set_index('well')['q']
    assert p['54'] == 800 and p['80'] == 500 and p['12'] == 10


def test_duplicate_zero_row_does_not_erase_flow_in_file(tmp_path):
    path = book(tmp_path, prod_rows([('195', '2024-04-01', 191958, 19.5), ('195', '2024-04-01', 0, 0)]))
    r = load(path)
    assert r.frames['production']['q'].tolist() == [191958.0]
    assert any('Дубли суток' in i['Причина'] for i in r.issues)
