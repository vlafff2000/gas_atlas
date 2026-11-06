"""Паритет с 5.8: «Группы» и «Аналитика фонда» (docs/parity/groups.md)."""
import datetime as dt

import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.engine.core.config import ordered
from atlas.engine.modules import gdi as legacy_gdi
from atlas.engine.modules import group_analysis
from atlas.engine.modules import production as legacy
from atlas.api import create_app
from atlas.contract import Param, ParamError
from atlas.domain import DatasetKind
from atlas.modules.fund import program_span, program_wells
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    return client, pid, projects


def run(client, pid, module, **params):
    r = client.post(f'/api/modules/{module}/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def table(body, tid):
    return next(t for t in body['tables'] if t['id'] == tid)


def rows(t):
    """Таблица ответа -> DataFrame по ключам колонок."""
    return pd.DataFrame({c['key']: values for c, values in zip(t['columns'], t['rows'])})


def periods(projects, pid, kind='withdrawal'):
    df = projects.data(pid)[DatasetKind.PRODUCTION]
    return ordered(df.loc[df.kind.eq(kind), 'period'])


# ---------- 5.8, как было в app/main.py до выноса в group_analysis (эталон паритета) ----------

def ranking_58(f, mapping):
    positive = f[f.q.gt(0)]
    stats = f.groupby('well').agg(Объем_млн_м3=('q', lambda v: v.sum() / 1e6), Записей=('q', 'size'),
                                  Нулевых=('q', lambda v: v.eq(0).sum()))
    stats['Средний_тыс_м3_сут'] = positive.groupby('well').q.mean() / 1000
    stats['Средний_тыс_м3_сут'] = stats['Средний_тыс_м3_сут'].fillna(0)
    stats['Активных_дней'] = positive.groupby('well').q.size()
    stats = stats.fillna(0).sort_values('Средний_тыс_м3_сут', ascending=False).reset_index().rename(columns={'well': 'Скважина'})
    stats['Группа'] = stats['Скважина'].map(lambda w: mapping.get(w, {}).get('group', 'Без группы'))
    return stats


def program_58(gdi_df, ws, span):
    d = gdi_df[gdi_df.date.between(pd.Timestamp(span[0]), pd.Timestamp(span[1]))]
    counts = d.groupby('well').date.nunique()
    program = pd.DataFrame({'Скважина': ws, 'Дат исследований': [int(counts.get(w, 0)) for w in ws]})
    program['Статус'] = program['Дат исследований'].map(lambda n: 'Проведено' if n else 'Нет исследования')
    return program


# ---------- Группы ----------

def test_assignments_show_project_mapping(env):
    client, pid, projects = env
    data = projects.data(pid)
    t = rows(table(run(client, pid, 'groups'), 'assignments'))
    assert t.well.tolist() == data.wells
    assert t.group.tolist() == [data.mapping.get(w, {}).get('group', 'Без группы') for w in data.wells]
    action = table(run(client, pid, 'groups'), 'assignments')['action']
    assert action['kind'] == 'assign' and action['editable'] == ['group', 'subgroup']
    assert action['values']['group'] == t.group.tolist()


@pytest.mark.parametrize('direction', ['desc', 'asc', 'number'])
def test_auto_subgroups_match_58_partitions(env, direction):
    client, pid, projects = env
    ps = periods(projects, pid)[-2:]
    body = run(client, pid, 'groups', kind='withdrawal', size=3, direction=direction, periods=ps)
    data = projects.data(pid)
    parts = legacy.partitions(data[DatasetKind.PRODUCTION], data.mapping, 'withdrawal', ps, data.wells, 'auto', 3, direction)
    summary = rows(table(body, 'auto-summary'))
    assert summary.label.tolist() == list(parts)
    assert summary.wells.tolist() == [', '.join(ws) for ws in parts.values()]
    apply = rows(table(body, 'auto-apply'))
    assert apply.well.tolist() == [w for ws in parts.values() for w in ws]
    assert apply.subgroup.tolist() == [k.rsplit(' / ', 1)[1] for k, ws in parts.items() for _ in ws]
    preview = body['charts'][0]
    first = next(iter(parts))
    assert preview['title'] == first and preview['x']['categories'] == parts[first]


def test_auto_without_periods_has_no_apply(env):
    client, pid, _ = env
    body = run(client, pid, 'groups', periods=[])
    assert 'auto-apply' not in {t['id'] for t in body['tables']} and not body['charts']
    assert any('периоды' in n['text'] for n in body['notes'])


def test_save_assignments_in_58_format(env):
    client, pid, projects = env
    before = projects.manifest(pid)
    r = client.post(f'/api/projects/{pid}/groups', json={'changes': {'31': {'group': 'Север', 'subgroup': 'А'},
                                                                      '45': {'group': '  '}}})
    assert r.status_code == 200, r.text
    m = projects.manifest(pid)
    assert m['revision'] == before['revision'] + 1
    assert m['groups']['31'] == {'group': 'Север', 'subgroup': 'А'}
    assert m['groups']['45']['group'] == 'Без группы'           # пустая группа — как в 5.8
    data = projects.data(pid)
    assert data.mapping['31'] == {'group': 'Север', 'subgroup': 'А'}
    history = projects.store.history(pid)
    assert 'Назначение групп' in history['Действие'].tolist()
    t = rows(table(run(client, pid, 'groups'), 'assignments')).set_index('well')
    assert t.loc['31', 'group'] == 'Север' and t.loc['31', 'subgroup'] == 'А'


def test_apply_auto_subgroups_keeps_groups(env):
    client, pid, projects = env
    ps = periods(projects, pid)
    body = run(client, pid, 'groups', kind='withdrawal', size=2, direction='desc', periods=ps)
    apply = rows(table(body, 'auto-apply'))
    groups_before = {w: v.get('group') for w, v in projects.data(pid).mapping.items()}
    changes = {w: {'subgroup': s} for w, s in zip(apply.well, apply.subgroup)}
    r = client.post(f'/api/projects/{pid}/groups', json={'changes': changes, 'action': 'Автоматические подгруппы'})
    assert r.status_code == 200, r.text
    mapping = projects.data(pid).mapping
    for w, s in zip(apply.well, apply.subgroup):
        assert mapping[w]['subgroup'] == s and mapping[w]['group'] == groups_before[w]


def test_groups_errors(env):
    client, pid, projects = env
    bad = client.post(f'/api/projects/{pid}/groups', json={'changes': {'нет-такой': {'group': 'X'}}})
    assert bad.status_code == 400 and 'Нет таких скважин' in bad.json()['error']
    assert client.post(f'/api/projects/{pid}/groups', json={'changes': {}}).status_code == 400
    assert client.post(f'/api/projects/{pid}/groups', json={'changes': {'31': {'well': 'x'}}}).status_code == 400
    assert client.post(f'/api/projects/{pid}/groups', json={'changes': {'31': {'group': 'X'}},
                                                            'action': 'Удалить всё'}).status_code == 400
    stale = projects.manifest(pid)['revision'] - 1
    conflict = client.post(f'/api/projects/{pid}/groups', json={'changes': {'31': {'group': 'X'}}, 'revision': stale})
    assert conflict.status_code == 409


# ---------- Аналитика фонда ----------

def test_ranking_matches_58(env):
    client, pid, projects = env
    ps = periods(projects, pid)
    body = run(client, pid, 'fund', kind='withdrawal', periods=ps)
    data = projects.data(pid)
    d = data[DatasetKind.PRODUCTION]
    expected = ranking_58(d[d.kind.eq('withdrawal') & d.period.isin(ps)], data.mapping)
    got = rows(table(body, 'ranking'))
    pd.testing.assert_frame_equal(group_analysis.ranking(d[d.kind.eq('withdrawal') & d.period.isin(ps)], data.mapping),
                                  expected)
    assert got['Скважина'].tolist() == expected['Скважина'].tolist()
    for col in ('Объем_млн_м3', 'Средний_тыс_м3_сут', 'Активных_дней', 'Записей', 'Нулевых'):
        assert got[col].astype(float).tolist() == pytest.approx(expected[col].astype(float).tolist())
    assert got['Группа'].tolist() == expected['Группа'].tolist()


def test_ranking_injection_and_empty(env):
    client, pid, projects = env
    ps = periods(projects, pid, 'injection')
    assert rows(table(run(client, pid, 'fund', kind='injection', periods=ps), 'ranking')).shape[0] > 0
    body = run(client, pid, 'fund', kind='withdrawal', periods=[])
    assert 'ranking' not in {t['id'] for t in body['tables']} and body['notes']


def test_gdi_quality_matches_58(env):
    client, pid, projects = env
    data = projects.data(pid)
    g = data[DatasetKind.GDI]
    expected = legacy_gdi.analyze(legacy_gdi.select_studies(g, ordered(g.well), 1), data.settings['r2_threshold'])
    got = rows(table(run(client, pid, 'fund', periods=[]), 'gdi-quality'))
    assert got.well.tolist() == expected.well.tolist()
    assert got.r2.astype(float).tolist() == pytest.approx(expected.r2.astype(float).tolist(), nan_ok=True)
    assert got.note.fillna('').tolist() == expected.note.fillna('').tolist()


def test_program_matches_58(env):
    client, pid, projects = env
    g = projects.data(pid)[DatasetKind.GDI]
    start, end = g.date.min().date(), g.date.max().date()
    text = '31, 45;540\n9999'
    body = run(client, pid, 'fund', periods=[], program=text, start=str(start), end=str(end))
    ws = ordered(['31', '45', '540', '9999'])
    expected = program_58(g, ws, (start, end))
    got = rows(table(body, 'program'))
    assert got['Скважина'].tolist() == expected['Скважина'].tolist()
    assert got['Дат исследований'].tolist() == expected['Дат исследований'].tolist()
    assert got['Статус'].tolist() == expected['Статус'].tolist()
    assert got['Статус'].iloc[-1] == 'Нет исследования'
    pd.testing.assert_frame_equal(group_analysis.program(g, ws, start, end), expected)
    reversed_ = run(client, pid, 'fund', periods=[], program=text, start=str(end), end=str(start))
    assert 'program' not in {t['id'] for t in reversed_['tables']}
    assert any(n['level'] == 'warning' for n in reversed_['notes'])


def test_program_defaults_like_58():
    assert program_wells(' 45\n31,,540; ') == ['31', '45', '540']
    assert program_wells('') == []
    today = dt.date(2026, 10, 3)
    assert program_span(None, None, today) == (dt.date(2026, 1, 1), today)
    assert program_span('2025-02-01', '', today) == (dt.date(2025, 2, 1), today)


def test_composition_counts(env):
    client, pid, projects = env
    m = projects.manifest(pid)
    got = dict(zip(*table(run(client, pid, 'fund', periods=[]), 'composition')['rows']))
    assert got['Скважин'] == len(projects.data(pid).wells)
    assert got['Динамика'] == m['tables'].get('production', 0)
    assert got['Точек ГДИ'] == m['tables'].get('gdi', 0)
    assert got['Замеров уровней'] == m['tables'].get('response', 0)


def test_date_and_text_params():
    p = Param('d', 'Дата', 'date')
    assert p.coerce('2025-03-04') == '2025-03-04' and p.coerce('') is None and p.coerce(None) is None
    with pytest.raises(ParamError):
        p.coerce('не дата')
    assert Param('t', 'Текст', 'text', default='').coerce(12) == '12'


def test_bulk_assignment_by_numbers(env):
    client, pid, projects = env
    wells = rows(table(run(client, pid, 'groups'), 'assignments')).well.tolist()
    pick = wells[:2]
    body = run(client, pid, 'groups', bulk_wells=f'{pick[0]}; {pick[1]},  9999\n', bulk_group='Север')
    t = table(body, 'bulk')
    assert rows(t).well.tolist() == pick and set(rows(t).group) == {'Север'}
    assert t['action']['submit'] == 'all' and t['action']['fields'] == ['group']
    note = next(n['text'] for n in body['notes'] if 'Массовое' in n['text'])
    assert 'найдено 2' in note and 'не найдено 1' in note and '9999' in note
    # кнопка пишет назначения в формат 5.8, подгруппы не трогает
    r = client.post(f'/api/projects/{pid}/groups', json={'changes': {w: {'group': 'Север'} for w in pick}})
    assert r.status_code == 200, r.text
    saved = projects.manifest(pid)['groups']
    assert all(saved[w]['group'] == 'Север' for w in pick)
    assert 'bulk' not in {t['id'] for t in run(client, pid, 'groups')['tables']}


def test_ranking_by_season_separate_tables(env):
    """Выгрузка по отдельным сезонам: свой рейтинг на каждый сезон, сводный остаётся."""
    client, pid, projects = env
    ps = periods(projects, pid)[:2]
    assert len(ps) == 2
    plain = run(client, pid, 'fund', kind='withdrawal', periods=ps)
    assert not [t for t in plain['tables'] if t['id'].startswith('ranking-season')]
    body = run(client, pid, 'fund', kind='withdrawal', periods=ps, by_season=True)
    data = projects.data(pid)
    d = data[DatasetKind.PRODUCTION]
    sheets = [t for t in body['tables'] if t['id'].startswith('ranking-season')]
    assert [t['title'] for t in sheets] == [f'Рейтинг · {p}' for p in ps]
    assert rows(table(body, 'ranking')).equals(rows(table(plain, 'ranking')))
    for t, p in zip(sheets, ps):
        want = group_analysis.ranking(d[d.kind.eq('withdrawal') & d.period.eq(p)], data.mapping)
        got = rows(t)
        assert got['Скважина'].tolist() == want['Скважина'].tolist()
        assert got['Объем_млн_м3'].astype(float).tolist() == pytest.approx(want['Объем_млн_м3'].astype(float).tolist())
    xlsx = client.post('/api/modules/fund/export', json={'project': pid, 'params': {'kind': 'withdrawal', 'periods': ps, 'by_season': True}, 'target': 'tables'})
    assert xlsx.status_code == 200
    from io import BytesIO
    from openpyxl import load_workbook
    names = load_workbook(BytesIO(xlsx.content)).sheetnames
    assert all(f'Рейтинг · {p}' in names for p in ps)


def test_ratio_a_to_b_by_well(env):
    """Сезон А делится на среднее по Б; нулевое среднее и отсутствие данных — пусто с причиной."""
    from atlas.modules import fund_ratio
    m = {
        'A': pd.DataFrame({'Группа': ['г', 'г', 'г'], 'Средний_тыс_м3_сут': [100., 5., 0.], 'Объем_млн_м3': [2., 1., 0.],
                           'Активных_дней': [10, 4, 0], 'Записей': [10, 4, 3], 'Нулевых': [0, 0, 3]}, index=['1', '2', '3']),
        'B1': pd.DataFrame({'Группа': ['г', 'г'], 'Средний_тыс_м3_сут': [50., 0.], 'Объем_млн_м3': [1., 0.],
                            'Активных_дней': [5, 0], 'Записей': [5, 2], 'Нулевых': [0, 2]}, index=['1', '2']),
        'B2': pd.DataFrame({'Группа': ['г'], 'Средний_тыс_м3_сут': [150.], 'Объем_млн_м3': [3.],
                            'Активных_дней': [15], 'Записей': [15], 'Нулевых': [0]}, index=['1']),
    }
    t = fund_ratio.ratio_table(m, 'A', ['B1', 'B2', 'A']).set_index('Скважина')
    assert t.at['1', 'Средний_тыс_м3_сут'] == pytest.approx(1.0)      # 100 / mean(50,150)
    assert t.at['1', 'Объем_млн_м3'] == pytest.approx(1.0)
    assert pd.isna(t.at['2', 'Средний_тыс_м3_сут']) and 'равно 0' in t.at['2', 'Примечание']   # деление на ноль
    assert pd.isna(t.at['3', 'Объем_млн_м3']) and 'нет записей в сезонах Б' in t.at['3', 'Примечание']
    assert t.at['1', 'Примечание'] == '«Нулевых записей»: среднее по Б равно 0'   # 0 / 0 — пусто с причиной, а не NaN-ошибка
    assert pd.isna(t.at['1', 'Нулевых'])


def test_ratio_in_fund_module(env):
    client, pid, projects = env
    ps = periods(projects, pid)[:3]
    assert len(ps) == 3
    well = rows(table(run(client, pid, 'fund', kind='withdrawal', periods=ps), 'ranking'))['Скважина'].iloc[0]
    body = run(client, pid, 'fund', kind='withdrawal', periods=ps, base=ps[2], against=ps[:2], ratio_well=well)
    t = rows(table(body, 'ratio'))
    assert well in t['Скважина'].tolist() and 'Средний_тыс_м3_сут' in t
    assert body['charts'] and body['charts'][0]['id'] == 'ratio-chart'
    assert 'ratio' not in {x['id'] for x in run(client, pid, 'fund', kind='withdrawal', periods=ps)['tables']}


def test_mean_cru_over_working_days_from_elpro():
    """Среднее КРУ — по всем значениям ЭЛПРО сезона; сутки без записи ЭЛПРО пропускаются, а не считаются нулём."""
    from atlas.modules import fund_ratio
    d = pd.to_datetime(['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-04'])
    prod = pd.DataFrame({'well': ['1'] * 4 + ['2'], 'date': list(d) + [d[0]], 'kind': 'withdrawal',
                         'q': [10., 20., 0., 30., 5.]})
    elpro = pd.DataFrame({'well': ['1', '1', '1'], 'date': [d[0], d[1], d[2]], 'kind': 'withdrawal', 'y': [40., 60., 100.]})
    got = fund_ratio.mean_cru(prod, elpro)
    assert got['1'] == pytest.approx(200 / 3)   # три суток ЭЛПРО (40, 60, 100); сутки 4 без ЭЛПРО не считаются нулём
    assert '2' not in got.index                 # у скважины 2 нет ЭЛПРО — значения нет
    assert fund_ratio.mean_cru(prod, None).empty


def test_fund_cru_column_with_elpro(env):
    client, pid, projects = env
    data = projects.data(pid)
    if DatasetKind.ELPRO not in data or data[DatasetKind.ELPRO].empty:
        pytest.skip('в демо-проекте нет ЭЛПРО')
    ps = periods(projects, pid)[:2]
    body = run(client, pid, 'fund', kind='withdrawal', periods=ps, by_season=True)
    assert 'КРУ_среднее' in rows(table(body, 'ranking')).columns


def test_ratio_includes_cru_metric():
    from atlas.modules import fund_ratio
    d = pd.to_datetime(['2025-01-01', '2026-01-01'])
    prod = pd.DataFrame({'well': ['1', '1'], 'date': d, 'kind': 'withdrawal', 'period': ['A', 'B'], 'q': [10., 10.]})
    elpro = pd.DataFrame({'well': ['1', '1'], 'date': d, 'kind': 'withdrawal', 'y': [80., 40.]})
    m = fund_ratio.season_metrics(prod, {}, ['A', 'B'], elpro)
    t = fund_ratio.ratio_table(m, 'A', ['B'], fund_ratio.METRICS + (fund_ratio.CRU_METRIC,)).set_index('Скважина')
    assert t.at['1', 'КРУ_среднее'] == pytest.approx(2.0)


def test_mean_cru_uses_all_elpro_values_in_season():
    """Баг: КРУ пустой, если сутки ЭЛПРО не совпали с сутками q > 0 в БД расходов. Среднее — по всем значениям ЭЛПРО в сезоне."""
    from atlas.modules import fund_ratio
    d = pd.to_datetime(['2025-01-01', '2025-01-10', '2025-01-20', '2025-02-01'])
    prod = pd.DataFrame({'well': ['1', '1', '2', '2'], 'date': d, 'kind': 'withdrawal', 'q': [10., 20., 5., 5.]})
    # ЭЛПРО скважины 1 — в сутки без расхода в БД; скважины 3 нет в эксплуатации сезона; вне сезона — не берём
    elpro = pd.DataFrame({'well': ['1', '1', '1', '3', '2'],
                          'date': pd.to_datetime(['2025-01-05', '2025-01-06', '2024-06-01', '2025-01-05', '2025-01-20']),
                          'kind': 'withdrawal', 'y': [40., 60., 99., 10., 70.]})
    got = fund_ratio.mean_cru(prod, elpro)
    assert got['1'] == pytest.approx(50.0)     # 40 и 60 внутри сезона, 99 из прошлого года не входит
    assert got['2'] == pytest.approx(70.0)
    assert '3' not in got.index                # скважина не участвует в рейтинге сезона


def test_mean_cru_skips_gap_between_selected_seasons():
    from atlas.modules import fund_ratio
    prod = pd.DataFrame({'well': '1', 'kind': 'withdrawal', 'period': ['A', 'A', 'B', 'B'], 'q': 1.,
                         'date': pd.to_datetime(['2024-01-01', '2024-03-01', '2025-01-01', '2025-03-01'])})
    elpro = pd.DataFrame({'well': '1', 'kind': 'withdrawal', 'y': [20., 100., 40.],
                          'date': pd.to_datetime(['2024-02-01', '2024-08-01', '2025-02-01'])})   # 08.2024 — межсезонье
    assert fund_ratio.mean_cru(prod, elpro)['1'] == pytest.approx(30.0)
