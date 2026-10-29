"""Конструктор графиков: гистограмма (вид «гистограмма») с категориями по оси X — скважины, группы или фильтр по названию."""
import numpy as np
import pandas as pd
import pytest

from atlas.contract import Data, ParamError
from atlas.domain import DatasetKind as K
from atlas.modules import builder

D = pd.to_datetime


@pytest.fixture()
def data():
    production = pd.DataFrame({
        'well': ['1', '1', '2', '2', '3', '3'], 'date': list(D(['2025-01-01', '2025-01-02'])) * 3, 'kind': 'withdrawal',
        'q': [100.0, 300.0, 50.0, np.nan, 10.0, 20.0], 'group': ['ГСП-1', 'ГСП-1', 'ГСП-1', 'ГСП-1', 'ГСП-2', 'ГСП-2'],
        '_point_id': [f'p{i}' for i in range(6)]})
    return Data({K.PRODUCTION: production})



def layout(*rows):
    return {'series': list(rows)}


def row(**kw):
    base = {'dataset': 'production', 'y': 'q', 'view': 'hist', 'x': 'date'}
    return {**base, **kw}


def values(result):
    chart = result.charts[0]
    series = chart.series[0]
    return list(series.x), [None if v != v else float(v) for v in series.y]


def test_histogram_all_wells_by_default_with_mean(data):
    result = builder.build(data, layout(row()))
    cats, ys = values(result)
    assert cats == ['1', '2', '3']
    assert ys == pytest.approx([0.2, 0.05, 0.015])       # среднее по скважине за период (значения ×0,001: единица поля — тыс. м³/сут → млн)
    assert result.charts[0].series[0].kind == 'bar'
    assert result.charts[0].x.scale == 'category' and result.charts[0].x.categories == ['1', '2', '3']


def test_explicit_wells_keep_chosen_order_and_show_gaps(data):
    result = builder.build(data, layout(row(x_cats=['3', '2', '9'], hist_agg='sum')))
    cats, ys = values(result)
    assert cats == ['3', '2', '9']
    assert ys[:2] == pytest.approx([0.03, 0.05])        # сумма: 3 и 2 (у скважины 2 один пропуск — сумма по остальным)
    assert ys[2] is None                                # скважины 9 нет в наборе — пропуск, не ноль
    assert any('без данных' in n.text for n in result.notes)


def test_filter_by_group_name_and_union_with_list(data):
    result = builder.build(data, layout(row(x_filter='3', x_cats=['1'])))
    cats, _ = values(result)
    assert cats == ['1', '3']                           # список и фильтр складываются


def test_groups_as_categories_use_group_key():
    groups = pd.DataFrame({'group': ['ГСП 2', 'ГСП-2', 'ГСП-1'], 'date': list(D(['2025-01-01'])) * 3, 'kind': 'withdrawal',
                           'q': [4.0, 6.0, 1.0], '_point_id': ['a', 'b', 'c']})
    result = builder.build(Data({K.PRODUCTION: groups}), layout(row(x_cats=['ГСП-2'], hist_agg='max')))
    cats, ys = values(result)
    assert len(cats) == 1                              # «ГСП 2» и «ГСП-2» — одна группа; подпись — как в данных
    assert ys == pytest.approx([0.006])


def test_histogram_next_to_date_series_is_skipped_with_note(data):
    result = builder.build(data, layout(row(), row(view='line', x='date', name='линия')))
    assert len(result.charts[0].series) == 1
    assert 'ось X одна' in ' '.join(n.text for n in result.notes)


def test_bad_agg_and_bad_list_are_param_errors():
    with pytest.raises(ParamError):
        builder.parse_layout(layout(row(hist_agg='median')))
    with pytest.raises(ParamError):
        builder.parse_layout(layout(row(x_cats='1')))
