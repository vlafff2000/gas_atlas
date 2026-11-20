"""Автоперебор критериев вывода в КРС: сетка вариантов, защита от подгонки, прерывание, применение вручную."""
from __future__ import annotations

import random
import time

from atlas import passport_assess, well_search as ws


def synthetic(seed=1):
    random.seed(seed)
    prep = {}
    for y in (2022, 2023, 2024, 2025):
        rows = []
        for _ in range(150):
            rep = random.random() < 0.1
            deps = [random.uniform(1, 6 if rep else 3.5) for _ in range(4)]       # у ушедших в КР депрессия выше предела чаще
            rows.append({'rep': rep, 'lv': {'bottom_fill': 0, 'sand': 0, 'gdi_old': 0}, 'dep': {'limit': 4.1, 'deps': deps}, 'el': {'high_share': random.uniform(0, 10), 'eff_change': None}})
        prep[y] = rows
    return prep


CUR = {'dep_min_dates': 2.0, 'elpro_high_share': 30.0, 'elpro_drop': -15.0}


def test_year_metrics_are_tie_aware():
    # все баллы равны: точность = доля ушедших в КР, «лучше случайного» = 1
    prec, lift = ws._year_metrics([1.0] * 10, [True] * 2 + [False] * 8)
    assert prec == 0.2 and abs(lift - 1.0) < 1e-9
    prec, lift = ws._year_metrics([3, 3, 0, 0, 0, 0], [True, True, False, False, False, False])
    assert prec == 1.0 and abs(lift - 3.0) < 1e-9


def test_search_finds_planted_depression_signal_and_holds_out_last_year():
    res = ws.search(synthetic(), CUR)
    assert res['fit_years'] == [2022, 2023, 2024] and res['test_years'] == [2025]
    best = res['rows'][0]
    assert best['variant']['dep_on'] and best['fit_lift'] > 1.5 and best['test_lift'] is not None
    assert any(r['current'] for r in res['rows']) and res['tried'] == len(ws.variants()) + 1
    assert all(r['in_target'] for r in res['rows'][:3])       # целевая доля срабатывания идёт первой, если такие варианты есть


def test_search_can_be_cancelled_and_reports_progress():
    seen = []
    state = {'n': 0}

    def cancelled():
        state['n'] += 1
        return state['n'] > 30

    res = ws.search(synthetic(), CUR, progress=lambda d, t: seen.append((d, t)), cancelled=cancelled)
    assert res['canceled'] and res['tried'] == 30 and seen and seen[-1][0] == 30


def test_single_year_has_no_holdout_note():
    res = ws.search({2024: synthetic()[2024]}, CUR)
    assert res['test_years'] == [] and any('проверки на отложенном годе нет' in n for n in res['notes'])


def test_weights_are_read_from_settings_and_change_score():
    from atlas import well_backtest as bt
    from atlas.well_assess import Evidence
    assert passport_assess.weights_of({'passport_weights': {'sand': 2, 'weak': 0.5, 'нет': 9}}) == {'sand': 2.0, 'weak': 0.5}
    ev = [Evidence('sand', 'strong', 'p', '', 1.0, ''), Evidence('gdi_old', 'weak', 'p', '', 1.0, '')]
    assert bt.score(ev) == 3.0 and bt.score(ev, {'sand': 2.0, 'weak': 0.5}) == 4.5


def test_api_search_job_apply_variant_and_export(tmp_path):
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
    url = f'/api/projects/{pid}/passport/search'
    assert client.post(url, json={'action': 'status'}).json()['state'] == 'idle'
    assert client.post(url, json={'action': 'start', 'years': [1500]}).status_code == 400
    assert client.post(url, json={'action': 'start', 'years': [2023, 2024]}).status_code == 200
    for _ in range(300):
        job = client.post(url, json={'action': 'status'}).json()
        if job['state'] != 'running':
            break
        time.sleep(0.2)
    assert job['state'] == 'done' and job['result']['tables'], job
    variant = job['result']['rows'][0]['variant']
    done = client.post(f'/api/projects/{pid}/passport/thresholds', json={'variant': variant, 'revision': None})
    assert done.status_code == 200
    assert client.post(f'/api/projects/{pid}/passport/thresholds', json={'variant': {**variant, 'weak': 99}}).status_code == 400
    xl = client.post(f'/api/projects/{pid}/passport/summary_export', json={'kind': 'search', 'data': job['result'], 'id': 'passport-search', 'format': 'xlsx'})
    assert xl.status_code == 200 and xl.content[:2] == b'PK'
