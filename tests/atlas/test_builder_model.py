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
