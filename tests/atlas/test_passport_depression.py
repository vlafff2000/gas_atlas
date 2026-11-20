"""Депрессия по сезонам: обратный пересчёт по ГДИ, пределы по типу забоя, ручное главнее."""
import pandas as pd

from atlas import passport_depression as pd_


def gdi():
    return [{'date': '10.12.2024', 'reliable': True, 'a': 0.5, 'b': 0.002, 'q_max': 150.0}, {'date': '01.01.2020', 'reliable': False, 'a': 9, 'b': 9, 'q_max': 1}]


def seasons():
    return [{'kind': 'withdrawal', 'period': '2025-2026', 'mean_rate': 60.0, 'max_rate': 100.0},
            {'kind': 'injection', 'period': '2025', 'mean_rate': 5.0, 'max_rate': 5.0},
            {'kind': 'withdrawal', 'period': '2024-2025', 'mean_rate': 50.0, 'max_rate': 90.0}]


def pressure():
    return pd.DataFrame({'date': pd.to_datetime(['2024-10-20', '2025-10-25']), 'pressure': [100.0, 98.0]})


def test_depression_is_pressure_difference_not_square():
    dp2 = 0.5 * 100 + 0.002 * 100 * 100          # 70
    assert round(pd_.depression(100.0, 0.5, 0.002, 100.0), 4) == round(100 - (100 ** 2 - dp2) ** 0.5, 4)
    assert pd_.depression(10.0, 5.0, 1.0, 100.0) is None


def test_season_rows_status_by_limit_and_notes():
    rows = pd_.season_rows(seasons(), gdi(), pressure(), 4.1)
    assert [r['period'] for r in rows] == ['2024-2025', '2025-2026']      # только отбор, по порядку
    assert rows[0]['p_res'] == 100.0 and rows[0]['p_date'] == '20.10.2024' and rows[0]['note'] == 'по ГДИ 10.12.2024'
    assert 0.3 < rows[0]['dep_max'] < 0.5 and rows[0]['status'] == 'норма'
    assert pd_.season_rows(seasons(), gdi(), pressure(), 0.2)[0]['status'] == 'превышен'
    assert pd_.season_rows(seasons(), gdi(), pressure(), 0.32)[0]['status'] == 'близко'
    assert pd_.season_rows(seasons(), gdi(), pressure(), None)[0]['status'] == 'предел не задан'


def test_missing_gdi_or_pressure_is_a_note_not_zero():
    assert 'нет надёжного ГДИ' in pd_.season_rows(seasons(), [], pressure(), 4.1)[0]['note']
    far = pd.DataFrame({'date': pd.to_datetime(['2020-01-01']), 'pressure': [100.0]})
    r = pd_.season_rows(seasons(), gdi(), far, 4.1)[0]
    assert r['dep_max'] is None and 'пластового давления' in r['note'] and r['status'] == 'нет данных'
    big = [{'kind': 'withdrawal', 'period': '2024-2025', 'mean_rate': 100.0, 'max_rate': 200.0}]
    assert 'грубая' in pd_.season_rows(big, gdi(), pressure(), 4.1)[0]['note']


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
