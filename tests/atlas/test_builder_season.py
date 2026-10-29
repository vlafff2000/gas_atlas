"""Конструктор графиков: преобразование «по сезонам» — сумма или сводка по периоду расхода, X — первые сутки сезона."""
import pandas as pd
import pytest

from atlas.contract import Data
from atlas.domain import DatasetKind as K
from atlas.modules import builder

D = pd.to_datetime


@pytest.fixture()
def data():
    production = pd.DataFrame({
        'well': ['1', '1', '1', '1'], 'date': D(['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-04']), 'kind': 'withdrawal',
        'q': [100.0, 200.0, 300.0, 400.0],                              # тыс. м³/сут
        'period': ['Отбор 1', 'Отбор 1', 'Отбор 2', 'Отбор 2'], '_point_id': ['a', 'b', 'c', 'd']})
    return Data({K.PRODUCTION: production})


def row(**kw):
    return {'dataset': 'production', 'y': 'q', 'view': 'bar', 'x': 'date', 'transform': {'op': 'season', 'agg': 'sum'}, **kw}


def test_season_sum_is_volume_per_season_at_first_day(data):
    result = builder.build(data, {'series': [row()]})
    series = result.charts[0].series[0]
    assert list(pd.to_datetime(series.x)) == [D('2025-01-01'), D('2025-01-03')]
    assert list(series.y) == pytest.approx([0.0003, 0.0007])     # сумма суточных за сезон, с переводом единиц поля (×0,001 и ÷1000)
    assert 'за сезон' in series.name


def test_season_mean_keeps_daily_units(data):
    result = builder.build(data, {'series': [row(transform={'op': 'season', 'agg': 'mean'})]})
    series = result.charts[0].series[0]
    assert list(series.y) == pytest.approx([0.15, 0.35])        # среднее суточное за сезон, единица поля


def test_season_cumulative_runs_across_seasons(data):
    result = builder.build(data, {'series': [row(transform={'op': 'season', 'agg': 'sum', 'cum': True})]})
    series = result.charts[0].series[0]
    assert list(series.y) == pytest.approx([0.0003, 0.001])      # нарастающий итог по сезонам, не сбрасывается


def test_season_without_periods_is_a_note_not_an_error():
    frame = pd.DataFrame({'well': ['1'], 'date': D(['2025-01-01']), 'kind': 'withdrawal', 'q': [5.0], '_point_id': ['a']})
    result = builder.build(Data({K.PRODUCTION: frame}), {'series': [row()]})
    assert any('периодов расхода' in n.text for n in result.notes)
