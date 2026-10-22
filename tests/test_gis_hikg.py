"""ГИС: Σ(hi × Кг) по исследованиям — расчёт и вид в модуле ГИС.
Данные — литеральные, прямо в тесте; реальных данных компании в репозитории нет."""
import pandas as pd
import pytest

from atlas.domain import DatasetKind
from atlas.engine.modules import gis_hikg
from atlas.modules.gis import GisModule

INTERVALS = DatasetKind.GIS_INTERVALS


def _intervals():
    return pd.DataFrame({
        'well': ['115', '115', '115', '115', '115', '113'],
        'date': pd.to_datetime(['2024-10-01', '2024-10-01', '2024-10-01', '2024-10-01', '2025-03-01', '2024-10-01']),
        'season': ['осень', 'осень', 'осень', 'осень', 'весна', 'осень'],
        'investigation': [1, 1, 1, 2, 3, 4],
        'pack': ['верхняя', 'верхняя', 'верхняя', 'нижняя', 'верхняя', 'верхняя'],
        'hi_m': [2.0, 1.5, 3.0, 4.0, 2.5, 1.0],
        'kg': [0.30, 0.25, 0.0, 0.20, 0.40, None],
    })


def _params(**kw):
    base = {'wells': ['115', '113'], 'packs': [], 'seasons': [], 'start': '', 'end': '', 'view': 'hikg'}
    return {**base, **kw}


def test_product_counts_kg_at_or_below_quarter_but_not_zero():
    prepared = gis_hikg.prepare(_intervals())
    table = gis_hikg.sums(prepared)
    first = table[(table['well'] == '115') & (table['investigation'] == 1)].iloc[0]
    # 2,0×0,30 + 1,5×0,25 — Кг 0,25 учитывается; 3,0×0 — нет
    assert first['hikg'] == pytest.approx(2.0 * 0.30 + 1.5 * 0.25)
    assert first['intervals'] == 2


def test_missing_kg_is_skipped_and_reported():
    prepared = gis_hikg.prepare(_intervals())
    assert gis_hikg.skipped(prepared) == 1                  # Кг пустой у скважины 113


def test_season_label_and_investigation_by_date_without_number():
    raw = _intervals().drop(columns=['investigation'])
    prepared = gis_hikg.prepare(raw)
    assert set(prepared['season']) == {'осень 2024', 'весна 2025'}
    assert set(prepared['investigation']) == {'2024-10-01', '2025-03-01'}


def test_view_gives_table_per_investigation_and_pack_and_chart_per_well():
    res = GisModule().run({INTERVALS: _intervals()}, _params())
    table = next(t for t in res.tables if t.id == 'gis-hikg')
    assert len(table.frame) == 4                             # 115: 1 верхняя, 2 нижняя, 3 верхняя; 113: 4 верхняя
    assert [c.id for c in res.charts] == ['gis-hikg-113', 'gis-hikg-115']


def test_season_filter_keeps_only_chosen_seasons():
    res = GisModule().run({INTERVALS: _intervals()}, _params(seasons=['весна 2025']))
    table = next(t for t in res.tables if t.id == 'gis-hikg')
    assert list(table.frame['well']) == ['115']
    assert list(table.frame['season']) == ['весна 2025']


def test_seasons_listed_as_options_for_param():
    options = GisModule().options('seasons', {INTERVALS: _intervals()}, _params())
    assert options == ['осень 2024', 'весна 2025']


def test_no_intervals_gives_note_not_error():
    res = GisModule().run({}, _params())
    assert not res.charts and not res.tables
    assert any('интервалов' in n.text for n in res.notes)
