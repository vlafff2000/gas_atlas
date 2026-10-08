"""Прореживание графиков на больших данных не теряет то, что видно и на что можно нажать.

Результат модуля хранит все точки; экран получает выборку М4; при увеличении отдаются точки окна; выгрузки
(график, таблицы) и исключение точек работают с полными данными. Тесты сравнивают прореженное с исходным.
"""
import io

import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas import thinning
from atlas.api import create_app
from atlas.contract import Axis, Chart, Result, Series
from atlas.projects import Projects

N = 9000        # точек на скважину: больше лимита серии, но тест остаётся быстрым


def response_frame():
    rng = np.random.default_rng(7)
    parts = []
    for k, well in enumerate(('11', '12', '13', '14')):
        dates = pd.date_range('2015-01-01', periods=N, freq='D')
        level = 30 + 8 * np.sin(np.arange(N) / 40 + k) + rng.normal(0, 0.3, N)
        level[N // 3 + k * 100] = 3.0 + k          # одиночный провал
        level[N // 2 + k * 50] = 95.0 - k          # одиночный пик
        pressure = 70 + np.cos(np.arange(N) / 90) + rng.normal(0, 0.05, N)
        level[2000 + k:2060 + k] = np.nan          # разрыв (исключённые замеры)
        parts.append(pd.DataFrame({'well': well, 'date': dates, 'horizon': 'Окский', 'level': level,
                                   'pressure': pressure, 'group': 'ГСП 1', 'subgroup': '',
                                   'file': 'тест', 'sheet': 'Реагирование', '_row': np.arange(2, N + 2)}))
    return pd.concat(parts, ignore_index=True)


@pytest.fixture(scope='module')
def env(tmp_path_factory):
    projects = Projects(tmp_path_factory.mktemp('thin'))
    pid = projects.store.create('Большое реагирование')
    projects.store.commit(pid, frames={'response': response_frame()}, action='Загрузка')
    return TestClient(create_app(projects)), pid, projects


WELLS = ['11', '12', '13', '14']
PARAMS = {'wells': WELLS, 'view': 'separate', 'split': 'all'}


def run(client, pid, params=PARAMS):
    r = client.post('/api/modules/response/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def level_chart(body):
    return next(c for c in body['charts'] if c['id'].endswith('-level'))


def raw_series(wells=WELLS, field='level'):
    frame = response_frame()
    return {w: frame[frame.well == w].sort_values('date') for w in wells}


# ---------- метод М4 ----------

def test_m4_keeps_first_last_extremes_and_gaps():
    rng = np.random.default_rng(1)
    y = np.sin(np.arange(50000) / 70) + rng.normal(0, 0.2, 50000)
    y[1234], y[40000] = -9.0, 9.0
    y[300:320] = np.nan
    keep = thinning.m4_indices(y, 800)
    assert len(keep) <= 800 and keep[0] == 0 and keep[-1] == len(y) - 1
    assert np.all(np.diff(keep) > 0)
    assert y[keep][np.isfinite(y[keep])].min() == np.nanmin(y) and np.nanmax(y[keep]) == np.nanmax(y)
    assert np.isnan(y[keep]).any(), 'разрыв линии должен остаться разрывом'


def test_m4_every_bucket_keeps_its_min_and_max():
    rng = np.random.default_rng(2)
    y = rng.normal(0, 1, 20000)
    limit = 500
    keep = thinning.m4_indices(y, limit)
    for chunk in np.array_split(np.arange(len(y)), max(1, (limit - 2) // 5)):
        kept = np.intersect1d(chunk, keep)
        assert y[kept].max() == y[chunk].max() and y[kept].min() == y[chunk].min()


def test_short_series_untouched():
    y = np.arange(100.0)
    assert np.array_equal(thinning.m4_indices(y, 5000), np.arange(100))


def test_budget_shares_unused_points_with_long_series():
    # короткие серии отдают неиспользованное длинным; сумма не превышает бюджет
    limit = thinning.shares([100, 100, 20000], 6000)
    assert limit == 5800 or limit == thinning.SERIES_CAP
    assert sum(min(s, limit) for s in (100, 100, 20000)) <= 6000
    assert thinning.shares([50] * 1000, 30000) >= thinning.SERIES_FLOOR


# ---------- экран: прореженное против исходного ----------

def test_screen_is_thinned_but_keeps_peaks_dips_and_totals(env):
    client, pid, _ = env
    chart = level_chart(run(client, pid))
    raw = raw_series()
    assert len(chart['series']) == len(WELLS)
    for series, well in zip(chart['series'], WELLS):
        full = raw[well]
        assert series['total'] == N and len(series['x']) < N // 2          # прорежено и помечено
        y = np.array([np.nan if v is None else v for v in series['y']])
        assert np.nanmin(y) == full.level.min() and np.nanmax(y) == full.level.max()    # пик и провал на месте
        assert series['x'][0] == full.date.iloc[0].date().isoformat()
        assert series['x'][-1] == full.date.iloc[-1].date().isoformat()
        assert any(v is None for v in series['y'])                          # разрыв не заполнен
        # каждая отданная точка — настоящий замер, значения не усреднялись
        shown = pd.DataFrame({'date': pd.to_datetime(series['x']), 'y': y}).dropna()
        merged = shown.merge(full[['date', 'level']], on='date')
        assert len(merged) == len(shown) and np.allclose(merged.y, merged.level)
        assert len(series['ids']) == len(series['x']) == len(series['labels'])


def test_result_keeps_every_point(env):
    """Прореживается только JSON: из результата делаются выгрузки и щелчки по точкам."""
    client, pid, projects = env
    from atlas import registry
    data = projects.select(pid, registry.get('response').spec.needs, registry.get('response').spec.optional)
    result = registry.get('response').run(data, registry.get('response').spec.coerce(PARAMS))
    sizes = [len(s.x) for c in result.charts for s in c.series if c.id.endswith('-level')]
    before = result.to_json()
    assert sizes == [N] * len(WELLS)
    result.to_json(thin=False)
    assert [len(s.x) for c in result.charts for s in c.series if c.id.endswith('-level')] == sizes
    assert before['charts'][0]['series'][0]['total'] == N


# ---------- увеличение: полное разрешение окна ----------

def ms(date):
    return float(pd.Timestamp(date).value // 10 ** 6)


def window(client, pid, x0, x1, raw=False, chart='response-all-Все выбранные-level'):
    r = client.post('/api/modules/response/window', json={'project': pid, 'params': PARAMS, 'chart': chart,
                                                          'x0': ms(x0), 'x1': ms(x1), 'raw': raw})
    assert r.status_code == 200, r.text
    return r.json()['series']


def test_zoomed_window_returns_all_raw_points(env):
    client, pid, _ = env
    start, end = '2018-03-01', '2018-08-31'
    series = window(client, pid, start, end)
    raw = raw_series()
    for i, well in enumerate(WELLS):
        got = series[str(i)]
        full = raw[well]
        inside = full[(full.date >= start) & (full.date <= end)]
        dates = pd.to_datetime(got['x'])
        shown = pd.DataFrame({'date': dates, 'y': [np.nan if v is None else v for v in got['y']]})
        core = shown[(shown.date >= start) & (shown.date <= end)].reset_index(drop=True)
        assert got['window'] >= len(inside) and len(core) == len(inside)    # все точки окна, ничего не пропущено
        assert np.allclose(core.y.to_numpy(), inside.level.to_numpy(), equal_nan=True)
        assert got['ids'][1:-1][:3], 'у точек окна есть идентификаторы для исключения'


def test_window_ids_match_raw_point_ids(env):
    """Щелчок по точке в окне исключает ту самую точку исходных данных."""
    client, pid, projects = env
    raw = projects.data(pid).raw[next(iter(projects.data(pid).raw))]
    series = window(client, pid, '2019-01-01', '2019-02-15')
    got = series['0']
    expected = raw[(raw.well == '11') & (raw.date.isin(pd.to_datetime(got['x'])))]
    assert sorted(i.rsplit(':', 1)[0] for i in got['ids']) == sorted(expected['_point_id'])
    assert all(i.endswith(':level') for i in got['ids'])


def test_raw_window_over_whole_chart_when_small_enough(env):
    client, pid, _ = env
    series = window(client, pid, '2000-01-01', '2100-01-01', raw=True)
    assert [len(series[str(i)]['x']) for i in range(len(WELLS))] == [N] * len(WELLS)
    thin = window(client, pid, '2000-01-01', '2100-01-01', raw=False)
    assert all(len(thin[str(i)]['x']) < N for i in range(len(WELLS)))


def test_stale_revision_is_refused(env):
    client, pid, _ = env
    r = client.post('/api/modules/response/window', json={'project': pid, 'params': PARAMS, 'revision': -5,
                                                          'chart': 'response-all-Все выбранные-level', 'x0': 0, 'x1': 1})
    assert r.status_code == 409


# ---------- выгрузки: полные данные ----------

def test_chart_export_uses_all_points(env, monkeypatch):
    client, pid, _ = env
    seen = {}

    def fake(chart, fmt, dpi, *font):
        seen['sizes'] = [len(s.x) for s in chart.series]
        return b'x', 'g.' + fmt, 'image/png'
    monkeypatch.setattr('atlas.render.chart_file', fake)
    r = client.post('/api/modules/response/export', json={'project': pid, 'params': PARAMS, 'target': 'chart',
                                                           'id': 'response-all-Все выбранные-level', 'format': 'png'})
    assert r.status_code == 200
    assert seen['sizes'] == [N] * len(WELLS)


def test_real_svg_export_contains_every_point(env):
    client, pid, _ = env
    r = client.post('/api/modules/response/export', json={'project': pid, 'params': PARAMS, 'target': 'chart',
                                                           'id': 'response-all-Все выбранные-pressure', 'format': 'svg'})
    assert r.status_code == 200 and b'<svg' in r.content[:2000]
    from atlas import registry, render
    data = env[2].select(pid, registry.get('response').spec.needs, registry.get('response').spec.optional)
    result = registry.get('response').run(data, registry.get('response').spec.coerce(PARAMS))
    chart = next(c for c in result.charts if c.id.endswith('-pressure'))
    figure = render.to_plotly(chart)
    assert [len(t.x) for t in figure.data] == [N] * len(WELLS)


def test_table_exports_equal_raw_data(env):
    client, pid, _ = env
    csv = client.post('/api/modules/response/export', json={'project': pid, 'params': PARAMS, 'target': 'tables',
                                                             'id': 'measurements', 'format': 'csv'})
    assert csv.status_code == 200
    text = csv.content.decode('utf-8-sig')
    assert len(text.strip().splitlines()) == 1 + N * len(WELLS)            # заголовок + все строки
    xlsx = client.post('/api/modules/response/export', json={'project': pid, 'params': PARAMS, 'target': 'tables',
                                                              'id': 'measurements', 'format': 'xlsx'})
    sheet = pd.read_excel(io.BytesIO(xlsx.content))
    assert len(sheet) == N * len(WELLS)
    raw = response_frame()
    assert np.isclose(sheet.filter(like='Уровень').iloc[:, 0].sum(), raw.level.sum())


def test_big_collapsed_table_is_deferred_and_loaded_in_full(env):
    client, pid, _ = env
    body = run(client, pid)
    stub = next(t for t in body['tables'] if t['id'] == 'measurements')
    assert stub['deferred'] and stub['count'] == N * len(WELLS) and all(col == [] for col in stub['rows'])
    r = client.post('/api/modules/response/table', json={'project': pid, 'params': PARAMS, 'id': 'measurements'})
    full = r.json()
    assert not full.get('deferred') and len(full['rows'][0]) == N * len(WELLS)
    assert client.post('/api/modules/response/table', json={'project': pid, 'params': PARAMS, 'id': 'нет'}).status_code == 404


# ---------- исключение точки на прореженном графике ----------

def test_excluding_a_point_from_thinned_view_hits_the_raw_point(env, tmp_path):
    client, pid, projects = env
    series = window(client, pid, '2020-05-01', '2020-05-10')['0']
    target = series['ids'][len(series['ids']) // 2]
    day = pd.to_datetime(series['x'][len(series['x']) // 2])
    before = run(client, pid)
    total = sum(s['total'] for s in level_chart(before)['series'])
    r = client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'response', 'add': [target], 'remove': [], 'reason': 'тест'})
    assert r.status_code == 200, r.text
    try:
        raw = projects.data(pid).raw[next(iter(projects.data(pid).raw))]
        hit = raw[(raw.well == '11') & (raw.date == day)]
        assert len(hit) == 1 and target.startswith(hit['_point_id'].iloc[0])
        after = run(client, pid)
        first = level_chart(after)['series'][0]
        assert first['total'] == N and sum(s['total'] for s in level_chart(after)['series']) == total
        again = window(client, pid, '2020-05-01', '2020-05-10')['0']
        assert again['y'][again['x'].index(day.date().isoformat())] is None     # исключённая точка — разрыв, остальные на месте
        assert sum(v is not None for v in again['y']) == sum(v is not None for v in series['y']) - 1
    finally:
        client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'response', 'add': [], 'remove': [target], 'reason': ''})


# ---------- другие графики: производительность ----------

def test_production_export_and_window_use_full_curves(tmp_path):
    from atlas.engine.core.demo_large import create_large_demo
    projects = Projects(tmp_path)
    pid = create_large_demo(projects.store, production=60000, gdi=500, response=500, pressure_match=500)
    client = TestClient(create_app(projects))
    groups = client.post('/api/modules/production/options', json={'project': pid, 'param': 'groups', 'params': {}}).json()
    wells = client.post('/api/modules/production/options', json={'project': pid, 'param': 'wells', 'params': {'groups': groups}}).json()
    periods = client.post('/api/modules/production/options', json={'project': pid, 'param': 'periods', 'params': {}}).json()
    params = {'groups': groups, 'wells': wells, 'periods': periods}
    body = client.post('/api/modules/production/run', json={'project': pid, 'params': params}).json()
    chart = next(c for c in body['charts'] if c['series'])
    thinned = [s for s in chart['series'] if s['total'] > len(s['x'])]
    assert thinned, 'на экране многокривый график прорежен и помечен'
    seen = {}

    import atlas.render as render
    original = render.chart_file
    render.chart_file = lambda c, fmt, dpi, *font: (seen.setdefault('chart', c), (b'x', 'g.png', 'image/png'))[1]
    try:
        r = client.post('/api/modules/production/export', json={'project': pid, 'params': params, 'target': 'chart',
                                                                 'id': chart['id'], 'format': 'png'})
    finally:
        render.chart_file = original
    assert r.status_code == 200
    exported = seen['chart']
    assert [len(s.x) for s in exported.series] == [s['total'] for s in chart['series']]   # выгрузка — все точки


def test_many_curves_warning(tmp_path):
    from atlas.engine.core.demo_large import create_large_demo
    projects = Projects(tmp_path)
    pid = create_large_demo(projects.store, production=80000, gdi=500, response=500, pressure_match=500)
    client = TestClient(create_app(projects))
    wells = client.post('/api/modules/production/options', json={'project': pid, 'param': 'wells', 'params': {}}).json()
    periods = client.post('/api/modules/production/options', json={'project': pid, 'param': 'periods', 'params': {}}).json()
    from atlas.modules.production import MANY_CURVES
    few = client.post('/api/modules/production/run', json={'project': pid, 'params': {'wells': wells[:2], 'periods': periods[-1:]}}).json()
    assert not any(n['level'] == 'warning' for n in few['notes'])
    many = client.post('/api/modules/production/run', json={'project': pid, 'params': {'wells': wells, 'periods': periods}}).json()
    if len(wells) * len(periods) > MANY_CURVES:
        assert any(n['level'] == 'warning' and 'кривых' in n['text'] for n in many['notes'])
