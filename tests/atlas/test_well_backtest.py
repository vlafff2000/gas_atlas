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
