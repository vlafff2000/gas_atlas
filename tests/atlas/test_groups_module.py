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
