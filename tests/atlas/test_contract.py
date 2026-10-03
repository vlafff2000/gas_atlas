import json
import math

import numpy as np
import pandas as pd
import pytest

from atlas import registry
from atlas.contract import Axis, Chart, Option, Param, ParamError, Result, Series, Table, plain
from atlas.domain import DatasetKind


def test_param_coercion():
    assert Param('t', 'Порог', 'number', default=.95).coerce(None) == .95
    assert Param('t', 'Порог', 'number', minimum=0, maximum=1).coerce('0.9') == .9
    with pytest.raises(ParamError, match='больше'):
        Param('t', 'Порог', 'number', maximum=1).coerce(2)
    with pytest.raises(ParamError, match='целое'):
        Param('n', 'N', 'integer').coerce(1.5)
    assert Param('b', 'Флаг', 'boolean').coerce('false') is False
    choice = Param('c', 'Выбор', 'choice', options=(Option(1, 'Один'), Option(2, 'Два')))
    assert choice.coerce(2) == 2
    with pytest.raises(ParamError):
        choice.coerce(3)
    assert Param('w', 'Скважины', 'multi').coerce([31, '45']) == ['31', '45']


def test_spec_rejects_unknown_params():
    spec = registry.get('gdi').spec
    with pytest.raises(ParamError, match='Неизвестные'):
        spec.coerce({'nope': 1})
    assert spec.coerce({})['threshold'] == .95


def test_every_registered_spec_serializes():
    specs = [m.spec.to_json() for m in registry.modules().values()]
    assert {'gdi'} <= {s['id'] for s in specs}
    json.dumps(specs, ensure_ascii=False)
    for s in specs:
        # Страницы проекта («Обзор», «Исключенные точки», «История фильтра») наборов данных не требуют.
        assert s['needs'] or s['group'] == 'Проект'
        assert all(k in {d.value for d in DatasetKind} for k in s['needs'])


def test_result_json_is_strict():
    frame = pd.DataFrame({'a': [1.0, np.nan, np.inf], 'd': pd.to_datetime(['2024-01-02', None, '2024-01-03 10:30'], format='ISO8601')})
    result = Result(tables=[Table('t', 'T', frame)],
                    charts=[Chart('c', 'C', Axis('x'), Axis('y'), [Series('s', np.array([1., np.nan]), [2, 3])])])
    text = json.dumps(result.to_json(), allow_nan=False)
    data = json.loads(text)
    assert data['tables'][0]['rows'][0] == [1.0, None, None]
    assert data['tables'][0]['rows'][1] == ['2024-01-02', None, '2024-01-03T10:30:00']
    assert data['tables'][0]['columns'][1]['kind'] == 'date'
    assert data['charts'][0]['series'][0]['x'] == [1.0, None]
    assert plain(np.int64(3)) == 3 and plain(pd.NaT) is None and plain(math.nan) is None


def test_datetime_arrays_become_iso_dates_not_nanoseconds():
    dates = pd.to_datetime(['2024-01-02', None, '2024-01-04'])
    chart = Chart('c', 'C', Axis('x', scale='time'), Axis('y'),
                  [Series('a', dates.to_numpy(), [1, 2, 3], 'line'), Series('b', pd.Series(dates), [1, 2, 3], 'line'),
                   Series('c', dates, [1, 2, 3], 'line')])
    for s in Result(charts=[chart]).to_json()['charts'][0]['series']:
        assert s['x'] == ['2024-01-02', None, '2024-01-04']
