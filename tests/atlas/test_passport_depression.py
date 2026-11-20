"""Депрессия по сезонам: обратный пересчёт по ГДИ, пределы по типу забоя, ручное главнее."""
import pandas as pd

from atlas import passport_depression as pd_


def gdi():
    return [{'date': '10.12.2024', 'reliable': True, 'a': 0.5, 'b': 0.002, 'q_max': 150.0}, {'date': '01.01.2020', 'reliable': False, 'a': 9, 'b': 9, 'q_max': 1}]


def seasons():
    return [{'kind': 'withdrawal', 'period': '2025-2026'}, {'kind': 'injection', 'period': '2025'}, {'kind': 'withdrawal', 'period': '2024-2025'}]


def pressure():
    """Замеры Рпл каждую неделю: в сезоне 2024-2025 пять дат, одна из них — день простоя скважины."""
    return pd.DataFrame({'date': pd.to_datetime(['2024-11-04', '2024-11-11', '2024-11-18', '2024-11-25', '2024-12-02', '2025-11-03']),
                         'pressure': [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]})


def daily():
    """Суточные расходы тыс. м³/сут: 18.11 — простой (ноль), 25.11 — нет записи; расход растёт, значит и депрессия."""
    dates = ['2024-11-04', '2024-11-11', '2024-11-18', '2024-12-02', '2025-11-03']
    return {'date': dates, 'volume': [60.0, 80.0, 0.0, 150.0, 70.0], 'hours': [24.0] * 5,
            'period': ['2024-2025', '2024-2025', '2024-2025', '2024-2025', '2025-2026']}


def test_depression_is_pressure_difference_not_square():
    dp2 = 0.5 * 100 + 0.002 * 100 * 100          # 70
    assert round(pd_.depression(100.0, 0.5, 0.002, 100.0), 4) == round(100 - (100 ** 2 - dp2) ** 0.5, 4)
    assert pd_.depression(10.0, 5.0, 1.0, 100.0) is None


def test_depression_on_each_pressure_date_only_when_well_worked():
    row = pd_.season_rows(seasons(), gdi(), pressure(), 4.1, daily())[0]
    assert [p['date'] for p in row['points']] == ['04.11.2024', '11.11.2024', '02.12.2024']      # простой (ноль) и дата без записи пропущены
    assert row['n'] == 3 and row['n_over'] == 0 and row['share_over'] == 0
    by_date = {p['date']: p for p in row['points']}
    assert by_date['04.11.2024']['p_res'] == 100.0 and by_date['02.12.2024']['q'] == 150.0
    assert row['dep_max'] == by_date['02.12.2024']['dep'] and row['p_date'] == '02.12.2024'      # максимум — на своей дате и со своим Рпл
    assert 'выше Qmax ГДИ' not in row['note'] and row['status'] in ('норма', 'близко')


def test_status_counts_dates_over_the_limit():
    deps = sorted(p['dep'] for p in pd_.season_rows(seasons(), gdi(), pressure(), 4.1, daily())[0]['points'])
    limit = (deps[0] + deps[1]) / 2                                   # выше предела две даты из трёх
    row = pd_.season_rows(seasons(), gdi(), pressure(), limit, daily())[0]
    assert (row['n'], row['n_over'], row['status']) == (3, 2, 'превышен') and round(row['share_over'], 2) == 0.67
    assert pd_.season_rows(seasons(), gdi(), pressure(), None, daily())[0]['status'] == 'предел не задан'
    near = pd_.season_rows(seasons(), gdi(), pressure(), deps[-1] / 0.95, daily())[0]
    assert near['n_over'] == 0 and near['status'] == 'близко'


def test_missing_gdi_pressure_or_work_is_a_note_not_zero():
    assert 'нет надёжного ГДИ' in pd_.season_rows(seasons(), [], pressure(), 4.1, daily())[0]['note']
    assert 'нет замеров' in pd_.season_rows(seasons(), gdi(), None, 4.1, daily())[0]['note']
    stopped = {**daily(), 'volume': [0.0] * 5}
    r = pd_.season_rows(seasons(), gdi(), pressure(), 4.1, stopped)[0]
    assert r['dep_max'] is None and 'скважина работала' in r['note'] and r['status'] == 'нет данных'


def test_limits_and_type_are_editable_manual_wins():
    types = pd_.types_of({})
    assert [(t['key'], t['limit']) for t in types] == [('reaming', 4.1), ('perf', 2.8)]
    custom = pd_.types_of({'depression_limits': [{'key': 'reaming', 'name': 'Расширка', 'limit': '3.5'}, {'bad': 1}]})
    assert custom == [{'key': 'reaming', 'name': 'Расширка', 'limit': 3.5}]
    assert pd_.well_type({'reaming', 'perf'}, types, None) == 'reaming' and pd_.well_type({'perf', 'filter'}, types, None) == 'perf'
    assert pd_.well_type({'filter'}, types, None) is None and pd_.well_type({'reaming'}, types, 'perf') == 'perf'
    assert pd_.well_type({'perf'}, custom, None) is None


def test_api_limits_and_type_override_saved(tmp_path):
    import sys
    from pathlib import Path
    from starlette.testclient import TestClient
    sys.path.insert(0, str(Path(__file__).parent))
    from _wells_data import make_project
    from atlas.api import create_app
    from atlas.projects import Projects
    projects = Projects(tmp_path)
    pid = make_project(projects)
    client = TestClient(create_app(projects))
    url = f'/api/projects/{pid}/passport/depression'
    assert client.post(url, json={'types': [{'key': 'reaming', 'name': 'Расширка', 'limit': 3.0}, {'key': 'perf', 'name': 'Перфорация', 'limit': 2.0}]}).status_code == 200
    assert client.post(url, json={'types': [{'key': 'a', 'limit': -1}]}).status_code == 400
    assert client.post(url, json={'well': '31', 'type': 'perf'}).status_code == 200
    assert client.post(url, json={'well': '31', 'type': 'bad'}).status_code == 400
    card = client.get(f'/api/projects/{pid}/passport/card', params={'well': '31'}).json()
    dep = card['depression']
    assert dep['type'] == 'perf' and dep['limit'] == 2.0 and [t['limit'] for t in dep['types']] == [3.0, 2.0]
    client.post(url, json={'well': '31', 'type': None})
    assert client.get(f'/api/projects/{pid}/passport/card', params={'well': '31'}).json()['depression']['type'] == dep['type_auto']


def test_evidence_and_chart_use_dates_over_limit():
    from atlas import passport_assess as pa
    from atlas import passport_blocks
    deps = sorted(p['dep'] for p in pd_.season_rows(seasons(), gdi(), pressure(), 4.1, daily())[0]['points'])

    def evidence(limit):
        rows = pd_.season_rows(seasons(), gdi(), pressure(), limit, daily())
        kw = dict(bottom_m=None, bottom_date=None, bottom_row=None, filter_bottom_m=None, krs={'works': [], 'priority': None}, seasons=[], gdi=[], elpro=[], today='01.01.2026')
        return [e for e in pa.collect(depression=rows[:1], **kw) if e.mechanism == 'depression'], rows
    (two,), _ = evidence((deps[0] + deps[1]) / 2)
    assert two.level == 'strong' and '2 из 3 дат' in two.reason
    (one,), rows = evidence((deps[1] + deps[2]) / 2)
    assert one.level == 'weak' and '1 из 3 дат' in one.reason                  # одна дата выше предела — слабая улика
    chart = passport_blocks.depression_chart({'rows': rows, 'limit': (deps[1] + deps[2]) / 2})
    assert [s.name for s in chart.series][:2] == ['Депрессия на дату замера', 'Выше предела'] and len(chart.series[0].x) == 4
