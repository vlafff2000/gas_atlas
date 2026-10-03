"""Паритет раздела «Импорт данных»: те же файлы через API 6 и через функции 5.8 дают одинаковые таблицы проекта."""
from pathlib import Path

import pandas as pd
import pytest
from starlette.testclient import TestClient

from app.core import config, exclusions, profiles, tabular
from app.core.import_rules import parse_pressure_book, to_kgf
from app.core.loader import load_file, merge_frames
from app.core.storage import Store
from app.ui import general_import as gi
from app.ui import pressure_quick_import as q
from atlas.api import create_app
from atlas.imports import Imports
from atlas.projects import Projects
from tools.make_pressure_samples import make_book

EXAMPLES = Path(__file__).resolve().parents[2] / 'examples'
TABLES = ['01_long_format.xlsx', '02_matrix.xlsx', '03_single_sheet.xlsx', '04_groups.xlsx', '05_subgroups.xlsx',
          '06_GDI_5_columns.csv', '07_response.csv']


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path)          # профили шапок — во временной папке
    projects = Projects(tmp_path)
    return TestClient(create_app(projects)), projects.store


def upload(client, name, content=None):
    content = content if content is not None else (EXAMPLES / name).read_bytes()
    r = client.post('/api/import/files', params={'name': name}, content=content)
    assert r.status_code == 200, r.text
    return r.json()['token']


def import6(client, pid, files, policy='new', accept=True, **params):
    body = {'view': 'simple', 'mode': 'auto', **params, 'files': files}
    r = client.post(f'/api/projects/{pid}/import/check', json=body)
    assert r.status_code == 200, r.text
    pending = r.json()
    r = client.post(f'/api/projects/{pid}/import/apply', json={'pending': pending['id'], 'policy': policy, 'accept': accept})
    assert r.status_code == 200, r.text
    return pending, r.json()


def import58(store, pid, paths, policy='new', mode='auto', kind='withdrawal', punit='м³/сут', gunit='тыс. м³/сут',
             mpa=False, sheet_options=None):
    """Шаги страницы 5.8 «Импорт данных»: load_file → МПа → merge_frames и группы → commit."""
    parsed, originals, rejected = {}, [], 0
    for path in paths:
        r = load_file(path, mode, kind, punit, gunit, sheet_options=(sheet_options or {}).get(path.name))
        if mpa:
            to_kgf(r.frames)
        for module, frame in r.frames.items():
            parsed[module] = pd.concat([parsed[module], frame], ignore_index=True) if module in parsed else frame
        rejected += r.rejected
        if r.frames:
            originals.append(path)
    m, data = store.load(pid)
    updated = {n: exclusions.identify(d, n) for n, d in data.items()}      # raw_frames 5.8 — с _point_id
    groups, duplicates = dict(m['groups']), 0
    for module, frame in parsed.items():
        if module == 'groups':
            for row in frame.itertuples():
                change = {}
                if row.group and row.group != 'Без группы':
                    change['group'] = row.group
                if row.subgroup:
                    change['subgroup'] = row.subgroup
                groups.setdefault(row.well, {}).update(change)
        else:
            updated[module], count = merge_frames(updated.get(module), frame, module, policy)
            duplicates += count
    imports = m.get('imports', []) + [store.keep_original(pid, p) for p in originals]
    store.commit(pid, updated, groups=groups, imports=imports, expected=m['revision'], action='Импорт данных')
    store.event(pid, 'Результат импорта', {'removed_duplicates': duplicates, 'rejected': rejected})
    return duplicates


def same_project(store, a, b):
    ma, da = store.load(a)
    mb, db = store.load(b)
    assert ma['tables'] == mb['tables'] and ma['groups'] == mb['groups']
    assert [i['sha256'] for i in ma['imports']] == [i['sha256'] for i in mb['imports']]
    for name in da:
        left = da[name].drop(columns=['_point_id'], errors='ignore')
        right = db[name].drop(columns=['_point_id'], errors='ignore')
        pd.testing.assert_frame_equal(left, right, check_dtype=False)


def test_examples_import_like_58_including_merge(env, tmp_path):
    client, store = env
    p6, p58 = store.create('Атлас 6'), store.create('Атлас 5.8')
    first, second = TABLES[:4], TABLES[3:]           # 04_groups — в обоих: повторы и слияние с прежними данными
    pending, applied = import6(client, p6, [{'token': upload(client, n)} for n in first])
    assert {c['module'] for c in pending['counts']} == {'production', 'groups'} and applied['message'] == 'Данные сохранены'
    import58(store, p58, [EXAMPLES / n for n in first])
    for policy in ('old', 'new'):
        import6(client, p6, [{'token': upload(client, n)} for n in second], policy=policy)
        import58(store, p58, [EXAMPLES / n for n in second], policy=policy)
    same_project(store, p6, p58)
    actions = store.history(p6)['Действие'].tolist()
    assert actions[:2] == ['Результат импорта', 'Импорт данных'] and actions.count('Импорт данных') == 3
    # 5.8 видит импорт 6: группы и подгруппы из 04/05
    assert store.manifest(p6)['groups']


def test_replace_units_mpa_and_kind(env):
    client, store = env
    p6, p58 = store.create('6'), store.create('5.8')
    params = dict(kind='injection', production_unit='тыс. м³/сут', gdi_unit='м³/сут', pressure_unit='МПа')
    names = ['03_single_sheet.xlsx', '06_GDI_5_columns.csv', '07_response.csv']
    import6(client, p6, [{'token': upload(client, n)} for n in names], **params)
    import58(store, p58, [EXAMPLES / n for n in names], kind='injection', punit='тыс. м³/сут', gunit='м³/сут', mpa=True)
    import6(client, p6, [{'token': upload(client, names[1])}], policy='replace')
    import58(store, p58, [EXAMPLES / names[1]], policy='replace')
    same_project(store, p6, p58)
    assert set(store.load(p6)[1]['production'].kind) == {'injection'}


def test_simple_table_forced_type_and_disabled_sheet(env):
    client, store = env
    tokens = {n: upload(client, n) for n in ('01_long_format.xlsx', '07_response.csv')}
    files = [{'token': tokens['01_long_format.xlsx'], 'choices': {'Закачка': {'use': False}}},
             {'token': tokens['07_response.csv'], 'choices': {'07_response': {'module': 'gdi', 'use': True}}}]
    r = client.post('/api/import/inspect', json={'view': 'simple', 'mode': 'auto', 'files': files}).json()
    rows = {(x['file'], x['sheet']): x for x in r['rows']}
    assert rows[('01_long_format.xlsx', 'Отборы')]['module'] == 'production' and not rows[('01_long_format.xlsx', 'Закачка')]['use']
    assert rows[('07_response.csv', '07_response')]['status'].startswith('Не подходит')
    assert r['blocked'] and r['errors'] and r['counts'] == {'files': 2, 'sheets': 3, 'use': 2, 'unknown': 0}
    pid = store.create('П')
    bad = client.post(f'/api/projects/{pid}/import/check', json={'view': 'simple', 'mode': 'auto', 'files': files})
    assert bad.status_code == 400 and '07_response' in bad.json()['error']
    # тот же лист, разметка — как general_import.auto_spec 5.8
    files[1]['choices'] = {}
    pending, _ = import6(client, pid, files)
    expected = load_file(EXAMPLES / '01_long_format.xlsx', sheet_options={'Закачка': {'enabled': False}}).frames['production']
    stored = store.load(pid)[1]['production']
    assert len(stored) == len(expected) and set(stored.sheet) == {'Отборы'}


def test_sheet_editor_defaults_match_58_auto_spec(env):
    client, _ = env
    for name in TABLES:
        token = upload(client, name)
        fmt, tables = tabular.read_content((EXAMPLES / name).read_bytes(), name, 31)
        for sheet, raw in tables.items():
            found, _ = gi.describe(raw, 'auto')
            state = client.post('/api/import/sheet', json={'token': token, 'sheet': sheet, 'mode': 'auto'}).json()
            assert state['effective'] == found, (name, sheet)
            expected = gi.auto_spec(raw, found)
            assert state['header'] == expected['header'] and state['wide'] == expected['wide']
            if found != 'groups':        # без заголовков группы сопоставляются по позиции, как в 5.8
                assert state['mapping'] == {k: v for k, v in expected['mapping'].items() if k in state['fields']}
            spec = Imports(None).finish_spec(raw, {'enabled': True, 'module': 'auto', 'header': state['header'],
                                                   'mapping': expected['mapping'], 'wide': state['wide'],
                                                   'wellcols': state['wellcols'], 'names': {}}, 'auto')
            assert spec['valid'] and spec['module'] == found and spec['wellcols'] == expected['wellcols']


def test_detailed_mode_with_header_offset_and_renamed_columns(env, tmp_path):
    client, store = env
    text = 'Отчет за месяц;;\nНомер;Число;Газ, тыс. м3/сут\n73;01.11.2025;2\n73;02.11.2025;3\n'.encode('cp1251')
    token = upload(client, 'отчет.csv', text)
    info = client.post('/api/import/inspect', json={'view': 'detailed', 'mode': 'auto', 'files': [{'token': token}]}).json()
    assert info['files'][0]['sheets'] == ['отчет'] and info['files'][0]['book'] is None
    state = client.post('/api/import/sheet', json={'token': token, 'sheet': 'отчет', 'mode': 'auto', 'header': 1,
                                                   'module': 'production'}).json()
    assert state['labels'] == ['Номер', 'Число', 'Газ, тыс. м3/сут'] and set(state['fields']) >= {'well', 'date', 'q'}
    spec = {'enabled': True, 'module': 'production', 'header': 1, 'mapping': {'well': 0, 'date': 1, 'q': 2}, 'wide': False,
            'wellcols': [], 'names': {'0': 'Скважина', '1': 'Дата', '2': 'Расход, тыс. м³/сут'}}
    pid = store.create('П')
    import6(client, pid, [{'token': token, 'sheets': {'отчет': spec}}], view='detailed')
    path = tmp_path / 'отчет.csv'
    path.write_bytes(text)
    expected = load_file(path, sheet_options={'отчет': {**spec, 'valid': True, 'datecol': 1, 'fond_pairs': []}}).frames['production']
    stored = store.load(pid)[1]['production']
    pd.testing.assert_frame_equal(stored.drop(columns=['_point_id'], errors='ignore'), expected, check_dtype=False)
    assert stored.q.tolist() == [2000, 3000]
    dup = dict(spec, mapping={'well': 0, 'date': 0, 'q': 2})
    token = upload(client, 'отчет.csv', text)        # после применения загруженные файлы освобождаются
    r = client.post(f'/api/projects/{pid}/import/check', json={'view': 'detailed', 'files': [{'token': token, 'sheets': {'отчет': dup}}]})
    assert r.status_code == 400 and 'Одной колонке' in r.json()['error']


def test_rejected_rows_need_confirmation_and_issue_log(env):
    client, store = env
    pid = store.create('П')
    token = upload(client, 'плохой.csv', 'Скважина;Дата;Расход\n73;01.11.2025;2000\n73;не дата;2000\n'.encode())
    r = client.post(f'/api/projects/{pid}/import/check', json={'files': [{'token': token}]}).json()
    assert r['rejected'] == 1 and r['issues']['count'] == 1
    assert client.post(f'/api/projects/{pid}/import/apply', json={'pending': r['id']}).status_code == 400
    csv = client.post(f'/api/projects/{pid}/import/table', json={'pending': r['id'], 'table': 'issues', 'format': 'csv'})
    assert csv.status_code == 200 and 'Некорректная или пустая дата' in csv.content.decode('utf-8-sig')
    assert client.post(f'/api/projects/{pid}/import/apply', json={'pending': r['id'], 'accept': True}).status_code == 200
    assert store.manifest(pid)['tables'] == {'production': 1}


def test_profile_is_shared_with_58(env):
    client, _ = env
    text = 'Отчет;;\nНомер;Число;Газ\n73;01.11.2025;2000\n'.encode()
    token = upload(client, 'отчет.csv', text)
    spec = {'enabled': True, 'module': 'production', 'header': 1, 'mapping': {'well': 0, 'date': 1, 'q': 2}, 'wide': False,
            'wellcols': [], 'names': {}}
    r = client.post('/api/import/profile', json={'token': token, 'sheet': 'отчет', 'spec': spec, 'remember': True})
    assert r.status_code == 200 and r.json()['remembered']
    raw = tabular.read_content(text, 'отчет.csv', 31)[1]['отчет']
    assert profiles.find(raw, 'general')['mapping'] == {'well': 0, 'date': 1, 'q': 2}     # 5.8 прочитает тот же профиль
    rows = client.post('/api/import/inspect', json={'files': [{'token': upload(client, 'отчет2.csv', text)}]}).json()['rows']
    assert rows[0]['status'] == 'По сохраненному профилю'
    client.post('/api/import/profile', json={'token': token, 'sheet': 'отчет', 'spec': spec, 'remember': False})
    assert profiles.find(raw, 'general') is None


def test_templates_and_pressure_book_hint(env, tmp_path):
    client, _ = env
    names = {t['name'] for t in client.get('/api/import/templates').json()}
    assert 'Шаблон_ГДИ.xlsx' in names and '07_response.csv' in names
    assert client.get('/api/import/templates/Шаблон_ГДИ.xlsx').content[:2] == b'PK'
    path = tmp_path / 'Объект.xlsx'
    make_book(path, 0, 3, 5)
    rows = client.post('/api/import/inspect', json={'files': [{'token': upload(client, path.name, path.read_bytes())}]}).json()
    assert rows['rows'][0]['book'] and rows['blocked']


def test_pressure_book_in_detailed_mode_like_58(env, tmp_path):
    client, store = env
    path = tmp_path / 'Объект.xlsx'
    make_book(path, 0, 4, 10)
    token = upload(client, path.name, path.read_bytes())
    info = client.post('/api/import/inspect', json={'view': 'detailed', 'files': [{'token': token}]}).json()['files'][0]
    book = info['book']
    assert book['fact'] == 'Факт' and book['models'] == ['Модель 1', 'Модель 2'] and book['fonds'] == ['Фонд']
    specs = {}
    for sheet in ['Факт', *book['models'], *book['fonds']]:
        fonds = sheet == 'Фонд'
        s = client.post('/api/import/sheet', json={'token': token, 'sheet': sheet, 'pressure': True, 'fonds': fonds}).json()
        specs[sheet] = {'enabled': True, 'header': s['header'], 'mapping': s['mapping'], 'wide': s['wide'],
                        'wellcols': s['wellcols'], 'names': {}, 'fond_pairs': s['fond_pairs']}
    pid = store.create('П')
    import6(client, pid, [{'token': token, 'pressure_book': {**book, 'duplicate': 'first', 'sheets': specs}}], view='detailed')
    tables = tabular.read_content(path.read_bytes(), path.name)[1]
    options = {'sheets': {n: q.auto_spec(tables[n].head(31), fonds=n == 'Фонд') for n in specs}, 'encoding': 'auto',
               'delimiter': 'auto', 'fact': 'Факт', 'models': book['models'], 'fonds': ['Фонд'], 'object': 'Объект'}
    expected = merge_frames(None, parse_pressure_book(path.read_bytes(), path.name, options).frames['pressure_match'],
                            'pressure_match')[0]
    stored = store.load(pid)[1]['pressure_match'].drop(columns=['_point_id'], errors='ignore')
    pd.testing.assert_frame_equal(stored, expected, check_dtype=False)


def test_pressure_quick_import_like_58(env, tmp_path):
    client, store = env
    paths = []
    for i in range(2):
        p = tmp_path / f'Объект_{i + 1:02d}.xlsx'
        make_book(p, i, 4, 8)
        paths.append(p)
    pid = store.create('Давления')
    files = [{'token': upload(client, p.name, p.read_bytes())} for p in paths]
    r = client.post(f'/api/projects/{pid}/import/pressure', json={'files': files, 'duplicate': 'first'}).json()
    assert not r['errors'] and r['counts'] == {'files': 2, 'sheets': 8, 'use': 8, 'objects': 2} and r['ready']['existing'] is None
    # 5.8: те же функции быстрого импорта
    cache58 = {str(p): q.parse_file(p.name, p.read_bytes()) for p in paths}
    rows58 = q.build_rows({str(p): (p.name, p.read_bytes()) for p in paths}, cache58, {}, 'Давления')
    assert [(x['Лист'], x['Роль'], x['Объект'], x['Сценарий'], x['Статус']) for x in rows58] == \
        [(x['Лист'], x['Роль'], x['Объект'], x['Сценарий'], x['Статус']) for x in r['rows']]
    data58 = q.assemble(rows58, cache58, 'first')[0]
    applied = client.post(f'/api/projects/{pid}/import/pressure/apply', json={'pending': r['ready']['id'], 'mode': 'add'})
    assert applied.status_code == 200, applied.text
    stored = store.load(pid)[1]['pressure_match'].drop(columns=['_point_id'], errors='ignore')
    pd.testing.assert_frame_equal(stored, data58, check_dtype=False)
    assert store.history(pid)['Действие'].iloc[0] == 'Импорт кроссплота давлений'
    # повторно один объект с другой ролью листа и сценарием: «добавить / обновить» заменяет только этот объект
    token = upload(client, paths[0].name, paths[0].read_bytes())
    choices = {token: {'Модель 2': {'use': False}, 'Модель 1': {'scenario': 'Базовый'}}}
    r = client.post(f'/api/projects/{pid}/import/pressure', json={'files': [{'token': token}], 'choices': choices}).json()
    assert r['ready']['existing'] == {'objects': 2, 'replaced': ['Объект_01']}
    client.post(f'/api/projects/{pid}/import/pressure/apply', json={'pending': r['ready']['id'], 'mode': 'add'})
    stored = store.load(pid)[1]['pressure_match']
    assert set(stored[stored.object.eq('Объект_01')].scenario) == {'Базовый'}
    assert set(stored[stored.object.eq('Объект_02')].scenario) == {'Модель 1', 'Модель 2'}


def test_pressure_fine_tuning_override_and_missing_fact(env, tmp_path):
    client, store = env
    pid = store.create('П')
    days = pd.date_range('2023-01-01', periods=5)
    rows = [['Дата', 'Скв', 'Давление']] + [[d.strftime('%d.%m.%Y'), '5', 100 + i] for i, d in enumerate(days)]
    text = 'Отчет;;\n' + '\n'.join(';'.join(map(str, r)) for r in rows) + '\n'
    tf = upload(client, 'Север_факт.csv', text.encode())
    tm = upload(client, 'Север_модель.csv', text.replace(';100', ';101').encode())
    files = [{'token': tf}, {'token': tm}]
    r = client.post(f'/api/projects/{pid}/import/pressure', json={'files': files}).json()
    spec = {'enabled': True, 'header': 1, 'mapping': {'date': 0, 'well': 1, 'value': 2}, 'wide': False, 'wellcols': [], 'names': {}}
    over = {tf: {'Север_факт': spec}, tm: {'Север_модель': spec}}
    r = client.post(f'/api/projects/{pid}/import/pressure', json={'files': files, 'overrides': over}).json()
    assert not r['errors'] and r['ready'], r
    no_fact = client.post(f'/api/projects/{pid}/import/pressure', json={
        'files': files, 'overrides': over, 'choices': {tf: {'Север_факт': {'use': False}}}}).json()
    assert no_fact['ready'] is None and 'не выбран лист или файл с фактом' in no_fact['errors'][0]
