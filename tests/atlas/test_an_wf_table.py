"""«Авторский надзор»: таблица ВФ по скважинам (табл. 1.6) и график — расчёт на малом примере вручную."""
import numpy as np
import pandas as pd
import pytest

from atlas.contract import Data, ParamError
from atlas.domain import DatasetKind
from atlas.modules import an_wf_table as wf


def production():
    rows = []
    for period, start in (('2023/24', '2023-11-01'), ('2024/25', '2024-11-01')):
        for day in pd.date_range(start, periods=150):
            for well, q in (('1', 100000), ('2', 100000), ('3', 100000), ('4', 0), ('5', 100000)):
                if well == '3' and period == '2024/25':
                    q = 0
                rows.append((well, day, q, 'withdrawal', period))
    return pd.DataFrame(rows, columns=['well', 'date', 'q', 'kind', 'period'])


def water():
    rows = [
        ('1', '2023-12-01', 10.0, ''), ('1', '2024-01-01', 20.0, ''),      # два замера: среднее 15, максимум 20
        ('1', '2024-12-01', 0.0, ''),                                      # сухо
        ('2', '2023-12-01', 0.0, ''), ('2', '2024-12-01', np.nan, 'КРС'),  # сухо; простой по причине
        ('3', '2023-12-01', 44.8, ''), ('3', '2024-12-01', 0.0, ''),       # скв. 3 в 2024/25 без расхода: простой
        ('5', '2023-12-01', 7.0, ''),
    ]
    return pd.DataFrame(rows, columns=['well', 'date', 'water_factor_l', 'comment']).assign(date=lambda d: pd.to_datetime(d.date))


def run(overrides=None, **params):
    data = Data({DatasetKind.WATER: water(), DatasetKind.PRODUCTION: production()})
    data.mapping = {w: {'group': 'ГСП 9'} for w in '12345'}
    if overrides:
        data.settings[wf.OVERRIDES_KEY] = overrides
    base = {'groups': ['ГСП 9'], 'periods': [], 'agg': 'mean', **params}
    return wf.WaterFactorTableModule().run(data, base)


def matrix(result):
    return result.tables[0].frame.set_index('well')


def test_cells_value_dry_idle_and_missing():
    m = matrix(run())
    assert m.loc['1', 's0'] == '15' and m.loc['1', 's1'] == wf.DRY       # среднее по двум замерам; замер без воды
    assert m.loc['2', 's0'] == wf.DRY and m.loc['2', 's1'] == wf.IDLE    # КРС — простой
    assert m.loc['3', 's0'] == '44,8' and m.loc['3', 's1'] == wf.IDLE    # ВФ=0 при нулевом расходе газа — простой
    assert m.loc['4', 's0'] == wf.IDLE                                   # скважина без суток с расходом в сезоне — простой, а не «сухо»... но замеров нет
    assert m.loc['5', 's1'] == wf.NONE                                   # работала, замера нет


def test_max_instead_of_mean_and_colors():
    r = run(agg='max')
    assert matrix(r).loc['1', 's0'] == '20'
    fills = {(s.fill, tuple(s.rows), s.columns[0]) for s in r.tables[0].styles}
    assert (wf.DRY_FILL, (0,), 's1') in fills and (wf.IDLE_FILL, (1, 2, 3), 's1') in fills


def test_chart_counts_wells_with_water_and_max_wf():
    r = run()
    bars, line = r.charts[0].series
    assert bars.y.tolist() == [3, 0] and line.y[0] == pytest.approx(44.8) and np.isnan(line.y[1])
    assert r.charts[0].y2 is not None and line.axis == 'y2'


def test_manual_override_wins_and_is_reported():
    r = run({'1|2024/25': {'status': 'value', 'value': 5.5}, '5|2024/25': {'status': 'idle'}})
    m = matrix(r)
    assert m.loc['1', 's1'] == '5,5' and m.loc['5', 's1'] == wf.IDLE
    check = r.tables[2].frame.set_index('key')
    assert check.loc['1|2024/25', 'auto'] == wf.DRY and check.loc['1|2024/25', 'manual'] == '5,5'
    assert r.tables[1].frame.set_index('season').loc['2024/25', 'wet'] == 1


def test_parse_manual():
    assert wf.parse_manual('') is None and wf.parse_manual('Простой') == {'status': 'idle'}
    assert wf.parse_manual('сухо') == {'status': 'dry'} and wf.parse_manual('12,5') == {'status': 'value', 'value': 12.5}
    for bad in ('abc', '0', '-3'):
        with pytest.raises(ParamError):
            wf.parse_manual(bad)
    assert wf.with_overrides({}, {'1|2023/24': {'manual': 'простой'}})[wf.OVERRIDES_KEY] == {'1|2023/24': {'status': 'idle'}}
    assert wf.with_overrides({wf.OVERRIDES_KEY: {'a|b': {'status': 'idle'}}}, {'a|b': ''})[wf.OVERRIDES_KEY] == {}


def test_without_factor_column_gives_warning():
    data = Data({DatasetKind.WATER: water().drop(columns='water_factor_l'), DatasetKind.PRODUCTION: production()})
    r = wf.WaterFactorTableModule().run(data, {'groups': [], 'periods': [], 'agg': 'mean'})
    assert not r.tables and r.notes[0].level == 'warning'


def test_wf_status_endpoint_saves_to_project_settings(tmp_path):
    import sys
    sys.path.insert(0, 'tests/atlas')
    from starlette.testclient import TestClient

    from _wells_data import make_project
    from atlas.api import create_app
    from atlas.projects import Projects

    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    r = client.post(f'/api/projects/{pid}/wf-status', json={'changes': {'31|2023/24': {'manual': 'простой'}, '45|2023/24': {'manual': '12,5'}}})
    assert r.status_code == 200, r.text
    assert projects.manifest(pid)['settings'][wf.OVERRIDES_KEY] == {'31|2023/24': {'status': 'idle'}, '45|2023/24': {'status': 'value', 'value': 12.5}}
    assert client.post(f'/api/projects/{pid}/wf-status', json={'changes': {'31|2023/24': {'manual': 'мусор'}}}).status_code == 400
