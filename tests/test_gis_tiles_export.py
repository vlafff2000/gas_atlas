"""Экспорт: вкладка «ГИС и ГВК: плитка ГНТ и Кг» идёт общим планом выгрузки (оформление, файлы, архив, Word — общие)."""
import pandas as pd

from atlas.api_export import GIS_TILES, available, choices, options_from, with_gis_tiles
from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.engine.core import reporting

GIS = DatasetKind.GIS_PACKS


def _data():
    frame = pd.DataFrame({
        'well': ['115', '115', '115', '113-а'],
        'date': pd.to_datetime(['2024-10-01', '2025-03-01', '2025-10-01', '2024-10-01']),
        'season': ['осень', 'весна', 'осень', 'осень'],
        'pack': ['верхняя', 'верхняя', 'нижняя', 'верхняя'],
        'gvk_abs_m': [-1000.0, -1001.0, -1003.0, -990.0],
        'h_eff_m': [1.5, 1.2, 2.0, 3.0],
        'kg_avg': [0.3, 0.25, 0.4, 0.5],
    })
    data = Data({GIS: frame})
    data.settings = {}
    return data


def _plan(form):
    data = _data()
    options, source, raw = options_from({'modules': [GIS_TILES], **form}, data)
    return options, with_gis_tiles(reporting.plan(source, data.mapping, data.settings, options, raw), data, options)


def test_tab_is_offered_with_choices():
    data = _data()
    assert GIS_TILES in available({k.value: v for k, v in data.raw.items()})
    got = choices(data)['gis_tiles']
    assert got['wells'] == ['113-а', '115'] and got['packs'] == ['верхняя', 'нижняя'] and 'осень 2024' in got['seasons']


def test_charts_go_to_plan_with_meta_and_hand_axes():
    options, plan = _plan({'gis_tiles_wells': ['115', '113-а'], 'gis_tiles_gnt_max': '10'})
    assert [j.module for j in plan.jobs] == [GIS_TILES] * 3
    fig = plan.jobs[0].render()
    assert fig.layout.meta['wells'] and fig.layout.meta['periods']
    assert {m for j in plan.jobs for m in j.render().layout.meta['wells']} == {'113-а', '115'}
    assert 'ГИС_плитка_gis-tile-table' in plan.tables


def test_default_is_first_wells_and_empty_choice_is_nothing():
    assert _plan({})[0][GIS_TILES]['wells'] == ['113-а', '115']
    assert _plan({'gis_tiles_wells': []})[1].jobs == []
