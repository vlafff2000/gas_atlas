"""Паритет с 5.8: «Кроссплот давлений» отбирает пары, считает статистику и рисует то же, что app.modules.pressure_match."""
import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from app.modules import pressure_match as legacy
from atlas.api import create_app
from atlas.domain import DatasetKind
from atlas.modules import pressure
from atlas.projects import Projects

PM = DatasetKind.PRESSURE_MATCH


def pressure_frame(tmp_path, books=2, wells=8, dates=30):
    """Пары факт / модель так же, как их собирает быстрый импорт 5.8 (две книги, два сценария, фонды)."""
    from app.ui import pressure_quick_import as q
    from tools.make_pressure_samples import make_book
    files = {}
    for i in range(books):
        path = tmp_path / f'Объект_{i + 1}.xlsx'
        make_book(path, i, wells, dates)
        files[str(path)] = (path.name, path.read_bytes())
    cache = {sha: q.parse_file(n, c) for sha, (n, c) in files.items()}
    data, *_ = q.assemble(q.build_rows(files, cache, {}, 'P'), cache, 'first')
    # Пара с нулём и неполная пара: их счёт должен совпасть с 5.8.
    extra = data.iloc[:2].copy()
    extra.loc[extra.index[0], 'fact'] = 0.0
    extra.loc[extra.index[1], 'model'] = np.nan
    extra['date'] = pd.Timestamp('2019-06-01')
    return pd.concat([data, extra], ignore_index=True)


@pytest.fixture(scope='module')
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('pressure')
    projects = Projects(tmp / 'storage')
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    from app.core.demo import demo_frames
    projects.store.commit(pid, {**demo_frames(), 'pressure_match': pressure_frame(tmp)}, action='test')
    return client, pid, projects


def run(client, pid, **params):
    r = client.post('/api/modules/pressure/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def table(body, tid):
    return next(t for t in body['tables'] if t['id'] == tid)


def frame_of(t):
    return pd.DataFrame(dict(zip([c['key'] for c in t['columns']], t['rows'])))


def legacy_view(projects, pid, params):
    """Что показала бы 5.8 при тех же параметрах: cfg в её формате и ``filter_data``."""
    data = projects.data(pid)
    full = pressure.PressureModule.spec.coerce(params)
    cfg = pressure.config(full, data.raw[PM], data.settings)
    d, info = legacy.filter_data(data[PM], data.settings, data.mapping, cfg)
    return d, info, cfg


def test_registered_and_needs_data(env):
    client, pid, _ = env
    spec = next(m for m in client.get('/api/modules').json() if m['id'] == 'pressure')
    assert spec['needs'] == ['pressure_match'] and spec['title'] == 'Кроссплот давлений'
    demo = client.post('/api/projects/demo').json()['id']      # без данных давлений — понятная ошибка 409
    r = client.post('/api/modules/pressure/run', json={'project': demo, 'params': {}})
    assert r.status_code == 409 and 'Кроссплот давлений' in r.json()['error']


@pytest.mark.parametrize('params', [
    {},
    {'threshold_mode': 'relative', 'threshold': 3, 'inclusive': True},
    {'exclude_zeros': False, 'recent': True, 'percentiles': ['50', '95']},
    {'scenarios': ['Модель 2'], 'date_from': '2021-03-01', 'date_to': '2021-09-30'},
])
def test_statistics_match_legacy(env, params):
    client, pid, projects = env
    body = run(client, pid, view='stats', **params)
    d, info, cfg = legacy_view(projects, pid, params)
    assert not d.empty
    note = body['notes'][0]['text']
    assert f"неполных пар: {info['missing']}; нулевых: {info['zeros']}" in note
    theirs = legacy.tables(d, cfg)
    for title in pressure.STAT_ORDER:
        ours = frame_of(next(t for t in body['tables'] if t['title'] == title))
        expected = theirs[title]
        assert list(ours.columns) == list(expected.columns), title
        for c in expected.columns:
            if pd.api.types.is_numeric_dtype(expected[c]):
                assert np.allclose(ours[c].astype(float), expected[c].astype(float), equal_nan=True), (title, c)
            else:
                assert ours[c].astype(str).tolist() == expected[c].astype(str).tolist(), (title, c)
    stats = legacy.statistics(d, cfg['percentiles'])
    m = frame_of(table(body, 'metrics')).iloc[0]
    assert m.points == stats['Точек'] and np.isclose(m.rmse, stats['RMSE'])
    assert np.isclose(m.within, stats['В пределах порога, %'])
    assert not next(t for t in body['tables'] if t['title'] == 'Сводная объектов')['collapsed']


def test_cross_chart_matches_legacy_figure(env):
    client, pid, projects = env
    params = {'color': 'well', 'percentile_lines': True, 'groups': [], 'threshold': 4}
    body = run(client, pid, **params)
    d, _, cfg = legacy_view(projects, pid, params)
    fig = legacy.figure.__wrapped__(d, 'cross', cfg) if hasattr(legacy.figure, '__wrapped__') else legacy.figure(d, 'cross', cfg)
    chart = body['charts'][0]
    assert chart['id'] == 'pressure-cross' and len(chart['series']) == len(fig.data)
    for old, new in zip(fig.data, chart['series']):
        assert old.name.strip() == new['name'].strip()
        assert np.allclose(np.asarray(old.x, float), np.asarray(new['x'], float))
        assert np.allclose(np.asarray(old.y, float), np.asarray(new['y'], float))
        if new['kind'] == 'points':
            assert old.marker.color == new['color'] and len(new['ids']) == len(new['x'])
            assert new['dataset'] == 'pressure_match'
    assert chart['x']['minimum'] == chart['y']['minimum'] and chart['x']['maximum'] == chart['y']['maximum']
    summary = frame_of(table(body, 'summary'))
    assert summary['Точек'].sum() == len(d)


@pytest.mark.parametrize('view', ['dynamics', 'distributions', 'objects'])
def test_other_views_match_legacy(env, view):
    client, pid, projects = env
    body = run(client, pid, view=view, well_limit='all')
    d, _, cfg = legacy_view(projects, pid, {})
    names = pressure.VIEWS[view][1]
    assert [c['id'] for c in body['charts']] == [f'pressure-{n}' for n in names]
    for name, chart in zip(names, body['charts']):
        fig = legacy.figure(d, name, cfg)
        assert chart['title'] == fig.layout.title.text
        if name in ('time', 'error_time', 'cdf'):
            old = [t for t in fig.data]
            assert [t.name for t in old] == [s['name'] for s in chart['series']]
            for t, s in zip(old, chart['series']):
                assert np.allclose(np.asarray(t.y, float), np.asarray(s['y'], float))
        elif name in ('hist', 'percentiles'):
            assert [t.name for t in fig.data] == [s['name'] for s in chart['series']]
            for t, s in zip(fig.data, chart['series']):
                assert np.allclose(np.asarray(t.y, float), np.asarray(s['y'], float))
        else:   # ящики: те же квартили, что Plotly считает по 'linear', и порядок категорий по медиане
            boxes = [s for s in chart['series'] if s['kind'] == 'box']
            assert boxes
            for s in boxes:
                for category, stats in zip(s['x'], s['y']):
                    if stats is None:
                        continue
                    col = {'box': 'well', 'fond_box': 'fond', 'object_box': 'object', 'overall_box': None}[name]
                    if col is None:
                        continue
                    values = d[(d[col].astype(str) == category) & (d.scenario == s['name'])].error.to_numpy()
                    q1, med, q3 = np.percentile(values, [25, 50, 75])
                    assert np.allclose(stats[1:4], [q1, med, q3])
            if name != 'overall_box':
                col = {'box': 'well', 'fond_box': 'fond', 'object_box': 'object'}[name]
                medians = d.groupby(col).error.median()
                assert chart['x']['categories'] == [str(c) for c in sorted(medians.index, key=lambda c: medians[c])]


def test_well_limit_and_fixed_axes(env):
    client, pid, _ = env
    body = run(client, pid, view='dynamics', well_limit='12')
    assert any('показано 12 из' in n['text'] for n in body['notes'])
    body = run(client, pid, axis_x=True, x_min=50, x_max=160, x_step=20)
    x = body['charts'][0]['x']
    assert (x['minimum'], x['maximum'], x['step']) == (50, 160, 20)


def test_groups_filter_and_threshold_override(env):
    client, pid, projects = env
    groups = client.post('/api/modules/pressure/options', json={'project': pid, 'param': 'groups', 'params': {}}).json()
    assert groups
    wells = client.post('/api/modules/pressure/options',
                        json={'project': pid, 'param': 'wells', 'params': {'groups': groups[:1]}}).json()
    assert wells
    params = {'threshold_groups': groups[:1], 'group_threshold': 1.5, 'threshold': 7}
    body = run(client, pid, view='stats', **params)
    d, _, cfg = legacy_view(projects, pid, params)
    assert cfg['group_thresholds'] == {groups[0]: 1.5}
    assert set(d.threshold) <= {1.5, 7.0}
    stats = legacy.statistics(d, cfg['percentiles'])
    assert np.isclose(frame_of(table(body, 'metrics')).within[0], stats['В пределах порога, %'])


def test_empty_selection_is_a_note(env):
    client, pid, _ = env
    body = run(client, pid, date_from='1990-01-01', date_to='1990-12-31')
    assert not body['charts'] and any(n['level'] == 'warning' for n in body['notes'])
    bad = client.post('/api/modules/pressure/run', json={'project': pid, 'params': {'date_from': '31.12.2020'}})
    assert bad.status_code == 400


def test_click_exclusion_and_manual_filter(env):
    client, pid, projects = env
    body = run(client, pid)
    before = frame_of(table(body, 'metrics')).points[0]
    point = next(s for s in body['charts'][0]['series'] if s['ids'])['ids'][0]
    r = client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'pressure_match', 'add': [point]})
    assert r.status_code == 200 and r.json()['added'] == 1
    body = run(client, pid)
    assert frame_of(table(body, 'metrics')).points[0] == before - 1
    points = table(body, 'points')
    assert points['action']['dataset'] == 'pressure_match'
    assert points['action']['checked'][points['action']['ids'].index(point)] is True
    # 5.8 видит то же исключение: её отбор по тем же данным проекта
    from app.core import exclusions
    m = projects.manifest(pid)
    assert point in m['settings']['excluded_points']
    assert client.post(f'/api/projects/{pid}/exclusions/undo').json()['removed'] == 1
    assert frame_of(table(run(client, pid), 'metrics')).points[0] == before
    assert exclusions.KEYS['pressure_match']


def test_saved_view_is_58_format(env):
    client, pid, projects = env
    params = {'scenarios': ['Модель 1'], 'threshold': 5, 'threshold_groups': ['Без группы'], 'group_threshold': 2,
              'percentiles': ['75', '90'], 'axis_y': True, 'y_min': 10, 'y_max': 200, 'y_step': 25,
              'date_from': '2021-02-01', 'color': 'object'}
    r = client.post(f'/api/projects/{pid}/state/pressure', json={'params': params})
    assert r.status_code == 200, r.text
    saved = projects.manifest(pid)['settings']['panels']['pressure_match']
    assert saved['scenarios'] == ['Модель 1'] and saved['objects'] == sorted(saved['objects'])
    assert saved['group_thresholds'] == {'Без группы': 2.0} and saved['percentiles'] == [75.0, 90.0]
    assert saved['axes'] == {'y_range': [10.0, 200.0], 'y_dtick': 25.0} and saved['dates'][0] == '2021-02-01'
    # Сохранённое 6 открывается в 5.8: её options() принимает те же ключи (FIELDS панели 5.8)
    for field in ('objects', 'scenarios', 'groups', 'wells', 'fonds', 'recent', 'exclude_zeros', 'unit',
                  'threshold_mode', 'threshold', 'inclusive', 'color', 'bins', 'bands', 'percentile_lines', 'outliers'):
        assert field in saved
    loaded = client.get(f'/api/projects/{pid}/state/pressure').json()['panel']
    assert loaded['scenarios'] == ['Модель 1'] and loaded['threshold_groups'] == ['Без группы']
    assert loaded['axis_y'] is True and loaded['y_max'] == 200 and loaded['percentiles'] == ['75', '90']
    assert run(client, pid, **{k: v for k, v in loaded.items()})['charts']


def test_export_box_chart(env):
    client, pid, _ = env
    for fmt in ('svg', 'png'):
        r = client.post('/api/modules/pressure/export', json={'project': pid, 'params': {'view': 'distributions'},
                                                              'target': 'chart', 'id': 'pressure-fond_box',
                                                              'format': fmt, 'dpi': 300})
        assert r.status_code == 200 and len(r.content) > 1000
    r = client.post('/api/modules/pressure/export', json={'project': pid, 'params': {'view': 'stats'}, 'target': 'tables'})
    assert r.status_code == 200 and r.content[:2] == b'PK'
