"""Паритет с 5.8: «Графики реагирования» рисуют то же, что ``atlas.engine.modules.charts.response_chart``."""
import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.engine.core import exclusions
from atlas.engine.core.config import ordered
from atlas.engine.core.demo import demo_frames
from atlas.engine.core.storage import Store
from atlas.engine.modules import charts as legacy_charts
from atlas.engine.modules.response import statistics
from atlas.api import create_app
from atlas.contract import Param, ParamError
from atlas.domain import DatasetKind
from atlas.projects import Projects

RESPONSE = DatasetKind.RESPONSE


def object_pressure():
    dates = pd.date_range('2023-01-01', periods=44, freq='MS')
    return pd.DataFrame({'date': dates, 'pressure': 74 + np.sin(np.arange(44) / 3), 'file': 'Демонстрация',
                         'sheet': 'Давление объекта', '_row': range(2, 46)})


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    store = projects.store
    pid = store.create('Объект с давлением')
    frames = {k: v for k, v in demo_frames().items() if k == 'response'}
    frames['object_pressure'] = object_pressure()
    store.commit(pid, frames=frames, settings={'manometer_wells': ['45']}, action='Загрузка')
    return TestClient(create_app(projects)), pid, projects


def run(client, pid, **params):
    r = client.post('/api/modules/response/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def table(body, tid):
    return next(t for t in body['tables'] if t['id'] == tid)


def rows(t):
    return pd.DataFrame(dict(zip([c['key'] for c in t['columns']], t['rows'])))


WELLS = ['31', '45', '70', '73', '132']


def legacy_figures(projects, pid, wells, view, split, start=None, end=None):
    """То, что строит страница 5.8 (app/main.py) для тех же параметров: [(подпись, вид, фигура)]."""
    data = projects.data(pid)
    d, raw = data[RESPONSE], data.raw[RESPONSE]
    f = d[d.well.isin(wells)]
    if start:
        f = f[f.date.between(pd.Timestamp(start), pd.Timestamp(end))]
    sets = {'Все выбранные': f} if split == 'all' else {str(k): v for k, v in f.groupby('horizon' if split == 'horizon' else 'well')}
    out = []
    for label, part in sets.items():
        for metric in (['level', 'pressure'] if view == 'separate' else [view]):
            if metric != 'combined' and (metric not in part or not part[metric].notna().any()):
                continue
            fig = legacy_charts.response_chart(
                part, [], metric, legacy_charts.response_title(ordered(part.well), label, split),
                color_map=legacy_charts.well_colors(d.well), object_pressure=data[DatasetKind.OBJECT_PRESSURE],
                manometer_wells=['45'], by_well=split == 'well',
                pressure_horizons=ordered(raw.loc[raw.pressure.notna(), 'horizon']))
            out.append((label, metric, fig))
    return out


@pytest.mark.parametrize('view', ['separate', 'combined', 'level', 'pressure'])
@pytest.mark.parametrize('split', ['horizon', 'all', 'well'])
def test_charts_match_58(env, view, split):
    client, pid, projects = env
    body = run(client, pid, wells=WELLS, view=view, split=split)
    theirs = legacy_figures(projects, pid, WELLS, view, split)
    ours = {(c['id'].split('-')[2], c['id'].split('-')[3]): c for c in body['charts']}
    assert sorted(ours) == sorted((label, metric) for label, metric, _ in theirs)
    for label, metric, fig in theirs:
        chart = ours[(label, metric)]
        assert chart['title'] == fig.layout.title.text + ' · ' + {'level': 'уровень', 'pressure': 'давление',
                                                                    'combined': 'уровень и давление'}[metric]
        assert chart['x']['scale'] == 'time'
        assert f"{chart['y']['label']}, {chart['y']['unit']}" == fig.layout.yaxis.title.text
        assert chart['y']['inverse'] == (fig.layout.yaxis.autorange == 'reversed')
        y2 = fig.layout.to_plotly_json().get('yaxis2', {})
        assert (chart['y2'] is not None) == (y2.get('overlaying') == 'y')
        if chart['y2']:
            assert chart['y2']['inverse'] and f"{chart['y2']['label']}, {chart['y2']['unit']}" == y2['title']['text']
        assert len(chart['series']) == len(fig.data)
        for old, new in zip(fig.data, chart['series']):
            assert old.name == new['name'] and old.line.color == new['color']
            assert (old.showlegend is not False) == new['legend']
            assert (old.yaxis or 'y') == new['axis'] and new['markers']
            symbol = old.marker.symbol or 'circle'
            assert symbol == new['symbol'] and (old.marker.color == 'white') == new['hollow']
            y_old = np.asarray(old.y, float)
            y_new = np.array([np.nan if v is None else v for v in new['y']], float)
            assert np.array_equal(y_old, y_new, equal_nan=True)
            assert new['x'] == pd.to_datetime(list(old.x)).strftime('%Y-%m-%d').tolist()
            assert new['ids'] == [str(row[0]) for row in old.customdata]
            assert new['dataset'] == old.meta['module']


def test_semantic_colors_and_object_pressure(env):
    client, pid, _ = env
    body = run(client, pid, wells=['45'], view='combined', split='well')
    series = body['charts'][0]['series']
    assert [s['name'] for s in series] == ['Уровень жидкости', 'Давление (глубинный манометр)',
                                           'Пластовое давление объекта']
    assert [s['color'] for s in series] == ['#32BDA4', '#8B5CF6', '#DC3545']
    assert series[0]['hollow'] and series[0]['axis'] == 'y2' and series[2]['dataset'] == 'object_pressure'


def test_wells_follow_horizons_and_natural_order(env):
    client, pid, projects = env
    ask = lambda **p: client.post('/api/modules/response/options',
                                  json={'project': pid, 'param': 'wells', 'params': p}).json()
    assert ask(horizons=[]) == ['31', '45', '70', '73', '89', '132', '540', '541']
    assert ask(horizons=['Окский']) == ['31', '73', '540']
    body = run(client, pid, wells=WELLS, split='well', view='level')
    assert [c['title'] for c in body['charts']][:3] == ['Скважина №31 · уровень', 'Скважина №45 · уровень',
                                                        'Скважина №70 · уровень']
    # скважина вне выбранных горизонтов отбрасывается
    body = run(client, pid, wells=['31', '45'], horizons=['Окский'], view='level', split='all')
    assert body['charts'][0]['title'] == 'Скважина №31 · уровень'


def test_period_and_empty_selection(env):
    client, pid, projects = env
    body = run(client, pid, wells=WELLS, date_from='2024-01-01', date_to='2024-12-31', view='level', split='all')
    theirs = legacy_figures(projects, pid, WELLS, 'level', 'all', '2024-01-01', '2024-12-31')
    assert [len(s['y']) for s in body['charts'][0]['series']] == [len(t.y) for t in theirs[0][2].data]
    assert all(x.startswith('2024') for s in body['charts'][0]['series'] for x in s['x'])
    m = rows(table(body, 'measurements'))
    assert len(m) == 5 * 12 and set(m.columns) >= {'well', 'date', 'horizon', 'level', 'pressure'}
    stats = {st['label']: st['value'] for st in body['summary']}
    assert (stats['Горизонтов'], stats['Скважин'], stats['Действующих уровней']) == ('3', '5', '60')
    body = run(client, pid, wells=WELLS, date_from='2030-01-01')
    assert body['charts'] == [] and body['notes'][0]['text'] == 'Нет замеров в выбранном диапазоне.'
    assert run(client, pid, wells=[])['notes'][0]['text'] == 'Выберите скважины.'


def test_click_exclusion_of_pressure_keeps_level_and_is_seen_by_58(env):
    client, pid, projects = env
    body = run(client, pid, wells=['31'], view='pressure', split='well')
    point = body['charts'][0]['series'][0]['ids'][3]
    assert point.endswith(':pressure')
    r = client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'response', 'add': [point]})
    assert r.json()['added'] == 1
    m = Store(projects.store.root).manifest(pid)
    entry = m['settings']['excluded_points'][point]
    assert entry['metric'] == 'pressure' and entry['module'] == 'response' and entry['well'] == '31'
    shown = exclusions.apply(exclusions.identify_frames({'response': projects.data(pid).raw[RESPONSE]}), m['settings'])
    row = shown['response'][shown['response']['_point_id'] == point.rsplit(':', 1)[0]].iloc[0]
    assert np.isnan(row.pressure) and not np.isnan(row.level)        # 5.8 видит исключение давления, уровень цел
    after = run(client, pid, wells=['31'], view='pressure', split='well')['charts'][0]['series'][0]
    assert after['y'][3] is None
    pressure = table(run(client, pid, wells=['31']), 'points-pressure')
    assert pressure['action']['checked'][pressure['action']['ids'].index(point)]


def test_manual_filter_tables(env):
    client, pid, _ = env
    body = run(client, pid, wells=['31', '45'])
    level, pressure, obj = table(body, 'points-level'), table(body, 'points-pressure'), table(body, 'points-object')
    assert level['count'] == pressure['count'] == 88 and obj['count'] == 44
    assert all(i.endswith(':level') for i in level['action']['ids'])
    assert level['action']['dataset'] == 'response' and obj['action']['dataset'] == 'object_pressure'
    first = level['action']['ids'][0]
    client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'response', 'add': [first], 'reason': 'Проверка'})
    assert table(run(client, pid, wells=['31', '45']), 'points-level')['action']['checked'][0]
    client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'response', 'remove': [first]})
    assert not table(run(client, pid, wells=['31', '45']), 'points-level')['action']['checked'][0]
    o = obj['action']['ids'][0]
    assert client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'object_pressure', 'add': [o]}).json()['added'] == 1
    combined = run(client, pid, wells=['31'], view='pressure', split='well')['charts'][0]['series'][-1]
    assert o not in combined['ids']


def test_statistics_unchanged(env):
    """Сводка 5.8 по горизонтам (отчёт) считается по тем же данным, что видит модуль."""
    _, pid, projects = env
    s = statistics(projects.data(pid)[RESPONSE])
    assert s['Скважин'].sum() == 8


def test_saved_view_in_58_format(env):
    client, pid, projects = env
    params = dict(wells=['31', '73'], horizons=['Окский'], date_from='2024-01-01', view='combined', split='well')
    assert client.post(f'/api/projects/{pid}/state/response', json={'params': params}).status_code == 200
    saved = projects.store.manifest(pid)['settings']['panels']['response']
    assert saved == {'wells': ['31', '73'], 'horizons': ['Окский'], 'working': [], 'dates': ['2024-01-01', '2026-08-01'],
                     'view': 'combined', 'split': 'well'}
    back = client.get(f'/api/projects/{pid}/state/response').json()['panel']
    assert back == {'wells': ['31', '73'], 'horizons': ['Окский'], 'view': 'combined', 'split': 'well',
                    'date_from': '2024-01-01', 'date_to': '2026-08-01'}
    # вид, сохранённый в 5.8 (даты — объекты date, превращённые в строки)
    cfg = projects.store.manifest(pid)['settings']
    cfg['panels']['response'] = {'wells': ['540'], 'horizons': ['Окский', 'Турнейский'], 'working': ['Окский'],
                                 'dates': ['2023-05-01', '2025-01-01'], 'view': 'level', 'split': 'all'}
    projects.store.commit(pid, settings=cfg, action='Сохранение фильтров')
    back = client.get(f'/api/projects/{pid}/state/response').json()['panel']
    assert back['date_from'] == '2023-05-01' and back['view'] == 'level' and 'working' not in back


def test_working_horizons_are_shared_setting(env):
    client, pid, projects = env
    spec = next(s for s in client.get('/api/modules').json() if s['id'] == 'response')
    working = next(p for p in spec['params'] if p['name'] == 'working')
    assert working['setting'] == 'working_horizons'
    r = client.patch(f'/api/projects/{pid}/settings', json={'values': {'working_horizons': ['Окский']}})
    assert r.status_code == 200 and r.json()['settings']['working_horizons'] == ['Окский']
    assert projects.store.manifest(pid)['settings']['working_horizons'] == ['Окский']
    history = projects.store.history(pid)
    assert 'Выбор рабочих горизонтов' in history['Действие'].tolist()
    bad = client.patch(f'/api/projects/{pid}/settings', json={'values': {'working_horizons': 'Окский'}})
    assert bad.status_code == 400


@pytest.mark.parametrize('fmt,magic', [('png', b'\x89PNG'), ('svg', b'<?xml'), ('pdf', b'%PDF')])
def test_two_axis_chart_export(env, fmt, magic):
    client, pid, _ = env
    params = dict(wells=['45'], view='combined', split='well')
    chart = run(client, pid, **params)['charts'][0]
    r = client.post('/api/modules/response/export', json={'project': pid, 'params': params, 'target': 'chart',
                                                          'id': chart['id'], 'format': fmt, 'dpi': 300})
    assert r.status_code == 200 and r.content.startswith(magic)


def test_measurements_csv(env):
    client, pid, _ = env
    params = dict(wells=['31'])
    r = client.post('/api/modules/response/export', json={'project': pid, 'params': params, 'target': 'tables',
                                                          'id': 'measurements', 'format': 'csv'})
    assert r.status_code == 200 and 'Уровень жидкости, м' in r.content.decode('utf-8-sig').splitlines()[0]


def test_date_param():
    p = Param('d', 'Период с', 'date')
    assert p.coerce('') is None and p.coerce(None) is None
    assert p.coerce('2024-03-05') == '2024-03-05' and p.coerce('2024-03-05T10:00:00') == '2024-03-05'
    with pytest.raises(ParamError):
        p.coerce('вчера')


def test_demo_project_works(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    body = run(client, pid, wells=['31'], view='combined', split='horizon')
    assert body['charts'] and 'points-object' not in [t['id'] for t in body['tables']]


def test_level_band_separates_level_from_pressure(env):
    """Две шкалы: кривая уровня стоит отдельной полосой ниже (выше) давлений; «overlay» — как в 5.8."""
    from atlas.engine.modules.charts import separated_ranges
    pressure, level = np.linspace(50, 80, 20), np.linspace(10, 40, 20)
    for band in ('below', 'above', 'auto'):
        (p0, p1), (top, bottom) = separated_ranges(pressure, level, band)
        pos = lambda v: (v - p0) / (p1 - p0)                      # доля высоты от низа, давление растёт вверх
        lev = lambda v: (bottom - v) / (bottom - top)             # уровень: глубже — ниже
        p_band, l_band = (pos(pressure.min()), pos(pressure.max())), (lev(level.max()), lev(level.min()))
        low, high = sorted([p_band, l_band])
        assert high[0] - low[1] > .05 and 0 < low[0] and high[1] < 1               # полосы не пересекаются, есть зазор
        assert band == 'auto' or (l_band[0] < p_band[0]) == (band == 'below')
    assert separated_ranges(pressure, level, 'overlay') is None and separated_ranges([], level, 'below') is None
    assert separated_ranges([60, 60], [20, 20], 'below')
    client, pid, projects = env
    body = run(client, pid, wells=WELLS, view='combined', split='all')
    chart = body['charts'][0]
    assert chart['y']['minimum'] is not None and chart['y2']['minimum'] is not None and chart['y2']['inverse']
    assert chart['y']['maximum'] > chart['y']['minimum'] and chart['y2']['minimum'] < chart['y2']['maximum']
