"""Конструктор графиков: векторы модели tNavigator (атлас/model_source.py) как набор данных."""
import datetime as dt
import os
import types

import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas import model_source
from atlas.api import create_app
from atlas.contract import Data
from atlas.domain import DatasetKind as K
from atlas.modules import builder
from atlas.projects import Projects
from tests.atlas._wells_data import make_project
from tests.atlas.test_builder import frames

START = dt.datetime(2025, 1, 1)
FAKE: dict = {}


def fake_summary():
    cols = [('TIME', ':+:+:+:+', 0, 'DAYS'), ('WGPR', '31', 0, 'SM3/DAY'), ('WBHP', '31', 0, 'BARSA'),
            ('WWPR', '31', 0, 'SM3/DAY'), ('WGPR', '32', 0, 'SM3/DAY'), ('FGPR', ':+:+:+:+', 0, 'SM3/DAY')]
    dates = [START, START + dt.timedelta(hours=12), START + dt.timedelta(days=1), START + dt.timedelta(days=2)]
    data = [[0, 100_000.0, 100.0, 5.0, 0.0, 1.0], [0.5, 120_000.0, 99.0, 6.0, 0.0, 1.0],
            [1, 0.0, 98.0, 0.0, 50_000.0, 1.0], [2, 80_000.0, 97.0, 4.0, 60_000.0, 1.0]]
    return types.SimpleNamespace(columns=cols, dates=dates, data=data)


@pytest.fixture()
def stub(tmp_path, monkeypatch):
    monkeypatch.setenv('PXG_HOME', str(tmp_path / 'pxg_home'))
    anchor = tmp_path / 'GAS.SMSPEC'
    anchor.write_bytes(b'x')
    (tmp_path / 'GAS.UNSMRY').write_bytes(b'x')
    tnav = types.SimpleNamespace(read_summary=lambda *_: fake_summary())
    catalog = types.SimpleNamespace(load_names=lambda: {}, model_name=lambda a: 'Газ',
                                    load_folders=lambda: [str(tmp_path)],
                                    scan=lambda folders: [{'id': str(anchor), 'name': 'Газ', 'folder': str(tmp_path), 'summary': True}])
    monkeypatch.setattr(model_source, '_tnav', lambda: (tnav, catalog))
    model_source._cache.clear()
    return str(anchor)


def test_well_vectors_in_project_units(stub):
    frame, notes = model_source.frame([stub])
    assert not notes
    w31 = frame[frame.well == '31'].set_index('date')
    assert list(frame.columns[:3]) == ['well', 'date', 'model'] and set(frame.well) == {'31', '32'}
    assert 'fgpr' not in frame                                       # векторы объекта (F…) здесь не читаются
    assert w31.loc['2025-01-01', 'wgpr'] == 120.0                    # последняя запись суток, SM3/DAY → тыс. м³/сут
    assert w31.loc['2025-01-02', 'wgpr'] == 0.0                      # простой остаётся нулём
    assert w31.loc['2025-01-01', 'wbhp'] == pytest.approx(99.0 * 1.0197162)
    assert w31.loc['2025-01-01', 'wwpr'] == 6.0                      # вода остаётся в м³/сут
    assert model_source.column_meta('wgpr') == ('Дебит газа (модель)', 'тыс. м³/сут')


def test_builder_catalog_and_series(stub):
    frame, _ = model_source.frame([stub])
    data = Data({**frames(), K.MODEL: frame})
    cat = builder.catalog(data)
    fields = {f['id']: f for c in cat['categories'] for f in c['fields']}
    assert fields['model.wgpr']['unit'] == 'тыс. м³/сут' and fields['model.wgpr']['category'] == 'model'
    result = builder.build(data, {'series': [{'dataset': 'model', 'y': 'wgpr', 'wells': ['31']}]})
    series = result.charts[0].series
    assert len(series) == 1 and len(series[0].y) == 3 and series[0].y[0] == 120.0


def test_api_choose_models_and_use(tmp_path, stub):
    projects = Projects(tmp_path / 'p')
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    base = f'/api/projects/{pid}/builder/models'
    listed = client.get(base).json()
    assert listed['available'] and [m['selected'] for m in listed['models']] == [False]
    assert client.post(base, json={'selected': 'x'}).status_code == 400
    assert client.post(base, json={'selected': [stub]}).json()['models'][0]['selected'] is True
    data = projects.select(pid, (), tuple(K))
    assert K.MODEL in data and data.model_notes == []
    assert K.MODEL not in projects.select(pid, (), (K.PRODUCTION,))


def two_models():
    a, b = fake_frame('Газ-1', 1.0), fake_frame('Газ-2', 2.0)
    return pd.concat([a, b], ignore_index=True)


def fake_frame(name, k):
    days = pd.to_datetime(['2025-01-01', '2025-01-02'])
    return pd.DataFrame({'well': '31', 'date': days, 'model': name, 'wgpr': [10.0 * k, 20.0 * k]})


def test_row_picks_model_and_names_it():
    data = Data({K.MODEL: two_models()})
    cat = {d['id']: d for d in builder.catalog(data)['datasets']}
    assert cat['model']['models'] == ['Газ-1', 'Газ-2']
    row = {'dataset': 'model', 'y': 'wgpr', 'wells': ['31']}
    first = builder.build(data, {'series': [row]}).charts[0].series[0]
    second = builder.build(data, {'series': [{**row, 'model': 'Газ-2'}]}).charts[0].series[0]
    assert list(first.y) == [10.0, 20.0] and list(second.y) == [20.0, 40.0]
    assert 'Газ-1' in first.name and 'Газ-2' in second.name
    gone = builder.build(data, {'series': [{**row, 'model': 'нет такой'}]})
    assert not gone.charts or not gone.charts[0].series          # модель сняли с выбора: ряд пуст, а не молча другой


def test_model_minus_fact_formula():
    fact = pd.DataFrame({'well': '31', 'date': pd.to_datetime(['2025-01-01', '2025-01-02']), 'kind': 'withdrawal', 'q': [8_000.0, 25_000.0]})
    data = Data({K.PRODUCTION: fact, K.MODEL: two_models()})
    layout = {'series': [
        {'dataset': 'production', 'y': 'q', 'kind': 'withdrawal', 'key': 'date', 'transform': {'op': 'group', 'agg': 'sum'}},
        {'dataset': 'model', 'y': 'wgpr', 'key': 'date', 'transform': {'op': 'group', 'agg': 'sum'}},
        {'source': 'formula', 'formula': 'B - A', 'key': 'date', 'name': 'Модель − факт'}]}
    diff = builder.build(data, layout).charts[0].series[-1]
    assert list(diff.y) == [2.0, -5.0]                              # тыс. м³/сут: модель 10 и 20, факт 8 и 25


@pytest.fixture()
def cubes(stub, monkeypatch):
    """Подставные читалки кубов: 3 активные ячейки с объёмами 1, 2, 1; два шага рестарта."""
    model = types.SimpleNamespace(n_active=3, to_units=lambda arr, name, mode='rep': [list(arr)], _rep=np.array([0, 1, 2]),
                                  grid=types.SimpleNamespace(ni=1, nj=1))
    steps = [types.SimpleNamespace(date=dt.datetime(2025, 1, 1)), types.SimpleNamespace(date=dt.datetime(2025, 7, 1))]
    cube = {(0, 'SGAS'): [0.0, 0.5, 0.0], (1, 'SGAS'): [0.2, 0.6, 0.0],
            (0, 'PRESSURE'): [100.0, 100.0, 100.0], (1, 'PRESSURE'): [90.0, 80.0, 90.0], (0, 'INTEHEAD'): [0, 0, 1]}
    files = types.SimpleNamespace(
        iter_restart_steps=lambda path: steps, read_init=lambda path, kws: {'PORV': [1000.0, 2000.0, 1000.0], 'DEPTH': [1500.0, 1510.0, 1520.0]},
        read_restart_keyword=lambda path, step, kw: cube.get((steps.index(step), kw)) if kw != 'INTEHEAD' else cube[(0, kw)])
    ind = types.SimpleNamespace(
        load_model=lambda path: model,
        pick_step=lambda steps, want: min(steps, key=lambda s: abs(s.date - want)),
        gas_pore_volume=lambda m, porv, sg, thr: types.SimpleNamespace(total=2_000_000.0 * sum(sg)),
        gwc_map=lambda m, sg, thr: {(0, 0): 1.0}, gwc_stats=lambda m, g: types.SimpleNamespace(columns=1, mean=1500.0, mean_area=1510.0, min=1490.0, max=1520.0))
    FAKE.update(steps=steps, cube=cube, calls=[])
    par = types.SimpleNamespace(map_steps=lambda fn, m, todo, ctx, egrid: FAKE['calls'].append(len(todo)) or [fn(m, s, ctx) for s in todo])
    monkeypatch.setattr(model_source, '_indicators', lambda: (ind, files, par))
    folder = os.path.dirname(stub)
    found = {k: os.path.join(folder, 'GAS.' + k) for k in ('EGRID', 'INIT', 'UNRST')}
    for path in found.values():
        open(path, 'wb').write(b'x')
    monkeypatch.setattr(model_source, '_cube_files', lambda anchor: found)
    return stub


def test_cube_indicators_weighted_by_pore_volume(cubes):
    frame, notes = model_source.cubes_frame([cubes])
    assert not notes and list(frame.date.dt.strftime('%m-%d')) == ['01-01', '07-01']
    first, second = frame.iloc[0], frame.iloc[1]
    assert first.sg_avg == pytest.approx(0.5 * 2 / 4) and second.sg_avg == pytest.approx((0.2 + 1.2) / 4)
    assert first.p_avg == pytest.approx(100 * 1.0197162) and second.p_avg == pytest.approx(85 * 1.0197162)   # (90+160+90)/4
    assert first.gpv == pytest.approx(1.0) and first.gwc_mean == -1500.0 and first.gwc_min == -1520.0 and first.gwc_max == -1490.0


def test_cubes_in_builder_and_api(tmp_path, cubes):
    projects = Projects(tmp_path / 'p')
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    base = f'/api/projects/{pid}/builder/models'
    assert K.MODEL_OBJECT not in projects.select(pid, (), tuple(K))      # без запроса кубы не читаются
    out = client.post(base, json={'selected': [cubes], 'cubes': True}).json()
    assert out['cubes'] is True
    data = projects.select(pid, (), tuple(K))
    fields = {f['id'] for c in builder.catalog(data)['categories'] for f in c['fields']}
    assert {'model_object.p_avg', 'model_object.gwc_mean', 'model.wgpr'} <= fields
    result = builder.build(data, {'series': [{'dataset': 'model_object', 'y': 'p_avg'}]})
    assert len(result.charts[0].series[0].y) == 2


def test_cubes_limited_by_restart_dates(tmp_path, cubes):
    projects = Projects(tmp_path / 'p2')
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    base = f'/api/projects/{pid}/builder/models'
    out = client.post(base, json={'selected': [cubes], 'cubes': True, 'cubes_from': '2025-03-01', 'cubes_to': '2025-12-31'}).json()
    assert (out['cubes_from'], out['cubes_to']) == ('2025-03-01', '2025-12-31')
    data = projects.select(pid, (), tuple(K))
    assert list(data[K.MODEL_OBJECT].date.dt.strftime('%m-%d')) == ['07-01']          # шаг 1 января вне периода
    assert client.post(base, json={'selected': [cubes], 'cubes_from': '2026-01-01', 'cubes_to': '2025-01-01'}).status_code == 400
    assert client.post(base, json={'selected': [cubes], 'cubes_from': 'вчера'}).status_code == 400
    client.post(base, json={'selected': [cubes], 'cubes_from': '2030-01-01', 'cubes_to': ''})
    assert any('нет шагов' in n for n in projects.select(pid, (), tuple(K)).model_notes)


def test_cells_for_crossplot(tmp_path, cubes):
    projects = Projects(tmp_path / 'p3')
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    base = f'/api/projects/{pid}/builder/models'
    cells = {'dates': ['2025-01-01', '2025-07-20'], 'k_from': 2, 'k_to': 0, 'max_points': 100}
    out = client.post(base, json={'selected': [cubes], 'cells': cells}).json()
    assert out['cells']['dates'] == ['2025-01-01', '2025-07-20']
    data = projects.select(pid, (), tuple(K))
    frame = data[K.MODEL_CELLS]
    assert sorted(frame.restart.unique()) == ['2025-01-01', '2025-07-01']              # 20 июля → ближайший рестарт 1 июля
    assert any('ближайший' in n for n in data.model_notes)
    first = frame[frame.restart == '2025-07-01'].sort_values('k')
    assert list(first.k) == [2, 3] and list(first.depth) == [-1510.0, -1520.0]            # слой 1 отсечён; глубина а.о. со знаком минус
    assert list(first.sg) == [0.6, 0.0] and list(first.porv) == [2.0, 1.0]
    result = builder.build(data, {'series': [{'dataset': 'model_cells', 'x': 'sg', 'y': 'p', 'view': 'points'}]})
    assert sorted(s.name for s in result.charts[0].series) == ['Давление в ячейке (модель) · 2025-01-01', 'Давление в ячейке (модель) · 2025-07-01']
    dates = client.get(base + '/restarts', params={'model': cubes}).json()
    assert dates['dates'] == ['2025-01-01', '2025-07-01']
    assert client.post(base, json={'selected': [cubes], 'cells': {'dates': ['x']}}).status_code == 400
    assert client.post(base, json={'selected': [cubes], 'cells': {'dates': [], 'k_from': 5, 'k_to': 2}}).status_code == 400
    small = {'dates': ['2025-01-01'], 'k_from': 1, 'k_to': 0, 'max_points': 100}
    assert client.post(base, json={'selected': [cubes], 'cells': small}).status_code == 200


def test_cells_are_thinned_visibly(cubes):
    cfg = {'dates': ['2025-01-01'], 'k_from': 1, 'k_to': 0, 'max_points': 2}
    frame, notes = model_source.read_cells(cubes, 'Газ', cfg)
    assert list(frame.k) == [1, 3] and any('каждая 2-я' in n for n in notes)


def test_cubes_kept_on_disk_and_only_new_steps_counted(cubes):
    model_source.cubes_frame([cubes])
    assert FAKE['calls'] == [2]
    model_source._cache.clear()                                      # «перезапуск»: память пуста, диск остался
    again, _ = model_source.cubes_frame([cubes])
    assert FAKE['calls'] == [2] and len(again) == 2                  # ничего не пересчитано
    FAKE['steps'].append(types.SimpleNamespace(date=dt.datetime(2025, 8, 1)))                # в рестарт дописался шаг
    FAKE['cube'].update({(2, 'SGAS'): [0.1, 0.1, 0.1], (2, 'PRESSURE'): [70.0, 70.0, 70.0]})
    model_source._cache.clear()
    grown, _ = model_source.cubes_frame([cubes])
    assert FAKE['calls'] == [2, 1] and len(grown) == 3 and grown.p_avg.iloc[-1] == pytest.approx(70 * 1.0197162)


def test_refresh_recomputes_cubes(tmp_path, cubes):
    projects = Projects(tmp_path / 'p4')
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    base = f'/api/projects/{pid}/builder/models'
    client.post(base, json={'selected': [cubes], 'cubes': True})
    projects.select(pid, (), tuple(K))
    assert FAKE['calls'] == [2]
    model_source._cache.clear()
    projects.select(pid, (), tuple(K))
    assert FAKE['calls'] == [2]                                      # с диска
    assert client.post(base + '/refresh', json={}).status_code == 200
    projects.select(pid, (), tuple(K))
    assert FAKE['calls'] == [2, 2]                                   # сброшено: считается заново


def test_color_by_third_value(cubes):
    cfg = {'dates': ['2025-01-01', '2025-07-01'], 'k_from': 1, 'k_to': 0, 'max_points': 100}
    frame, _ = model_source.cells_frame([cubes], cfg)
    data = Data({K.MODEL_CELLS: frame})
    row = {'dataset': 'model_cells', 'x': 'p', 'y': 'sg', 'view': 'points', 'color_by': 'depth'}
    result = builder.build(data, {'series': [row]})
    first = result.charts[0].series[0]
    assert list(first.values) == [-1500.0, -1510.0, -1520.0] and first.values_label == 'Глубина ячейки, а.о. (модель), м'
    import json
    from atlas.contract import _series_json
    assert _series_json(first)['values'] == [-1500.0, -1510.0, -1520.0]
    plain = builder.build(data, {'series': [{**row, 'color_by': ''}]}).charts[0].series[0]
    assert plain.values is None
    wrong = builder.build(data, {'series': [{**row, 'color_by': 'нет такого'}]})
    assert any('нет такого' in n.text for n in wrong.notes) and wrong.charts[0].series[0].values is None
    lined = builder.build(data, {'series': [{**row, 'view': 'line'}]})
    assert any('работает у рядов с видом' in n.text for n in lined.notes)
