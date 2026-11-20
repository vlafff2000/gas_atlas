"""Плитки паспорта: ревизия КРУ по сезонам и КРС по годам (общая тепловая карта, не новый компонент)."""
import pandas as pd

from atlas import passport_tiles as pt
from atlas.passport_blocks import blocks


def priority():
    return pd.DataFrame({'well': ['31', '32', '33'], 'group': ['ГСП-1', 'ГСП-1', 'ГСП-2'],
                         'sand': ['2023-2024, 2025-2026', '2024-2025', '2022-2023']})


def works():
    return pd.DataFrame({'well': ['31', '31', '45'], 'year': [2019, 2023, 2022], 'work_type': ['Замена фильтра', 'Колтюбинг без СКО', 'Замена фильтра'],
                         'detail': ['КР 1.094', '', '']})


def test_sand_seasons_parses_text():
    assert pt.sand_seasons('2023-2024, 2025–2026') == ['2023-2024', '2025-2026']
    assert pt.sand_seasons(None) == [] and pt.sand_seasons('') == []


def test_kru_tile_three_states_derived_from_group():
    tile = pt.kru_tiles(priority(), '31')
    assert tile['columns'] == ['2022-2023', '2023-2024', '2024-2025', '2025-2026']
    # 2022-2023: песок нашли только в ГСП-2 → для ГСП-1 ревизии по данным не было; 2023-2024 песок у скважины; 2024-2025 у соседа — у этой скважины ревизия без песка
    assert tile['cells'] == [None, 1, 0, 1]
    assert pt.kru_tiles(priority(), '99') is None and pt.kru_tiles(None, '31') is None


def test_krs_tile_marks_years_and_keeps_types():
    tile = pt.krs_tiles(works(), '31')
    assert tile['columns'] == [str(y) for y in range(2019, 2024)]
    assert tile['cells'] == [1, 0, 0, 0, 1] and tile['texts'][0] == 'Замена фильтра' and tile['texts'][1] == ''
    assert pt.krs_tiles(works(), '99') is None


def test_blocks_use_common_heatmap():
    card = {'seasons': [], 'daily': {}, 'gdi_diagrams': [], 'gdi': [], 'krs': {'works': []},
            'tiles': {'kru': pt.kru_tiles(priority(), '31'), 'krs': pt.krs_tiles(works(), '31')}}
    charts, _ = blocks(card)
    heat = {c.id: c for c in charts if c.heat is not None}
    assert set(heat) == {'passport-kru-tiles', 'passport-krs-tiles'}
    kru = heat['passport-kru-tiles'].heat
    assert kru.values == [[None, 1.0, 0.0, 1.0]] and kru.texts[0][0] == 'нет ревизии'
