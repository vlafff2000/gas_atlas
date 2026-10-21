"""Макеты конструктора в разделах: «Производительность скважин» — да, ГДИ и «Реагирование» — нет; общая функция для отчёта АН."""
import pytest
from starlette.testclient import TestClient

from atlas import registry
from atlas.api import create_app
from atlas.contract import BUILDER_LAYOUTS, Data, Note, Result
from atlas.domain import DatasetKind
from atlas.modules import builder
from atlas import builder_library as lib
from atlas.projects import Projects

BASE = dict(mode='individual', kind='withdrawal', wells=['31', '45'])
GROUPS = ['ГСП 2', 'ГСП 9']
FIXED = {'series': [{'dataset': 'production', 'y': 'q', 'wells': ['31']}], 'title': 'Дебит 31'}
CURRENT = {'series': [{'dataset': 'production', 'y': 'q', 'wells_mode': 'current'}], 'title': 'Скважина {скважина}'}
NO_SET = {'series': [{'dataset': 'plan', 'y': 'plan'}], 'title': 'План'}


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    for name, layout in (('Фикс', FIXED), ('Текущая', CURRENT), ('Без набора', NO_SET)):
        assert client.post(f'/api/projects/{pid}/builder/layouts', json={'name': name, 'layout': layout}).status_code == 200
    return client, pid, projects


def run(client, pid, module='production', **params):
    r = client.post(f'/api/modules/{module}/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def base(projects, pid):
    df = projects.data(pid)[DatasetKind.PRODUCTION]
    return {**BASE, 'periods': sorted(set(df[df.kind == 'withdrawal'].period))[-1:], 'groups': GROUPS}


def test_flag_only_in_production_and_options(env):
    client, pid, _ = env
    has = {m.spec.id for m in registry.modules().values() if any(p.name == BUILDER_LAYOUTS for p in m.spec.params)}
    assert 'production' in has and 'an_report' in has
    assert not has & {'gdi', 'gdi_trend', 'response'}
    p = next(p for p in registry.get('production').spec.params if p.name == BUILDER_LAYOUTS)
    assert p.kind == 'multi' and p.default == [] and p.section == 'Вид' and p.dynamic
    r = client.post('/api/modules/production/options', json={'project': pid, 'param': BUILDER_LAYOUTS, 'params': {}})
    assert r.status_code == 200 and r.json() == ['Без набора', 'Текущая', 'Фикс']


def test_empty_selection_is_as_before(env):
    client, pid, projects = env
    BASE = base(projects, pid)
    before = run(client, pid, **BASE)
    after = run(client, pid, builder_layouts=[], **BASE)
    assert before['charts'] == after['charts'] and not any(c['id'].startswith('builder-') for c in after['charts'])


def test_fixed_and_current_layouts_after_main_charts(env):
    client, pid, projects = env
    BASE = base(projects, pid)
    out = run(client, pid, builder_layouts=['Фикс', 'Текущая'], **BASE)
    ids = [c['id'] for c in out['charts']]
    assert ids[0] == 'production-curve' and sum(i.startswith('builder-') for i in ids) == 3     # фикс + по графику на 31 и 45
    assert [c['title'] for c in out['charts'] if c['id'].startswith('builder-')][1:] == ['Скважина 31', 'Скважина 45']
    assert ids[1:] == sorted(ids[1:], key=ids.index) and all(i.startswith('builder-') for i in ids[1:])


def test_current_limit_and_no_wells_note(env):
    client, pid, projects = env
    BASE = base(projects, pid)
    pdata = projects.data(pid)
    many = Result()
    lib.add_layout_charts(many, pdata, ['Текущая'], [str(n) for n in range(1, 40)], limit=3)
    assert len(many.charts) <= 3 and any('первые 3 скважин' in n.text for n in many.notes)
    groups = run(client, pid, **{**BASE, 'mode': 'groups'}, builder_layouts=['Текущая'])
    assert any('скважины в разделе не выбраны' in n['text'] for n in groups['notes'])


def test_missing_dataset_warns_without_loading_it(env):
    client, pid, projects = env
    BASE = base(projects, pid)
    out = run(client, pid, builder_layouts=['Без набора', 'Нет такого'], **BASE)
    texts = [n['text'] for n in out['notes']]
    assert any('«Без набора»' in t and 'нет данных набора' in t for t in texts)
    assert any('«Нет такого»' in t and 'не найден' in t for t in texts)
    assert registry.get('production').spec.needs == (DatasetKind.PRODUCTION,)
    assert registry.get('production').spec.optional == (DatasetKind.GDI, DatasetKind.ELPRO)


def test_current_row_over_group_dataset_warns():
    import pandas as pd
    plan = pd.DataFrame({'group': ['ГСП-1'] * 2, 'date': pd.to_datetime(['2025-01-01', '2025-02-01']), 'plan_volume': [1.0, 2.0], 'kind': 'withdrawal'})
    row = {'dataset': 'plan', 'y': 'plan_volume', 'wells_mode': 'current'}
    r = builder.build(Data({DatasetKind.PLAN: plan}), {'series': [row], 'current_well': '31'})
    assert not r.charts and any('по группам' in n.text and 'Текущая скважина' in n.text for n in r.notes)


def test_an_report_uses_shared_function(env):
    client, pid, _ = env
    out = run(client, pid, module='an_report', builder_layouts=['Фикс', 'Текущая'])
    assert sum(c['id'].startswith('builder-') for c in out['charts']) == 1
    assert any('«Текущая»' in n['text'] and 'не выбрана скважина' in n['text'] and 'рисунок пропущен' in n['text'] for n in out['notes'])
