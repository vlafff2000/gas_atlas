"""ГИС и ГВК в Атласе: графики по скважинам и пачкам, свод и таблица изменения ГВК.
Данные — литеральные, прямо в тесте; реальных данных компании в репозитории нет."""
import pandas as pd

from atlas.domain import DatasetKind
from atlas.modules.gis import GisModule

GIS = DatasetKind.GIS_PACKS


def _frame():
    return pd.DataFrame({
        'well': ['115', '115', '115', '115', '113'],
        'date': pd.to_datetime(['2024-10-01', '2025-03-01', '2025-10-01', '2025-10-01', '2024-10-01']),
        'season': ['осень', 'весна', 'осень', 'осень', 'осень'],
        'pack': ['верхняя', 'верхняя', 'верхняя', 'нижняя', 'верхняя'],
        'gvk_abs_m': [-1000.0, -1001.0, -1003.0, -1010.0, -990.0],
        'h_eff_m': [1.5, 1.2, 1.4, 2.0, 3.0],
        'kg_avg': [0.3, 0.25, 0.28, 0.4, 0.5],
    })


def _params(**kw):
    base = {'wells': ['115', '113'], 'packs': [], 'start': '', 'end': ''}
    return {**base, **kw}


def test_one_chart_per_well_and_metric_plus_svod():
    res = GisModule().run({GIS: _frame()}, _params())
    titles = [c.id for c in res.charts]
    assert titles == ['gis-gvk-115', 'gis-h_eff-115', 'gis-kg-115', 'gis-gvk-113', 'gis-h_eff-113', 'gis-kg-113', 'gis-svod-gvk']


def test_spring_points_are_triangles_and_lines_follow_pack():
    chart = GisModule().run({GIS: _frame()}, _params(wells=['115'])).charts[0]
    names = [(s.name, s.kind, s.symbol) for s in chart.series]
    assert ('верхняя', 'line', 'circle') in names
    assert ('верхняя: весна', 'points', 'triangle') in names
    line = next(s for s in chart.series if s.name == 'верхняя')
    assert line.y == [-1000.0, -1001.0, -1003.0] and line.group == 'верхняя'


def test_packs_and_dates_filter_the_points():
    res = GisModule().run({GIS: _frame()}, _params(wells=['115'], packs=['нижняя']))
    assert [s.name for s in res.charts[0].series] == ['нижняя']
    res = GisModule().run({GIS: _frame()}, _params(wells=['115'], start='2025-01-01', end='2025-06-30'))
    assert res.charts[0].series[1].y == [-1001.0]


def test_change_table_gives_delta_and_rate_per_pack():
    res = GisModule().run({GIS: _frame()}, _params(wells=['115']))
    row = res.tables[0].frame.set_index(['well', 'pack']).loc[('115', 'верхняя')]
    assert row['delta'] == -3.0 and row['n'] == 3
    assert round(row['rate'], 2) == -3.0                    # −3 м за один год (с 01.10.2024 по 01.10.2025)


def test_no_data_or_no_wells_gives_note():
    assert GisModule().run({}, _params()).notes[0].text.startswith('В данных нет')
    assert GisModule().run({GIS: _frame()}, _params(wells=[])).notes[0].text == 'Выберите скважины.'
