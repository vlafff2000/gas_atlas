"""Авторский надзор: давление по опорной сетке (одна скважина — одна группа) и выбор источника давления объекта."""
import pandas as pd
import pytest

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules import an_report

PRODUCTION = pd.DataFrame([
    ('1', '2025-11-01', 100_000), ('2', '2025-11-01', 50_000), ('3', '2025-11-01', 70_000),
    ('1', '2025-12-01', 90_000), ('2', '2025-12-01', 40_000), ('3', '2025-12-01', 60_000),
], columns=['well', 'date', 'q'])
PRODUCTION['date'] = pd.to_datetime(PRODUCTION.date)
PRODUCTION['kind'], PRODUCTION['period'] = 'withdrawal', '2025-2026'
# Наблюдательные скважины с пересчётом давления по уровню: по одной на группу, две горизонта у первой на одну дату.
RESPONSE = pd.DataFrame({
    'well': ['1', '1', '1', '3', '3'], 'date': pd.to_datetime(['2025-11-01', '2025-11-01', '2025-12-01', '2025-11-01', '2025-12-01']),
    'horizon': ['A', 'B', 'A', 'A', 'A'], 'level': [10.0, 12.0, 11.0, 20.0, 21.0],
    'pressure': [90.0, 92.0, 88.0, 70.0, 72.0],
})
MATCH = pd.DataFrame({'well': ['2', '2'], 'date': pd.to_datetime(['2025-11-01', '2025-12-01']), 'fact': [80.0, 81.0],
                      'model': [79.0, 80.0], 'object': 'Объект', 'scenario': 'S', 'fond': 'Э'})
OBJECT_COLUMN = pd.DataFrame({'date': pd.to_datetime(['2025-11-01', '2025-12-01']), 'pressure': [95.0, 90.0]})
MAPPING = {'1': {'group': 'ГСП-1'}, '2': {'group': 'ГСП 2'}, '3': {'group': 'ГСП_3'}}


def run(extra, params=None):
    data = Data({DatasetKind.PRODUCTION: PRODUCTION, **extra})
    data.mapping = MAPPING
    return an_report.AuthorReportModule().run(data, {'kind': 'withdrawal', 'periods': ['2025-2026'], 'annulus': [],
                                                    **(params or {})})


def group_chart(result):
    return next(c for c in result.charts if c.id.startswith('an-group-pressure'))


def test_reference_grid_builds_group_pressure_chart_by_unified_names():
    result = run({DatasetKind.RESPONSE: RESPONSE})
    chart = group_chart(result)
    assert {s.name: list(s.y) for s in chart.series} == {'ГСП 1': [91.0, 88.0], 'ГСП 3': [70.0, 72.0]}
    assert any(s.label == 'Рпл за сезон · 2025-2026' for s in result.summary)


def test_auto_prefers_object_column_and_shows_source():
    result = run({DatasetKind.RESPONSE: RESPONSE, DatasetKind.OBJECT_PRESSURE: OBJECT_COLUMN})
    assert any('столбец «Давление объекта»' in n.text for n in result.notes)
    assert any(s.label == 'Рпл за сезон · 2025-2026' and '-5,0' in s.value for s in result.summary)
    assert group_chart(result) is not None


def test_grid_source_is_used_even_when_object_column_is_loaded():
    result = run({DatasetKind.RESPONSE: RESPONSE, DatasetKind.OBJECT_PRESSURE: OBJECT_COLUMN}, {'pressure_source': 'grid'})
    assert any('опорная сетка (реагирование' in n.text for n in result.notes)


def test_match_source_is_a_switch_for_the_grid_and_auto_falls_back_to_it():
    result = run({DatasetKind.PRESSURE_MATCH: MATCH})
    assert {s.name for s in group_chart(result).series} == {'ГСП 2'}
    assert any('кроссплот, факт' in n.text for n in result.notes)


def test_object_source_without_column_gives_a_note_and_no_grid_chart():
    result = run({DatasetKind.RESPONSE: RESPONSE}, {'pressure_source': 'object'})
    assert not any(c.id.startswith('an-group-pressure') for c in result.charts)
    assert any('Давление объекта не построено' in n.text for n in result.notes)


def test_pressure_is_not_taken_from_a_measurement_more_than_30_days_away():
    pressure = OBJECT_COLUMN
    assert an_report.pressure_near(pressure, '2025-11-20') == 90.0
    assert an_report.pressure_near(pressure, '2025-10-20') == 95.0
    assert an_report.pressure_near(pressure, '2026-03-01') is None


def test_group_pressure_x_axis_cumulative_object_volume_or_date_by_default():
    # объект за сезон: 220 000 м³ в первые сутки, 190 000 во вторые → накопленный 0,22 и 0,41 млн м³
    by_date = group_chart(run({DatasetKind.RESPONSE: RESPONSE}))
    assert by_date.x.scale == 'time'
    by_cum = group_chart(run({DatasetKind.RESPONSE: RESPONSE}, {'group_x': 'cumulative'}))
    assert by_cum.x.scale == 'value' and by_cum.x.unit == 'млн м³'
    xs = {s.name: [round(float(v), 2) for v in s.x] for s in by_cum.series}
    assert xs == {'ГСП 1': [0.22, 0.41], 'ГСП 3': [0.22, 0.41]}
    assert {s.name: list(s.y) for s in by_cum.series} == {'ГСП 1': [91.0, 88.0], 'ГСП 3': [70.0, 72.0]}
