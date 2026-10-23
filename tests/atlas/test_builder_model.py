"""Конструктор графиков: векторы модели tNavigator (атлас/model_source.py) как набор данных."""
import datetime as dt
import types

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


def fake_summary():
    cols = [('TIME', ':+:+:+:+', 0, 'DAYS'), ('WGPR', '31', 0, 'SM3/DAY'), ('WBHP', '31', 0, 'BARSA'),
            ('WWPR', '31', 0, 'SM3/DAY'), ('WGPR', '32', 0, 'SM3/DAY'), ('FGPR', ':+:+:+:+', 0, 'SM3/DAY')]
    dates = [START, START + dt.timedelta(hours=12), START + dt.timedelta(days=1), START + dt.timedelta(days=2)]
    data = [[0, 100_000.0, 100.0, 5.0, 0.0, 1.0], [0.5, 120_000.0, 99.0, 6.0, 0.0, 1.0],
            [1, 0.0, 98.0, 0.0, 50_000.0, 1.0], [2, 80_000.0, 97.0, 4.0, 60_000.0, 1.0]]
    return types.SimpleNamespace(columns=cols, dates=dates, data=data)


@pytest.fixture()
def stub(tmp_path, monkeypatch):
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
