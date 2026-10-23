"""ГИС и ГВК в Атласе: графики по скважинам и пачкам, свод и таблица изменения ГВК.
Данные — литеральные, прямо в тесте; реальных данных компании в репозитории нет."""
import pandas as pd
import pytest

from atlas.contract import Data
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
    base = {'wells': ['115', '113'], 'packs': [], 'start': '', 'end': '', 'view': 'all'}
    return {**base, **kw}


def test_one_chart_per_well_and_metric_plus_svod():
    res = GisModule().run({GIS: _frame()}, _params())
    titles = [c.id for c in res.charts]
    assert titles == ['gis-gvk-115', 'gis-h_eff-115', 'gis-kg-115', 'gis-combo-115-верхняя', 'gis-combo-115-нижняя',
                      'gis-gvk-113', 'gis-h_eff-113', 'gis-kg-113', 'gis-combo-113-верхняя',
                      'gis-pack-gvk-верхняя', 'gis-pack-gvk-нижняя', 'gis-pack-h_eff-верхняя', 'gis-pack-h_eff-нижняя',
                      'gis-pack-kg-верхняя', 'gis-pack-kg-нижняя']


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


def test_builder_layout_adds_gis_chart_after_main_ones():
    data = Data({GIS: _frame()})
    data.settings = {'builder_layouts': {'items': [{'id': 'g1', 'name': 'ГВК', 'layout': {
        'series': [{'dataset': 'gis_packs', 'y': 'gvk_abs_m', 'wells': ['115']}], 'title': 'ГВК 115'}}]}}
    res = GisModule().run(data, _params(wells=['115'], builder_layouts=['ГВК']))
    assert res.charts[-1].id.startswith('builder-g1')
    assert not [n for n in res.notes if n.level == 'warning']


def test_view_toggle_keeps_one_metric_or_the_svod():
    only_gvk = GisModule().run({GIS: _frame()}, _params(view='gvk')).charts
    assert [c.id for c in only_gvk] == ['gis-gvk-115', 'gis-gvk-113']
    assert len(GisModule().run({GIS: _frame()}, _params()).charts) == 15
    svod = GisModule().run({GIS: _frame()}, _params(view='svod')).charts
    assert [c.id for c in svod] == ['gis-pack-gvk-верхняя', 'gis-pack-gvk-нижняя', 'gis-pack-h_eff-верхняя',
                                    'gis-pack-h_eff-нижняя', 'gis-pack-kg-верхняя', 'gis-pack-kg-нижняя']


def test_pack_chart_puts_every_well_on_one_chart():
    svod = GisModule().run({GIS: _frame()}, _params(view='svod')).charts
    upper = next(c for c in svod if c.id == 'gis-pack-gvk-верхняя')
    assert [s.name for s in upper.series] == ['скв. 113', 'скв. 115']
    assert sum(len(s.x) for s in upper.series) == 4


def test_combo_chart_has_change_columns_on_both_axes():
    combo = GisModule().run({GIS: _frame()}, _params(wells=['115'], view='combo')).charts
    chart = next(c for c in combo if c.id == 'gis-combo-115-верхняя')
    assert chart.y2 is not None
    bars = [s for s in chart.series if s.kind == 'bar']
    assert {s.axis for s in bars} == {'y', 'y2'}
    kg_bar = next(s for s in bars if s.axis == 'y')
    assert len(kg_bar.y) == 2 and kg_bar.y[0] == pytest.approx(-0.05)      # 0.30 → 0.25 и 0.25 → 0.28: два перехода


def test_intervals_table_reaches_the_module_through_project_select():
    """Интервалы нужны виду «Σ hi × Кг» и списку сезонов: без optional проект их отбрасывал, вкладка писала «нет интервалов»."""
    assert DatasetKind.GIS_INTERVALS in GisModule.spec.optional


def test_csv_pack_table_without_season_column_does_not_crash():
    """Выгрузка gis_packs из CSV не содержит колонки «season»: графики строятся, без весенних треугольников."""
    frame = _frame().drop(columns='season')
    for view in ('gvk', 'all'):
        res = GisModule().run({GIS: frame}, _params(wells=['115'], view=view))
        assert res.charts and all(s.symbol != 'triangle' for c in res.charts for s in c.series)


def test_empty_pack_name_goes_to_separate_pack():
    frame = _frame()
    frame.loc[0, 'pack'] = None
    res = GisModule().run({GIS: frame}, _params(wells=['115']))
    assert 'без пачки' in [s.name for c in res.charts for s in c.series]
