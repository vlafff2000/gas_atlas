"""Фонды скважин: подсказка с причиной, ручной выбор важнее, общий для программ, хранится в проекте."""
import pandas as pd
import pytest
from starlette.testclient import TestClient

from _wells_data import make_project
from atlas import well_funds as well_fund
from atlas.api import create_app
from atlas.projects import Projects


def test_hint_rules():
    assert well_fund.hint(True, True, True, True)[0] == 'production'
    assert well_fund.hint(False, True, False, True)[0] == 'observation'
    assert well_fund.hint(False, True, True, False)[0] == 'observation'
    fund, why = well_fund.hint(False, True, False, False)
    assert fund == 'geophysical' and 'ГИС' in why
    assert well_fund.hint(False, False, False, False)[0] == ''


def test_table_manual_overrides_hint():
    gis = pd.DataFrame({'well': ['7', '8.0'], 'date': pd.to_datetime(['2025-01-01'] * 2), 'pack': ['A', 'A']})
    geo = pd.DataFrame({'well': ['7', '8'], 'perf_top': [None, -900.0], 'perf_bottom': [None, -950.0]})
    rows = {r['well']: r for r in well_fund.table({'gis_packs': gis, 'well_geo': geo}, {}, {})}
    assert rows['7']['fund'] == 'geophysical' and not rows['7']['manual']
    assert rows['8']['fund'] == 'observation'
    settings = well_fund.with_funds({}, {'7': 'observation', '8': 'geophysical'})
    rows = {r['well']: r for r in well_fund.table({'gis_packs': gis, 'well_geo': geo}, {}, settings)}
    assert rows['7']['fund'] == 'observation' and rows['7']['manual'] and rows['7']['hint'] == 'geophysical'
    assert rows['8']['fund'] == 'geophysical'
    back = well_fund.with_funds(settings, {'7': 'auto'})
    assert well_fund.fund_of(back, 7) == '' and well_fund.fund_of(back, '8.0') == 'geophysical'
    with pytest.raises(ValueError):
        well_fund.with_funds({}, {'7': 'неизвестный'})


def test_api_roundtrip(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    got = client.get(f'/api/projects/{pid}/well-fund').json()
    assert [f['id'] for f in got['funds']][:3] == ['production', 'observation', 'geophysical']
    assert got['wells'] and all(r['fund'] == 'production' for r in got['wells'])
    well = got['wells'][0]['well']
    saved = client.post(f'/api/projects/{pid}/well-fund', json={'changes': {well: 'geophysical'}, 'revision': got['revision']})
    assert saved.status_code == 200
    row = next(r for r in saved.json()['wells'] if r['well'] == well)
    assert row['fund'] == 'geophysical' and row['manual'] and row['hint'] == 'production'
    assert projects.manifest(pid)['settings']['well_funds'] == {well: 'geophysical'}
    assert client.post(f'/api/projects/{pid}/well-fund', json={'changes': {well: 'xx'}}).status_code == 400
