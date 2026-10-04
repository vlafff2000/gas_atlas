"""«План и факт по группам»: импорт плана через обычный загрузчик и сверка сумм с ручным расчётом."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from app.core.loader import load_file
from atlas.api import create_app
from atlas.domain import DatasetKind
from atlas.modules import plan_fact
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    return client, pid, projects


def test_plan_file_is_recognised_and_normalised(tmp_path):
    path = tmp_path / 'plan.csv'
    path.write_text('Группа;Месяц;Режим;План, тыс. м³\nГСП-1;15.05.2025;закачка;150000\nГСП-1;01.06.2025;закачка;220000\n'
                    ';01.06.2025;закачка;5\nГСП-2;01.06.2025;отбор;-1\n', encoding='utf-8')
    res = load_file(str(path), delimiter=';')
    plan = res.frames['plan']
    assert list(plan.group) == ['ГСП-1', 'ГСП-1']
    assert list(plan.plan_volume) == [150.0, 220.0]                    # тыс. м³ → млн м³
    assert list(plan.date) == [pd.Timestamp('2025-05-01'), pd.Timestamp('2025-06-01')]
    assert set(plan.kind) == {'injection'}
    assert res.rejected == 2                                            # без группы и отрицательный план


def test_compare_matches_manual_sums(env):
    client, pid, projects = env
    data = projects.data(pid)
    prod = data[DatasetKind.PRODUCTION]
    kind = 'withdrawal'
    month = prod[prod.kind.eq(kind)].date.dt.to_period('M').dt.to_timestamp().iloc[0]
    active = prod[prod.kind.eq(kind) & prod.date.dt.to_period('M').dt.to_timestamp().eq(month) & prod.q.gt(0)]
    groups = sorted({data.mapping[str(w)]['group'] for w in active.well.unique()})[:2]
    assert len(groups) == 2
    plan = pd.DataFrame({'group': groups, 'date': month, 'kind': kind, 'plan_volume': [100.0, 50.0]})
    projects.store.commit(pid, frames={**{k.value: v for k, v in data.raw.items()
                                          if k.value in projects.manifest(pid)['tables']}, 'plan': plan},
                          action='План')
    data = projects.data(pid)
    d = plan_fact.compare(data[DatasetKind.PRODUCTION], data[DatasetKind.PLAN], data.mapping, kind, data.settings)
    assert len(d) == 2
    p = data[DatasetKind.PRODUCTION]
    p = p[p.kind.eq(kind) & p.date.dt.to_period('M').dt.to_timestamp().eq(month)]
    for g, row in zip(groups, d.itertuples()):
        wells = [w for w in p.well.unique() if data.mapping[str(w)]['group'] == g]
        assert row.fact == pytest.approx(p[p.well.isin(wells)].q.sum() / 1e6)
    r = client.post('/api/modules/plan_fact/run', json={'project': pid, 'params': {'kind': kind, 'periods': list(d.period.unique())}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c['id'].split('-')[2] for c in body['charts']] == ['groups', 'months']
    bars = body['charts'][0]['series']
    assert [s['name'] for s in bars] == ['План', 'Факт'] and list(bars[0]['y']) == [100.0, 50.0]


def matrix_book(path, title):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Закачка'
    rows = [[title], ['Номер ГСП', 'Май', 'Июнь', 'Июль', 'ВСЕГО', '%'], [None, 27, 30, 31, 88, None],
            ['ГСП 1', 150, 220, 220, 590, 14], ['ГСП 2', 140, 220, None, 360, 14], ['ВСЕГО', 290, 440, 220, 950, 100]]
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_matrix_plan_groups_by_months(tmp_path):
    path = tmp_path / 'plan.xlsx'
    matrix_book(path, 'Таблица 2.4 – Распределение объемов закачки газа по месяцам и ГСП в сезоне 2025 г.')
    res = load_file(str(path))
    plan = res.frames['plan'].sort_values(['group', 'date']).reset_index(drop=True)
    assert list(plan.group) == ['ГСП 1'] * 3 + ['ГСП 2'] * 2
    assert list(plan.date.dt.strftime('%Y-%m')) == ['2025-05', '2025-06', '2025-07', '2025-05', '2025-06']
    assert list(plan.plan_volume) == [150, 220, 220, 140, 220] and set(plan.kind) == {'injection'}
    assert res.rejected == 0


def test_matrix_plan_without_year_is_explained(tmp_path):
    path = tmp_path / 'plan.xlsx'
    matrix_book(path, 'Технологическая карта')
    with pytest.raises(ValueError, match='нет года'):
        load_file(str(path))
