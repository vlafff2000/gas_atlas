"""Паритет с 5.8: «Поскважинный анализ» считает и рисует то же, что atlas.engine.modules.well_analysis / well_charts."""
import math

import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from _wells_data import make_project
from atlas.engine.core.config import DEFAULT_SETTINGS
from atlas.engine.core.performance import Frames, select_wells
from atlas.engine.modules import gdi as legacy_gdi
from atlas.engine.modules import well_analysis as legacy
from atlas.engine.modules import well_charts
from atlas.api import create_app
from atlas.contract import _column
from atlas.modules.wells import GDI_HISTORY_LABELS, OPERATING, SECTIONS
from atlas.projects import Projects

WELL = '31'
LABELS = [well_charts.LABELS[n] for n in OPERATING]


@pytest.fixture(scope='module')
def env(tmp_path_factory):
    projects = Projects(tmp_path_factory.mktemp('wells'))
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    return client, pid, projects


def number(value, precision=1):
    """Формат числа, как в 5.8 (well_dashboard.number)."""
    return f'{float(value):,.{precision}f}'.replace(',', ' ') if pd.notna(value) and np.isfinite(value) else 'Нет данных'


def ask(client, pid, name, **params):
    r = client.post('/api/modules/wells/options', json={'project': pid, 'param': name, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def run(client, pid, **params):
    r = client.post('/api/modules/wells/run', json={'project': pid, 'params': params})
    assert r.status_code == 200, r.text
    return r.json()


def table(body, tid):
    return next(t for t in body['tables'] if t['id'] == tid)


def legacy_inputs(projects, pid):
    """Аргументы, которые страница 5.8 передаёт в анализ: Frames проекта, настройки и группы."""
    m = projects.manifest(pid)
    settings = {**DEFAULT_SETTINGS, **m['settings']}
    cache = projects._cache(pid, m)
    return Frames(cache, settings), Frames(cache), settings, projects.data(pid).mapping


def legacy_analysis(projects, pid, periods, kind='withdrawal', method=None, delta=None, threshold=10.0, asof=None):
    """Как app/ui/well_dashboard.render: анализ + исходные ГДИ."""
    frames, raw, settings, mapping = legacy_inputs(projects, pid)
    if asof is None:
        asof = max(info['end'] for info in raw.project.catalog()['modules'].values() if pd.notna(info.get('end'))).date()
    analysis = dict(legacy.analyze(frames, settings, mapping, WELL, kind, periods, delta, threshold, method, asof))
    original = select_wells(raw['gdi'], [WELL])
    original = original[original.date.le(pd.Timestamp(asof))]
    if method is not None:
        original = original[original.method.eq(method)]
    if periods and not analysis['daily'].empty:
        mask = pd.Series(False, index=original.index)
        for _, g in analysis['daily'].groupby('period'):
            mask |= original.date.between(g.date.min(), g.date.max())
        original = original[mask]
    analysis['gdi_raw'] = original
    return analysis, settings


def same(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        if isinstance(x, float) and isinstance(y, float):
            assert (math.isnan(x) and math.isnan(y)) or x == pytest.approx(y, rel=1e-9, abs=1e-12)
        else:
            assert x == y, (x, y)


def cells(values):
    return _column(pd.Series(values) if not isinstance(values, (pd.Series, pd.Index)) else values)


def assert_table(body_table, frame):
    assert [c['label'] for c in body_table['columns']] == [str(c) for c in frame.columns]
    for column, values in zip(frame.columns, body_table['rows']):
        expected = cells(frame[column])
        assert len(values) == len(expected)
        for got, want in zip(values, expected):
            if isinstance(want, float):
                assert got == pytest.approx(want, rel=1e-9)
            else:
                assert got == want, (column, got, want)


def test_options_match_58(env):
    client, pid, projects = env
    frames, raw, settings, mapping = legacy_inputs(projects, pid)
    catalog = raw.project.catalog()
    from atlas.engine.core.config import ordered
    assert ask(client, pid, 'wells') == ordered(catalog['wells'])
    assert ask(client, pid, 'groups') == ordered(mapping.get(w, {}).get('group', 'Без группы') for w in catalog['wells'])
    daily = legacy.dataset(frames, settings, mapping)['daily']
    for kind in ('withdrawal', 'injection'):
        chosen = daily[daily.well.eq(WELL) & daily.kind.eq(kind)]
        assert ask(client, pid, 'periods', wells=[WELL], kind=kind) == chosen.groupby('period').date.max().sort_values().index.tolist()
    assert ask(client, pid, 'methods', wells=[WELL]) == ordered(select_wells(frames['gdi'], [WELL]).method)
    assert ask(client, pid, 'wells', groups=[]) == ordered(catalog['wells'])
    group = mapping[WELL]['group']
    assert WELL in ask(client, pid, 'wells', groups=[group])


def test_operations_section_matches_58(env):
    client, pid, projects = env
    periods = ask(client, pid, 'periods', wells=[WELL], kind='withdrawal')[-3:]
    body = run(client, pid, wells=[WELL], periods=periods, charts=LABELS, alignment='object')
    analysis, settings = legacy_analysis(projects, pid, periods)
    # Карточки
    metrics = table(body, f'metrics-{WELL}')
    expected = [number(v, p) if p is not None else v for _, v, p, _ in legacy.metrics(analysis)]
    assert metrics['rows'][1] == expected
    assert metrics['rows'][0] == [label for label, *_ in legacy.metrics(analysis)]
    # Графики: те же трассы, что строит 5.8, в том же порядке
    settings = {**settings, 'dashboard_alignment': 'object', 'dashboard_gdi': {}}
    available = well_charts.available(analysis)
    names = [n for n in OPERATING if n in available]
    assert {'hours', 'pressures', 'specific'} <= set(names)
    assert [c['id'] for c in body['charts']] == [f'wells-{WELL}-{n}' for n in names]
    for name, chart in zip(names, body['charts']):
        fig = well_charts.build(analysis, name, settings)
        assert chart['title'] == fig.layout.title.text
        assert len(chart['series']) == len(fig.data)
        for series, trace in zip(chart['series'], fig.data):
            assert series['name'] == trace.name
            assert series['axis'] == ('y2' if trace.yaxis == 'y2' else 'y')
            same([np.nan if v is None else float(v) for v in series['y']],
                 [np.nan if v is None else float(v) for v in cells(np.asarray(trace.y))])
            assert len(series['x']) == len(trace.x)
        if any(t.yaxis == 'y2' for t in fig.data):
            assert chart['y2']['label'] == fig.layout.yaxis2.title.text
    # Сезонные показатели
    assert_table(table(body, f'seasons-{WELL}'), analysis['seasons'].rename(columns=legacy.SEASON_LABELS))


def test_productivity_section_matches_58(env):
    client, pid, projects = env
    periods = ask(client, pid, 'periods', wells=[WELL], kind='withdrawal')
    method = ask(client, pid, 'methods', wells=[WELL])[0]
    body = run(client, pid, wells=[WELL], periods=periods, methods=[method], section='Продуктивность и ГДИ',
               fixed_dp2=True, dp2=300.0, gdi_n=2)
    analysis, settings = legacy_analysis(projects, pid, periods, method=method, delta=300.0)
    history = analysis['gdi_history']
    assert_table(table(body, f'gdi-{WELL}'), history[list(GDI_HISTORY_LABELS)].rename(columns=GDI_HISTORY_LABELS))
    gdi = next(c for c in body['charts'] if c['id'] == f'wells-{WELL}-gdi')
    selected = legacy_gdi.select_studies(analysis['gdi'], [WELL], 2)
    points = [s for s in gdi['series'] if s['kind'] == 'points' and not s['hollow']]
    assert sum(len(s['x']) for s in points) == len(selected)
    assert sorted(i for s in points for i in s['ids']) == sorted(selected['_point_id'])
    if history.q_reference.notna().any():
        line = next(c for c in body['charts'] if c['id'] == f'wells-{WELL}-gdi_history')
        fig = well_charts.build(analysis, 'gdi_history', settings)
        same([float(v) for s in line['series'] for v in s['y']], [float(v) for t in fig.data for v in t.y])
    # Ручной фильтр ГДИ: исходные точки выбранных дат
    filt = table(body, f'gdi-points-{WELL}')
    assert sorted(filt['action']['ids']) == sorted(legacy_gdi.select_studies(analysis['gdi_raw'], [WELL], 2)['_point_id'])


def test_one_method_equals_58_method_and_several_filter(env):
    client, pid, projects = env
    periods = ask(client, pid, 'periods', wells=[WELL], kind='withdrawal')
    methods = ask(client, pid, 'methods', wells=[WELL])
    everyone = run(client, pid, wells=[WELL], periods=periods, methods=methods, section='Продуктивность и ГДИ')
    single = run(client, pid, wells=[WELL], periods=periods, methods=[], section='Продуктивность и ГДИ')
    analysis, _ = legacy_analysis(projects, pid, periods, method=None)
    for body in (everyone, single):
        assert table(body, f'gdi-{WELL}')['count'] == len(analysis['gdi_history'])


@pytest.mark.parametrize('section', SECTIONS[2:])
def test_other_sections_match_58(env, section):
    client, pid, projects = env
    periods = ask(client, pid, 'periods', wells=[WELL], kind='withdrawal')[-3:]
    body = run(client, pid, wells=[WELL], periods=periods, section=section)
    analysis, settings = legacy_analysis(projects, pid, periods)
    ids = [c['id'] for c in body['charts']]
    if section == 'Контроль воды':
        assert_table(table(body, f'water-{WELL}'), analysis['water'])
        assert f'wells-{WELL}-water_log' in ids and f'wells-{WELL}-levels' in ids
        d = analysis['daily']
        factor = d[['date', 'gas_volume_m3', 'water_volume_m3', 'water_factor']].rename(columns={
            'date': 'Дата', 'gas_volume_m3': 'Газ, м³', 'water_volume_m3': 'Вода, м³',
            'water_factor': 'Водный фактор, л/тыс. м³'})
        assert_table(table(body, f'water-factor-{WELL}'), factor)
    elif section == 'Забой и шаблонировка':
        assert ids == [f'wells-{WELL}-bottom']
        assert table(body, f'bottom-{WELL}')['count'] == len(analysis['bottom'])
        fig = well_charts.build(analysis, 'bottom', settings)
        assert body['charts'][0]['y']['inverse'] and len(body['charts'][0]['series']) == len(fig.data)
    elif section == 'Конструкция':
        assert ids == [f'wells-{WELL}-construction']
        fig = well_charts.build(analysis, 'construction', settings)
        assert [s['name'] for s in body['charts'][0]['series']] == [t.name for t in fig.data]
        assert table(body, f'construction-{WELL}')['count'] == len(analysis['construction'])
    else:
        assert_table(table(body, f'signals-{WELL}'), analysis['signals'])
        topics = set(analysis['signals']['Раздел'])
        assert {'Забой', 'Вода', 'ГДИ'} <= topics


def test_raw_tables_exclude_and_58_sees_it(env):
    client, pid, projects = env
    body = run(client, pid, wells=[WELL], raw=True)
    raw_ids = [t['id'] for t in body['tables'] if t['id'].startswith('raw-')]
    assert raw_ids == [f'raw-{k}-{WELL}' for k in ('production', 'operations', 'water', 'bottom', 'construction')]
    bottom = table(body, f'raw-bottom-{WELL}')
    target = bottom['action']['ids'][0]          # самый свежий замер забоя
    before = table(body, f'metrics-{WELL}')['rows'][1][4]
    r = client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'bottom', 'add': [target], 'reason': 'тест'})
    assert r.status_code == 200 and r.json()['added'] == 1
    m = projects.manifest(pid)
    assert m['settings']['excluded_points'][target]['module'] == 'bottom'
    frames, *_ = legacy_inputs(projects, pid)
    assert target not in set(frames['bottom']['_point_id'])      # 5.8 видит исключение
    after = run(client, pid, wells=[WELL], raw=True)
    assert table(after, f'metrics-{WELL}')['rows'][1][4] != before
    assert client.post(f'/api/projects/{pid}/exclusions/undo').json()['removed'] == 1


def test_saved_view_in_58_format(env):
    client, pid, projects = env
    params = dict(wells=[WELL], kind='withdrawal', periods=['2024-2025'], fixed_dp2=True, dp2=250.0, threshold=15.0,
                  alignment='object', gdi_n=2, gdi_orientation='swapped', section='Конструкция',
                  charts=LABELS[:3], asof='2025-12-31')
    r = client.post(f'/api/projects/{pid}/state/wells', json={'params': params})
    assert r.status_code == 200, r.text
    saved = projects.manifest(pid)['settings']['panels']['well_dashboard']
    # Те же поля, что 5.8 кладёт в viewer['well_dashboard'] и читает «Экспорт»
    assert {k: saved[k] for k in ('wells', 'kind', 'periods', 'delta', 'threshold', 'method', 'asof', 'alignment')} == {
        'wells': [WELL], 'kind': 'withdrawal', 'periods': ['2024-2025'], 'delta': 250.0, 'threshold': 15.0,
        'method': None, 'asof': '2025-12-31', 'alignment': 'object'}
    assert saved['gdi']['n'] == 2 and saved['gdi']['orientation'] == 'swapped'
    back = client.get(f'/api/projects/{pid}/state/wells').json()['panel']
    for k, v in params.items():
        assert back[k] == v, k


def test_empty_and_limits(env):
    client, pid, projects = env
    body = run(client, pid, wells=[])
    assert not body['charts'] and any('Выберите скважину' in n['text'] for n in body['notes'])
    wells = ask(client, pid, 'wells')
    body = run(client, pid, wells=wells, section='Выводы и качество')
    assert len([t for t in body['tables'] if t['id'].startswith('signals-')]) == 4
    assert any('Показаны первые 4' in n['text'] for n in body['notes'])
    body = run(client, pid, wells=[WELL], kind='injection', periods=['нет такого'])
    assert any('Нет суточных данных' in n['text'] for n in body['notes'])


def test_chart_export_with_second_axis(env):
    client, pid, projects = env
    params = dict(wells=[WELL], charts=[well_charts.LABELS['daily']])
    r = client.post('/api/modules/wells/export', json={'project': pid, 'params': params, 'target': 'chart',
                                                       'id': f'wells-{WELL}-daily', 'format': 'svg', 'dpi': 300})
    assert r.status_code == 200 and r.content.lstrip().startswith(b'<')
