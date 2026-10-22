"""Ряды ЭЛПРО на суточном графике «Производительность скважин»: каждый ряд — на своей правой оси, пропуск ЭЛПРО —
разрыв, без выбора график как раньше; в экспорте — по одному рисунку на скважину и режим."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules._elpro_series import MAX_RIGHT_AXES, picked_extras
from atlas.modules._production import Selection, curve_chart
from atlas.api_export import with_elpro

PROD, ELPRO = DatasetKind.PRODUCTION, DatasetKind.ELPRO
DAYS = pd.to_datetime(['2025-06-01', '2025-06-02', '2025-06-03'])


def frames():
    # 01.06 и 03.06 — записи ЭЛПРО есть, 02.06 — пропуск ЭЛПРО; КРУ 150 обрезается до 100
    prod = pd.DataFrame({'well': '101', 'date': DAYS, 'q': [1000.0, 2000.0, 3000.0], 'kind': 'withdrawal', 'period': '2025',
                         'hours': [24.0, 12.0, np.nan], 'file': 'f', 'sheet': 's', '_row': [1, 2, 3], '_point_id': ['a', 'b', 'c']})
    elpro = pd.DataFrame({'well': '101', 'date': DAYS[[0, 2]], 'q': [1.5, 2.5], 'kind': 'withdrawal',
                          't': [15.0, 16.0], 'p': [50.0, 52.0], 'y': [30.0, 150.0]})
    return prod, elpro


def selection(prod, elpro_rows, **params):
    data = Data({PROD: prod, ELPRO: elpro_rows} if elpro_rows is not None else {PROD: prod})
    data.mapping = {'101': {'group': 'ГСП 4'}}
    data.settings = {}
    base = {'kind': 'withdrawal', 'periods': ['2025'], 'groups': ['ГСП 4'], 'wells': ['101'], 'direction': 'number', 'elpro': []}
    return Selection(data, {**base, **params}), data


def test_picked_extras_keeps_order_and_drops_unknown_and_repeats():
    assert picked_extras(['t', 'cru', 'cru', 'nope', 'p', 'hours']) == ['t', 'cru', 'p', 'hours'][:MAX_RIGHT_AXES]
    assert picked_extras(None) == []


def test_without_extras_chart_is_as_before():
    prod, elpro = frames()
    sel, _ = selection(prod, elpro)
    chart = curve_chart(sel, ['101'], 'date')
    assert chart.right_axes() == []
    assert [s.name for s in chart.series] == ['2025']


def test_each_extra_on_its_own_right_axis_with_gap_on_missing_elpro_day():
    prod, elpro = frames()
    sel, _ = selection(prod, elpro, elpro=['cru', 'p', 't'])
    chart = curve_chart(sel, ['101'], 'date')
    assert [name for name, _ in chart.right_axes()] == ['y2', 'y3', 'y4']
    cru, p, t = chart.series[1:4]
    assert [s.axis for s in (cru, p, t)] == ['y2', 'y3', 'y4']
    assert list(cru.y[[0, 2]]) == [30.0, 100.0]            # 150 обрезано до 100
    assert np.isnan(cru.y[1])                              # пропуск ЭЛПРО — разрыв, не ноль
    assert np.isnan(p.y[1]) and list(p.y[[0, 2]]) == [50.0, 52.0]


def test_hours_come_from_production_and_gap_where_empty():
    prod, elpro = frames()
    sel, _ = selection(prod, elpro, elpro=['hours'])
    chart = curve_chart(sel, ['101'], 'date')
    hours = chart.series[1]
    assert hours.axis == 'y2'
    assert list(hours.y[:2]) == [24.0, 12.0] and np.isnan(hours.y[2])


def test_cumulative_mode_uses_the_same_x_as_the_curve():
    prod, elpro = frames()
    sel, _ = selection(prod, elpro, elpro=['cru'])
    chart = curve_chart(sel, ['101'], 'cumulative')
    cru = chart.series[1]
    assert np.allclose(cru.x, chart.series[0].x)


def test_export_makes_one_figure_per_well_and_kind_with_chosen_rows():
    prod, elpro = frames()
    _, data = selection(prod, elpro)
    options = {'modules': ['production'], 'style': {}, 'production': {
        'wells': ['101'], 'groups': ['ГСП 4'], 'direction': 'number', 'elpro': ['cru', 'hours'],
        'periods': {'withdrawal': ['2025'], 'injection': []}}}
    plan = with_elpro(SimpleNamespace(jobs=[]), data, options)
    assert len(plan.jobs) == 1
    assert plan.jobs[0].module == 'production'


def test_without_elpro_database_selected_rows_are_dropped_not_empty_axes():
    prod, _ = frames()
    sel, data = selection(prod, None, elpro=['cru', 'hours'])
    chart = curve_chart(sel, ['101'], 'date')
    assert chart.right_axes() == []                        # БД ЭЛПРО не загружена — пустых правых осей нет
    assert [s.name for s in chart.series] == ['2025']
    assert with_elpro(SimpleNamespace(jobs=[]), data, {'modules': ['production'], 'style': {}, 'production': {
        'wells': ['101'], 'groups': ['ГСП 4'], 'direction': 'number', 'elpro': ['cru'],
        'periods': {'withdrawal': ['2025'], 'injection': []}}}).jobs == []
