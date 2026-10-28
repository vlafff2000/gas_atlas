"""Паритет с 5.8: «Производительность скважин» и «Гистограммы» считают и рисуют то же, что atlas.engine.modules."""
import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.engine.core.demo import demo_frames
from atlas.engine.modules import charts as legacy_charts
from atlas.engine.modules import group_analysis
from atlas.engine.modules import production as legacy
from atlas.api import create_app
from atlas.projects import Projects


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    return client, pid, projects


def run(client, pid, module='production', **params):
    r = client.post(f'/api/modules/{module}/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def frame(projects, pid):
    from atlas.domain import DatasetKind
    return projects.data(pid)[DatasetKind.PRODUCTION]


def table(body, tid):
    return next(t for t in body['tables'] if t['id'] == tid)


BASE = dict(kind='withdrawal', groups=['Группа 1', 'Группа 2'], wells=['31', '45'], periods=['2025-2026'])


def groups(client, pid):
    return client.post('/api/modules/production/options', json={'project': pid, 'param': 'groups', 'params': {}}).json()


def test_dynamic_options_cascade(env):
    client, pid, projects = env
    gs = groups(client, pid)
    assert gs and all(isinstance(g, str) for g in gs)
    ask = lambda name, **p: client.post('/api/modules/production/options',
                                        json={'project': pid, 'param': name, 'params': p}).json()
    periods = ask('periods', kind='withdrawal')
    df = frame(projects, pid)
    from atlas.engine.core.config import ordered
    assert periods == ordered(df[df.kind == 'withdrawal'].period)          # естественный порядок, как в 5.8
    assert set(ask('periods', kind='injection')) == set(df[df.kind == 'injection'].period)
    everyone = ask('wells', groups=gs)
    assert everyone == ['31', '45', '70', '73', '89', '132', '540', '541']
    assert ask('wells', groups=[]) == []
    one = ask('wells', groups=gs[:1])
    assert 0 < len(one) < len(everyone)
    bad = client.post('/api/modules/production/options', json={'project': pid, 'param': 'mode', 'params': {}})
    assert bad.status_code == 404


def pick(client, pid, projects, kind='withdrawal', n_periods=2):
    gs = groups(client, pid)
    df = frame(projects, pid)
    ps = sorted(set(df[df.kind == kind].period))[-n_periods:]
    return dict(kind=kind, groups=gs, wells=['31', '45', '540'], periods=ps)


@pytest.mark.parametrize('view,xmode', [('curve', 'cumulative'), ('time', 'date')])
def test_curve_matches_58_figure(env, view, xmode):
    client, pid, projects = env
    p = pick(client, pid, projects)
    body = run(client, pid, view=view, **p)
    df = frame(projects, pid)
    ws = legacy.rank_wells(df, p['kind'], p['periods'], p['wells'], 'number')
    fig = legacy_charts.production_curve(df, p['kind'], p['periods'], ws, xmode)
    chart = body['charts'][0]
    assert chart['title'] == 'Скважины №31, 45, 540' and len(chart['series']) == len(fig.data)
    # ≈ 5.8: у нескольких скважин цвет — скважина, стиль линии — период (легенда рядами «Скважина» / «Период»)
    well_color = legacy_charts.well_colors(ws)
    for old, new in zip(fig.data, chart['series']):
        well, period = old.name[len('№ '):].split(' · ')
        assert old.name == new['name'] and new['color'] == well_color[well]
        assert new['dash'] == legacy_charts.DASH[p['periods'].index(period)] and new['kind'] == 'line'
        assert new['facets'] == {'Скважина': '№ ' + well, 'Период': period}
        y_old = np.asarray(old.y, float); y_new = np.array([np.nan if v is None else v for v in new['y']])
        assert np.array_equal(y_old, y_new, equal_nan=True)
        if xmode == 'cumulative':
            assert np.array_equal(np.asarray(old.x, float), np.asarray(new['x'], float))
        else:    # даты: ISO-строки, а не наносекунды
            assert new['x'] == pd.to_datetime(list(old.x)).strftime('%Y-%m-%d').tolist()
        assert len(new['ids']) == len(new['labels']) == len(new['y'])
    if xmode == 'date':      # смена режима и ГДИ — отметки на оси времени
        kinds = {e['kind'] for e in chart['events']}
        assert 'regime' in kinds and all(chart['x'] and e['x'] for e in chart['events'])
    else:                    # на оси накопленного объёма — только ГДИ, число вместо даты
        assert chart['events'] and all(e['kind'] == 'gdi' and isinstance(e['x'], float) for e in chart['events'])
        assert all(0 <= e['x'] <= max(chart['series'][0]['x']) * 1.01 for e in chart['events'][:1])
    assert chart['y']['from_zero'] and (chart['x']['step'] is None or chart['x']['step'] > 0)
    assert chart['x']['scale'] == ('time' if xmode == 'date' else 'value')


def test_single_period_uses_well_colors_and_names(env):
    client, pid, projects = env
    p = pick(client, pid, projects, n_periods=1)
    body = run(client, pid, **{**p, 'wells': ['31']})
    chart = body['charts'][0]
    assert chart['title'] == 'Скважина №31' and chart['series'][0]['name'] == p['periods'][0]
    assert chart['series'][0]['dash'] == 'solid' and chart['series'][0]['color'] == '#dc3545'


def test_averages_match_legacy_and_ranking(env):
    client, pid, projects = env
    p = pick(client, pid, projects)
    df = frame(projects, pid)
    for direction in ('number', 'desc', 'asc'):
        body = run(client, pid, direction=direction, **p)
        ws = legacy.rank_wells(df, p['kind'], p['periods'], p['wells'], direction)
        assert body['charts'][0]['title'] == 'Скважины №' + ', '.join(ws)
        theirs = legacy.averages(df, p['kind'], p['periods'], ws)
        t = table(body, 'averages')
        cols = [c['key'] for c in t['columns']]
        ours = pd.DataFrame(dict(zip(cols, t['rows'])))
        assert ours.well.tolist() == theirs.well.tolist() and ours.period.tolist() == theirs.period.tolist()
        assert np.allclose(ours.value.astype(float), theirs.value.astype(float), equal_nan=True)
        assert ours.active.tolist() == theirs.active.tolist() and np.allclose(ours.volume, theirs.volume, equal_nan=True)
    assert table(run(client, pid, **p), 'averages')['collapsed']


def test_nothing_selected_is_a_note(env):
    client, pid, _ = env
    body = run(client, pid, kind='withdrawal', groups=[], wells=[], periods=[])
    assert not body['charts'] and body['notes'][0]['text'] == 'Выберите скважины и периоды.'
    assert 'Выберите группы' in run(client, pid, mode='groups', groups=[], periods=[])['notes'][0]['text']


@pytest.mark.parametrize('metric', ['daily', 'cumulative', 'active'])
def test_group_totals_match_58(env, metric):
    client, pid, projects = env
    p = pick(client, pid, projects)
    df, mapping = frame(projects, pid), projects.data(pid).mapping
    overlay = ['31', '45']
    body = run(client, pid, mode='groups', metric=metric, overlay=overlay, **p)
    assert len(body['charts']) == len(p['groups'])
    group = p['groups'][0]
    fig = group_analysis.figure(df, mapping, group, p['kind'], p['periods'], overlay, metric)
    chart = body['charts'][0]
    assert chart['title'] == fig.layout.title.text == f'Группа {group}'
    totals_old = [t for t in fig.data if t.name.startswith('Сумма')]
    totals_new = [s for s in chart['series'] if s['name'].startswith('Сумма')]
    assert [t.name for t in totals_old] == [s['name'] for s in totals_new] and totals_new
    for old, new in zip(totals_old, totals_new):
        assert np.array_equal(np.asarray(old.y, float), np.array([np.nan if v is None else v for v in new['y']]), equal_nan=True)
        assert old.line.color == new['color'] and new['width'] == 3.0
    assert len(chart['series']) == len(fig.data)
    assert all(isinstance(v, str) and len(v) == 10 for s in totals_new for v in s['x'] if v is not None)
    daily, _ = group_analysis.daily(df, mapping, group, p['kind'], p['periods'])
    t = table(body, f'group-{group}')
    assert t['count'] == len(daily) and t['collapsed']
    cols = [c['key'] for c in t['columns']]
    ours = pd.DataFrame(dict(zip(cols, t['rows'])))
    for column in ('total', 'observed', 'active', 'cumulative', 'coverage', 'expected'):
        assert np.allclose(ours[column].astype(float), daily[column].astype(float), equal_nan=True), column
    assert ours.period.tolist() == daily.period.tolist()


def test_group_total_ignores_overlay(env):
    client, pid, projects = env
    p = pick(client, pid, projects)
    a = run(client, pid, mode='groups', overlay=[], **p)['charts'][0]['series']
    b = run(client, pid, mode='groups', overlay=['31', '45'], **p)['charts'][0]['series']
    assert [s['y'] for s in a if s['name'].startswith('Сумма')] == [s['y'] for s in b if s['name'].startswith('Сумма')]
    assert len(b) > len(a)


@pytest.mark.parametrize('axis,size', [('well', 'Авто'), ('period', 'Авто'), ('well', '10'), ('well', 'Все')])
def test_histograms_match_58(env, axis, size):
    client, pid, projects = env
    p = pick(client, pid, projects)
    p['wells'] = ['31', '45', '70', '73', '89', '132', '540', '541']
    body = run(client, pid, 'histograms', axis=axis, hist_size=size, **p)
    df = frame(projects, pid)
    ws = legacy.rank_wells(df, p['kind'], p['periods'], p['wells'], 'number')
    chunk = 10 if size in ('Авто', '10') else len(ws)
    parts = [ws[i:i + chunk] for i in range(0, len(ws), chunk)]
    assert len(body['charts']) == len(parts)
    for part, chart in zip(parts, body['charts']):
        fig = legacy_charts.histogram(df, p['kind'], p['periods'], part, axis)
        assert len(fig.data) == len(chart['series']) and chart['x']['scale'] == 'category'
        assert chart['x']['categories'] == (part if axis == 'well' else p['periods'])
        for old, new in zip(fig.data, chart['series']):
            assert old.name == new['name'] and old.marker.color == new['color'] and new['kind'] == 'bar'
            assert list(old.x) == new['x']
            assert np.array_equal(np.asarray(old.y, float), np.array([np.nan if v is None else v for v in new['y']]), equal_nan=True)


def test_exclusion_roundtrip_changes_curve_and_averages(env):
    client, pid, projects = env
    p = pick(client, pid, projects, n_periods=1)
    p['wells'] = ['31']
    body = run(client, pid, **p)
    series = body['charts'][0]['series'][0]
    j = next(i for i, v in enumerate(series['ids']) if v and series['y'][i] and series['y'][i] > 0)
    target = series['ids'][j]
    assert target.startswith('production:')
    before = dict(zip(*[[c['key'] for c in table(body, 'averages')['columns']], table(body, 'averages')['rows']]))
    r = client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'production', 'add': [target],
                                                             'reason': 'Исключено кликом на графике'})
    assert r.status_code == 200 and r.json()['added'] == 1
    after_body = run(client, pid, **p)
    assert after_body['charts'][0]['series'][0]['y'][j] is None            # дыра, а не ноль
    after = dict(zip(*[[c['key'] for c in table(after_body, 'averages')['columns']], table(after_body, 'averages')['rows']]))
    assert after['active'][0] == before['active'][0] - 1 and after['volume'][0] < before['volume'][0]
    points = table(after_body, 'points')
    k = points['action']['ids'].index(target)
    assert points['action']['checked'][k] is True and points['action']['checked_column'] == '_excluded'
    undo = client.post(f'/api/projects/{pid}/exclusions/undo', json={})
    assert undo.json()['removed'] == 1
    assert run(client, pid, **p)['charts'][0]['series'][0]['y'][j] == series['y'][j]


def test_saved_panels_use_58_keys(env):
    client, pid, projects = env
    p = pick(client, pid, projects)
    for module, key in (('production', 'prod'), ('histograms', 'hist')):
        for panel in (0, 1):
            r = client.post(f'/api/projects/{pid}/state/{module}', json={'params': {**p, 'wells': ['31']}, 'panel': panel})
            assert r.status_code == 200, r.text
            saved = projects.manifest(pid)['settings']['panels'][f'{key}_{panel}']
            assert saved['wells'] == ['31'] and saved['kind'] == 'withdrawal' and saved['periods'] == p['periods']
            back = client.get(f'/api/projects/{pid}/state/{module}', params={'panel': panel}).json()
            assert back['panel']['wells'] == ['31']
    assert projects.manifest(pid)['settings']['panels']['hist_1']['histaxis'] == 'well'
    # старое название: гистограммы читают prod_N, если hist_N ещё нет
    store = projects.store
    m = store.manifest(pid)
    cfg = {**m['settings'], 'panels': {'prod_0': {'wells': ['45'], 'periods': p['periods'], 'groups': p['groups']}}}
    store.commit(pid, settings=cfg, expected=m['revision'], action='тест')
    assert client.get(f'/api/projects/{pid}/state/histograms').json()['panel']['wells'] == ['45']


def test_chart_exports_for_bars_and_lines(env):
    client, pid, projects = env
    p = pick(client, pid, projects)
    for module, extra, chart_id, fmt in (('production', {'view': 'time'}, 'production-curve', 'svg'),
                                         ('production', {'view': 'curve'}, 'production-curve', 'png'),
                                         ('histograms', {'axis': 'period'}, 'hist-histogram-1', 'pdf'),
                                         ('histograms', {'axis': 'well'}, 'hist-histogram-1', 'png')):
        params = {**p, **extra}
        r = client.post(f'/api/modules/{module}/export', json={'project': pid, 'params': params, 'target': 'chart',
                                                               'id': chart_id, 'format': fmt, 'dpi': 150})
        assert r.status_code == 200, (module, extra, r.text)
        assert len(r.content) > 1000


def test_table_csv_like_58(env):
    client, pid, projects = env
    p = pick(client, pid, projects)
    r = client.post('/api/modules/production/export', json={'project': pid, 'params': p, 'target': 'tables',
                                                            'id': 'averages', 'format': 'csv'})
    assert r.status_code == 200 and r.content.startswith(b'\xef\xbb\xbf')       # BOM для Excel
    head, first = r.content.decode('utf-8-sig').splitlines()[:2]
    assert head.startswith('Скважина;Период;Средний расход, тыс. м³/сут;') and first.count(';') == 6
    assert ',' in first.split(';')[2]                                               # десятичная запятая
    many = client.post('/api/modules/production/export', json={'project': pid, 'params': p, 'target': 'tables',
                                                               'format': 'csv'})
    assert many.status_code == 400


def test_summary_strip_and_legend_facets(env):
    client, pid, projects = env
    p = pick(client, pid, projects)
    body = run(client, pid, view='time', **p)
    stats = {s['label']: s['value'] for s in body['summary']}
    assert stats['Скважин'] == '3' and stats['Режим'] == 'Отбор' and stats['Исключено точек'] == '0'
    assert stats['Периоды'] == f"{p['periods'][0]} – {p['periods'][-1]}"
    # несколько скважин и периодов: легенда рядами «Скважина» и «Период»
    facets = {tuple(sorted(s['facets'].items())) for s in body['charts'][0]['series']}
    assert len(facets) == len(body['charts'][0]['series']) and all(s['facets'] for s in body['charts'][0]['series'])
    # события — даты смены режима внутри периода графика
    dates = [e['x'] for e in body['charts'][0]['events']]
    assert dates and all(e['kind'] in ('regime', 'gdi') for e in body['charts'][0]['events'])
    assert min(dates) >= body['charts'][0]['series'][0]['x'][0][:4]


def test_gdi_events_on_cumulative_axis():
    import numpy as np
    import pandas as pd
    from atlas.contract import Event, _chart_json, Chart, Axis
    from atlas.modules._events import on_cumulative
    dates = pd.date_range('2024-01-01', periods=10)
    data = pd.DataFrame({'date': dates, 'period': 'A', 'well': '1', 'cumulative': np.arange(10) * 1.5})
    ev = [Event(pd.Timestamp('2024-01-04'), 'ГДИ · № 1', 'gdi', '1'), Event(pd.Timestamp('2025-01-01'), 'вне', 'gdi', '1')]
    out = on_cumulative(ev, data)
    assert [(e.x, e.label) for e in out] == [(4.5, 'ГДИ · № 1')]       # вне показанного сезона — без отметки
    chart = Chart('c', '', Axis('Накопленный'), Axis('Q'), events=out)
    assert _chart_json(chart)['events'][0]['x'] == 4.5


def test_group_share_charts(env):
    """Новые виды группы: доли дают 100 %, Парето заканчивается на 100 %, ось объекта числовая и растёт."""
    client, pid, projects = env
    p = pick(client, pid, projects)
    p['groups'] = p['groups'][:1]
    for metric in ('shares', 'hybrid', 'pareto', 'vs_object'):
        assert run(client, pid, mode='groups', metric=metric, **p)['charts'], metric
    shares = run(client, pid, mode='groups', metric='shares', **p)['charts'][0]['series']
    last = [s['y'][-1] for s in shares if s['y'] and s['y'][-1] is not None]
    assert abs(sum(last) - 100 * len(p["periods"])) < 1e-3   # стопка на каждый период
    pareto = run(client, pid, mode='groups', metric='pareto', **p)['charts'][0]['series'][1]
    assert abs(pareto['y'][-1] - 100) < 1e-9
    chart = run(client, pid, mode='groups', metric='daily', gx='object', **p)['charts'][0]
    assert chart['x']['scale'] == 'value'
    xs = [v for v in chart['series'][0]['x'] if v is not None]
    assert xs == sorted(xs)


def test_group_x_axis_works_for_every_line_metric(env):
    """Ось X «накопленный объем» не игнорируется: меняются ось и значения X у суточного, накопленного, работающих, доли."""
    client, pid, projects = env
    p = pick(client, pid, projects)
    p['groups'] = p['groups'][:1]
    for metric in ('daily', 'cumulative', 'active', 'share'):
        by_date = run(client, pid, mode='groups', metric=metric, gx='date', **p)['charts'][0]
        by_object = run(client, pid, mode='groups', metric=metric, gx='object', **p)['charts'][0]
        assert by_date['x']['scale'] == 'time' and by_object['x']['scale'] == 'value', metric
        xs = [v for v in by_object['series'][0]['x'] if v is not None]
        assert xs == sorted(xs), metric
    own = run(client, pid, mode='groups', metric='daily', gx='group', **p)['charts'][0]
    assert own['x']['label'] == 'Накопленный объем группы'
    assert run(client, pid, mode='groups', metric='cumulative', gx='group', **p)['charts'][0]['x']['label'] == \
        'Накопленный объем объекта'


def test_groups_overlay_on_one_plane(env):
    """Режим «Все группы на одном графике»: один график, цвет — группа, значения те же, что на отдельных графиках."""
    client, pid, projects = env
    p = pick(client, pid, projects)
    assert len(p['groups']) >= 2
    for metric in ('daily', 'cumulative', 'active', 'share'):
        for gx in ('date', 'object'):
            one = run(client, pid, mode='groups', metric=metric, gx=gx, layout='overlay', **p)
            apart = run(client, pid, mode='groups', metric=metric, gx=gx, layout='separate', **p)
            assert len(one['charts']) == 1 and len(apart['charts']) == len(p['groups'])
            names = {s['facets']['Группа'] for s in one['charts'][0]['series']}
            assert names == set(p['groups'])
            expected = sum(len(c['series']) for c in apart['charts'])
            assert len(one['charts'][0]['series']) == expected, (metric, gx)
            first = next(s for s in one['charts'][0]['series'] if s['facets']['Группа'] == p['groups'][0])
            ref = apart['charts'][0]['series'][0]
            assert first['y'] == ref['y'] and first['x'] == ref['x']
    # виды без наложения строятся по группам, с пояснением
    body = run(client, pid, mode='groups', metric='pareto', layout='overlay', **p)
    assert len(body['charts']) == len(p['groups'])


@pytest.mark.parametrize('xmode', ['date', 'object'])
def test_object_seasons_one_curve_per_season(env, xmode):
    """Режим «Объект по сезонам»: одна кривая на сезон, сумма по всем скважинам объекта, без выбора групп."""
    client, pid, projects = env
    df = frame(projects, pid)
    periods = sorted(set(df[df.kind == 'withdrawal'].period))[-2:]
    body = run(client, pid, mode='object', kind='withdrawal', groups=[], periods=periods, seasonx=xmode)
    chart = body['charts'][0]
    assert chart['id'] == 'production-object-seasons'
    assert [s['name'] for s in chart['series']] == periods
    base = df[df.kind.eq('withdrawal')]
    for series, period in zip(chart['series'], periods):
        day_sum = base[base.period.eq(period)].groupby('date').q.sum(min_count=1).dropna() / 1000
        assert len(series['y']) == len(day_sum)
        assert np.allclose(series['y'], day_sum.to_numpy())
        if xmode == 'object':
            x = np.asarray(series['x'], dtype=float)
            assert x[0] >= 0
            assert np.all(np.diff(x) >= 0) and x.min() >= 0
            total = base[base.period.eq(period)].groupby('date').q.sum(min_count=1).fillna(0).sum() / 1e6
            assert x[-1] == pytest.approx(total)
    assert any(s['label'] == 'Пиковый суточный расход' for s in body['summary'])


def test_object_seasons_need_periods(env):
    client, pid, _ = env
    body = run(client, pid, mode='object', kind='withdrawal', groups=[], periods=[])
    assert body['charts'] == []
    assert any('Выберите' in n['text'] for n in body['notes'])


def test_histogram_volumes_by_season_and_month(env):
    client, pid, projects = env
    p = pick(client, pid, projects)
    p['wells'] = ['31', '45']
    p['periods'] = p['periods'][:1]
    base = dict(p, hist_size='Все', direction='number')
    season = run(client, pid, 'histograms', **base, metric='season', axis='well')['charts'][0]
    month = run(client, pid, 'histograms', **base, metric='month', axis='well')['charts'][0]
    legacy_vol = legacy.averages(frame(projects, pid), p['kind'], p['periods'], ['31', '45']).set_index('well').volume
    got = {c: v for c, v in zip(season['x']['categories'], season['series'][0]['y'])}
    assert got['31'] == pytest.approx(legacy_vol['31'])
    total = [sum(s['y'][i] for s in month['series'] if s['y'][i] is not None) for i in range(2)]
    assert total == pytest.approx([legacy_vol['31'], legacy_vol['45']])
    names = [s['name'] for s in month['series']]
    assert len(names) == len(set(names)) and len(names) > 1
