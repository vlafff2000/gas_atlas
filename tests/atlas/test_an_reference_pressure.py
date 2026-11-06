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
# «БД давлений по замерам»: эксплуатационные скважины с ГСП; скв. 4 без ГСП (наблюдательная) и строка без Рпл в среднее не входят.
SURVEY = pd.DataFrame({
    'well': ['1', '2', '3', '1', '3', '4', '2'],
    'date': pd.to_datetime(['2025-11-01', '2025-11-01', '2025-11-01', '2025-12-01', '2025-12-01', '2025-12-01', '2025-12-01']),
    'p_res': [90.0, 80.0, 70.0, 88.0, 72.0, 10.0, None],
    'group': ['ГСП-1', 'ГСП 2', 'ГСП_3', 'ГСП-1', 'ГСП_3', '', 'ГСП 2'],
})
OBJECT_COLUMN = pd.DataFrame({'date': pd.to_datetime(['2025-11-01', '2025-12-01']), 'pressure': [95.0, 90.0]})
MAPPING = {'1': {'group': 'ГСП-1'}, '2': {'group': 'ГСП 2'}, '3': {'group': 'ГСП_3'}}


def run(extra, params=None):
    data = Data({DatasetKind.PRODUCTION: PRODUCTION, **extra})
    data.mapping = MAPPING
    return an_report.AuthorReportModule().run(data, {'kind': 'withdrawal', 'periods': ['2025-2026'], 'annulus': [],
                                                    **(params or {})})


def group_chart(result):
    return next(c for c in result.charts if c.id.startswith('an-group-pressure'))


def test_mean_pressure_is_average_over_wells_with_gsp_on_each_date():
    # Тест: tests/atlas/test_an_reference_pressure.py::test_mean_pressure_is_average_over_wells_with_gsp_on_each_date
    pressure, reference, label = an_report.object_pressure_of(Data({DatasetKind.PRESSURE_SURVEY: SURVEY}))
    assert pressure.date.tolist() == list(pd.to_datetime(['2025-11-01', '2025-12-01']))
    assert pressure.pressure.tolist() == [80.0, 80.0]         # (90+80+70)/3 и (88+72)/2, без скв. 4 (нет ГСП) и без пустой строки
    assert pressure.wells.tolist() == [3, 2]
    assert 'среднее по эксплуатационным скважинам' in label and 'от 2 до 3' in label


def test_other_pressure_sources_are_not_used_even_when_loaded():
    data = Data({DatasetKind.OBJECT_PRESSURE: OBJECT_COLUMN})
    assert an_report.object_pressure_of(data)[0] is None
    both = Data({DatasetKind.OBJECT_PRESSURE: OBJECT_COLUMN, DatasetKind.PRESSURE_SURVEY: SURVEY})
    assert an_report.object_pressure_of(both)[0].pressure.tolist() == [80.0, 80.0]
    assert 'pressure_source' not in {p.name for p in an_report.AuthorReportModule().spec.params}


def test_report_builds_group_chart_from_survey_and_names_source():
    result = run({DatasetKind.PRESSURE_SURVEY: SURVEY})
    chart = group_chart(result)
    assert {s.name: list(s.y) for s in chart.series} == {'ГСП 1': [90.0, 88.0], 'ГСП 2': [80.0], 'ГСП 3': [70.0, 72.0]}
    assert any('БД давлений по замерам' in n.text for n in result.notes)


def test_without_survey_a_note_and_no_group_chart():
    result = run({DatasetKind.OBJECT_PRESSURE: OBJECT_COLUMN})
    assert not any(c.id.startswith('an-group-pressure') for c in result.charts)
    assert any('Давление объекта не построено' in n.text for n in result.notes)


def test_pressure_is_not_taken_from_a_measurement_more_than_30_days_away():
    pressure = OBJECT_COLUMN
    assert an_report.pressure_near(pressure, '2025-11-20') == 90.0
    assert an_report.pressure_near(pressure, '2025-10-20') == 95.0
    assert an_report.pressure_near(pressure, '2026-03-01') is None


def test_group_pressure_x_axis_cumulative_object_volume_or_date_by_default():
    by_date = group_chart(run({DatasetKind.PRESSURE_SURVEY: SURVEY}))
    assert by_date.x.scale == 'time'
    by_cum = group_chart(run({DatasetKind.PRESSURE_SURVEY: SURVEY}, {'group_x': 'cumulative'}))
    assert by_cum.x.scale == 'value' and by_cum.x.unit == 'млн м³'
