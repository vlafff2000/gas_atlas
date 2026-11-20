"""Проверка критериев на истории: только данные до даты, метрики по факту КР."""
from __future__ import annotations

import pandas as pd

from atlas import well_backtest as bt


def card(gdi_dates, end='30.04.2022'):
    return {'seasons': [{'kind': 'withdrawal', 'period': '2021-2022', 'end': end, 'start': '2021-11-01', 'volume': 1.0, 'days': 100, 'max_rate': 100.0, 'mean_rate': 80.0}],
            'gdi': [{'date': d, 'reliable': True} for d in gdi_dates], 'elpro': [], 'depression': {'limit': None}}


def run(cards, works, years=(2024,)):
    return bt.run(cards, works, {}, {}, None, list(years))


def test_future_gdi_is_not_used_and_ranking_hits_repaired_well():
    cards = {'A': card(['10.03.2024']), 'B': card(['15.05.2023'])}   # у A надёжное ГДИ появилось ПОСЛЕ 1.01.2024 и не должно считаться
    works = {'A': [{'year': 2024, 'type': 'КР'}], 'B': []}
    res = run(cards, works)
    y = res['years'][0]
    assert (y['wells'], y['repaired'], y['hits'], y['precision']) == (2, 1, 1, 1.0)
    gdi_old = next(m for m in res['mechanisms'] if m['mechanism'] == 'gdi_old')
    assert (gdi_old['repaired_hit'], gdi_old['other_hit']) == (1, 0)


def test_current_repair_type_tr_is_not_counted_and_wells_without_seasons_skipped():
    cards = {'A': card([]), 'C': card([], end='30.04.2025')}          # у C сезон закончился после даты — до неё данных нет
    works = {'A': [{'year': 2024, 'type': 'ТР'}], 'C': [{'year': 2024, 'type': 'КР'}]}
    res = run(cards, works)
    y = res['years'][0]
    assert y['wells'] == 1 and y['repaired'] == 0 and y['missing'] == 1 and y['precision'] is None


def test_empty_gives_note():
    res = run({}, {})
    assert res['years'][0]['wells'] == 0 and any('проверять не на чем' in n for n in res['notes'])


def test_backtest_tables_in_common_contract():
    from atlas import passport_blocks
    res = run({'A': card(['10.03.2024']), 'B': card(['15.05.2023'])}, {'A': [{'year': 2024, 'type': 'КР'}], 'B': []})
    tables = passport_blocks.backtest_tables(res)
    assert [t.id for t in tables] == ['passport-backtest-years', 'passport-backtest-mechanisms']
    assert tables[0].frame.iloc[0].precision == '100 %'


def test_api_backtest_runs_on_project(tmp_path):
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
    url = f'/api/projects/{pid}/passport/backtest'
    r = client.post(url, json={'years': [2023, 2024]})
    assert r.status_code == 200 and [y['year'] for y in r.json()['years']] == [2023, 2024] and r.json()['tables']
    assert client.post(url, json={'years': [1500]}).status_code == 400


def test_fund_candidates_rank_by_score_and_api_saves_operations(tmp_path):
    import sys
    from pathlib import Path
    from starlette.testclient import TestClient
    sys.path.insert(0, str(Path(__file__).parent))
    from _wells_data import make_project
    from atlas.api import create_app
    from atlas.projects import Projects
    rows = bt.candidates({'A': {'assess': [{'level': 'weak', 'weight': 1.0, 'manual': False, 'name': 'М', 'recommendation': 'р'}]},
                          'B': {'assess': [{'level': 'strong', 'weight': 1.0, 'manual': True, 'name': 'М', 'recommendation': 'р'}]}})
    assert [r['well'] for r in rows] == ['B', 'A'] and rows[0]['manual'] and rows[0]['score'] == 2.0
    projects = Projects(tmp_path)
    pid = make_project(projects)
    client = TestClient(create_app(projects))
    url = f'/api/projects/{pid}/passport/operations'
    assert client.post(url, json={'operations': {'sand': {'strong': 'Своя'}}}).status_code == 200
    assert client.post(url, json={'operations': {'нет': {'strong': 'x'}}}).status_code == 400
    assert client.post(f'/api/projects/{pid}/passport/fund', json={}).status_code == 200
    assert client.post(url, json={'reset': True}).status_code == 200


def test_summary_export_returns_excel_and_csv_of_screen_table(tmp_path):
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
    url = f'/api/projects/{pid}/passport/summary_export'
    rows = [{'well': '31', 'group': 'ГСП-1', 'score': 3.0, 'manual': False, 'mechanisms': 'Заполнение забоя (сильная)', 'recommendation': 'Промывка'}]
    xlsx = client.post(url, json={'kind': 'fund', 'data': {'rows': rows}, 'id': 'passport-fund', 'format': 'xlsx'})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b'PK'                      # книга Excel
    csv = client.post(url, json={'kind': 'fund', 'data': {'rows': rows}, 'id': 'passport-fund', 'format': 'csv'})
    assert csv.status_code == 200 and '31' in csv.content.decode('utf-8-sig') and 'Промывка' in csv.content.decode('utf-8-sig')
    assert client.post(url, json={'kind': 'fund', 'data': {'rows': []}, 'id': 'passport-fund', 'format': 'csv'}).status_code == 400
    assert client.post(url, json={'kind': 'нет', 'data': {}, 'id': 'x', 'format': 'csv'}).status_code == 400


def test_sand_evidence_reconstructed_on_date_and_labels_explain_well_years():
    from atlas import passport_blocks
    a = {**card([]), 'krs': {'priority': {'sand': '2021-2022, 2022-2023, 2023-2024'}}}     # к 1.01.2025 три ревизии с песком → приоритет 1, срочно
    b = {**card([]), 'krs': {'priority': {'sand': ''}}}
    res = run({'A': a, 'B': b}, {'A': [{'year': 2025, 'type': 'КР с заменой фильтра'}], 'B': []}, years=(2025,))
    sand = next(m for m in res['mechanisms'] if m['mechanism'] == 'sand')
    assert (sand['repaired_hit'], sand['repaired'], sand['other_hit']) == (1, 1, 0) and sand['strong_repaired'] == 1.0
    t = passport_blocks.backtest_tables(res)[1]
    assert 'скважино-лет' in t.columns[1].label and 'Скважино-год' in t.note
