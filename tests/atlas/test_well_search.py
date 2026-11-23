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
    for y, rows in prep.items():
        for i, r in enumerate(rows):
            r['well'] = f'W{i}'
            r['perf'] = {'prev': 10.0, 'next': 7.0, 'change': -30.0} if r['dep']['deps'][0] > 3.5 else {'prev': 10.0, 'next': 10.0, 'change': 0.0}
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
    assert all(r['stable'] for r in res['rows'][:3])           # первыми идут устойчивые к сдвигу порога, а не «целевая доля 5–10 %»


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


def test_sorting_does_not_use_target_share_and_stability_is_reported():
    res = ws.search(synthetic(), CUR)
    rows = [r for r in res['rows'] if not r['current']]
    assert all(r['stability'] is not None for r in res['rows'] if r['variant']['dep_on'] or r['variant']['el_on'])
    stable_flags = [r['stable'] for r in rows]
    assert stable_flags == sorted(stable_flags, reverse=True)            # устойчивые идут первыми
    assert not all(r['in_target'] for r in rows[:3]) or any(not r['in_target'] for r in rows)
    assert not any('5–10' in n for n in res['notes'])


def test_review_has_reasons_split_by_repair_and_real_drop():
    prep = synthetic()
    v = {**ws.variants()[0], 'dep_on': True, 'dep_min_dates': 1, 'dep_factor': 0.8, 'el_on': False, 'weak': 1.0, 'mults': {}}
    rv = ws.review(v, prep, [2024, 2025])
    assert rv['flagged'] == rv['flagged_repaired'] + rv['flagged_not_repaired'] and rv['flagged_not_repaired'] > 0     # вторая группа — кандидаты вне плана КР
    assert all('депрессия' in e['reasons'] for e in rv['entries'])
    assert rv['perf_flagged_not_repaired']['n'] > 0 and rv['perf_flagged_not_repaired']['drop_share'] is not None
    assert 'persistence' not in rv                                   # «те же скважины из года в год» не цель и не показывается


def test_search_tables_show_reasons_and_split():
    from atlas import passport_blocks
    res = ws.search(synthetic(), CUR)
    tables = passport_blocks.search_tables(res)
    assert [t.id for t in tables] == ['passport-search', 'passport-search-wells']
    assert 'ремонтировались / нет' in ' '.join(c.label for c in tables[0].columns)
    assert set(tables[1].frame['kr']) <= {'ремонтировали', 'без КР'} and (tables[1].frame['reasons'] != '').all()


def test_perf_change_and_last_kr_from_card():
    import pandas as pd
    from atlas import well_backtest as bt
    card = {'seasons': [{'kind': 'withdrawal', 'end': '30.04.2023', 'mean_rate': 100.0}, {'kind': 'withdrawal', 'end': '30.04.2024', 'mean_rate': 80.0},
                        {'kind': 'injection', 'end': '30.09.2023', 'mean_rate': 1.0}],
            'krs': {'works': [{'year': 2020, 'type': 'КР'}, {'year': 2023, 'type': 'ТР'}]}}
    got = bt.perf_change(card, pd.Timestamp(2024, 1, 1))
    assert got and abs(got['change'] + 20.0) < 1e-9
    assert bt.perf_change(card, pd.Timestamp(2020, 1, 1)) is None and abs(bt.perf_last(card) + 20.0) < 1e-9 and bt.last_kr(card) == 2020


def test_sweep_picks_stable_sets_not_target_share():
    from atlas import well_backtest as bt
    prep = synthetic()
    feats = {y: {r['well']: {'dep': r['dep'], 'elpro': r['el']} for r in rows} for y, rows in prep.items()}
    fact = {y: {r['well'] for r in rows if r['rep']} for y, rows in prep.items()}
    res = bt.sweep(feats, fact, {'dep_min_dates': 2.0, 'elpro_high_share': 30.0, 'elpro_drop': -15.0})
    rows = res['depression']
    assert rows and all('stability' in r for r in rows) and any(r['current'] for r in rows)
    flags = [bool(r.get('stable')) for r in rows if not r['current']]
    assert flags == sorted(flags, reverse=True)


def test_reset_repair_restarts_observation_window_incl_flush():
    import pandas as pd
    from atlas import well_backtest as bt
    card = {'seasons': [{'kind': 'withdrawal', 'period': '2022-2023', 'end': '30.04.2023', 'mean_rate': 100.0},
                        {'kind': 'withdrawal', 'period': '2023-2024', 'end': '30.04.2024', 'mean_rate': 60.0}]}
    filt, flush = [{'year': 2023, 'type': 'Замена фильтра'}], [{'year': 2023, 'type': 'Промывка колтюбингом'}]
    assert bt.reset_years(filt) == [2023] and bt.reset_years(flush) == [2023]          # промывка поднимает продуктивность: окно заново
    assert bt.reset_years([{'year': 2023, 'type': 'Колтюбинг с СКО'}]) == []
    cut = pd.Timestamp(2023, 12, 1)
    assert bt.perf_change(card, cut, bt.reset_years(filt))['reset'] is True          # до и после замены фильтра вслепую не сравниваем
    assert bt.perf_change(card, cut, bt.reset_years(flush))['reset'] is True
    kw = dict(bottoms=None, filter_bottom_m=None, pressure=None, limit=None)
    for works, expect in ((filt, 0), (flush, 0), ([], 1)):
        f: dict = {}
        bt.evidence_at({**card, 'elpro': [{'period': '2022-2023', 'verdict': 'внимание', 'reason': 'x', 'high_share': 80.0, 'eff_change': None}]},
                       pd.Timestamp(2024, 1, 1), works=works, features=f, **kw)
        assert ('elpro' in f) == bool(expect)                                           # сезон до замены фильтра в уликах не участвует


def test_review_skips_perf_across_reset_repair():
    prep = {2024: [{'well': '1', 'rep': False, 'lv': {'bottom_fill': 2, 'sand': 0, 'gdi_old': 0}, 'dep': None, 'el': None, 'perf': {'change': -40.0, 'reset': True}},
                   {'well': '2', 'rep': False, 'lv': {'bottom_fill': 2, 'sand': 0, 'gdi_old': 0}, 'dep': None, 'el': None, 'perf': {'change': -20.0, 'reset': False}}]}
    v = {**ws.variants()[0], 'dep_on': False, 'el_on': False, 'weak': 1.0, 'mults': {}}
    rv = ws.review(v, prep, [2024])
    assert rv['perf_flagged_not_repaired']['n'] == 1 and rv['perf_reset_skipped'] == 1
