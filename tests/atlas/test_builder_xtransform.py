"""Конструктор: преобразование и сводка по оси X (накопленный отбор по объекту, по группе, по скважине), подсказка при пустой связи."""
import pytest

from atlas.contract import Data, ParamError
from atlas.modules import builder
from tests.atlas.test_builder import frames, text

Y = {'dataset': 'operations', 'y': 'p_wellhead', 'x_dataset': 'production', 'x': 'q', 'view': 'points'}


@pytest.fixture()
def data():
    d = Data(frames())
    d.mapping = {'1': {'group': 'ГСП-1'}, '2': {'group': 'ГСП 1'}}
    return d


def run(data, **row):
    return builder.build(data, {'series': [{**Y, **row}]})


def points(result):
    return sorted((round(float(x), 4), float(y)) for s in result.charts[0].series for x, y in zip(s.x, s.y))


def test_cumulative_object(data):
    r = run(data, key='date', x_scope='object', x_transform={'op': 'cumsum'})
    name = r.charts[0].x.label
    assert 'накопленное' in name and 'по объекту' in name and 'млн м³' in name
    # объект по датам: 150, 60, 70, 280 тыс. м³/сут → накопленное 0,15 / 0,21 / 0,28 / 0,56 млн м³
    assert points(r) == [(0.15, 40.0), (0.21, 41.0), (0.21, 43.0), (0.28, 50.0)]


def test_cumulative_object_default_key_falls_back_to_date(data):
    r = run(data, x_scope='object', x_transform={'op': 'cumsum'})          # ключ по умолчанию «скважина + дата»
    assert len(points(r)) == 4 and 'warning' not in {n.level for n in r.notes if 'нет ни одной' in n.text}


def test_cumulative_group_merges_name_variants(data):
    r = run(data, key='well_date', x_scope='group', x_transform={'op': 'cumsum'})
    assert points(r) == [(0.15, 40.0), (0.21, 41.0), (0.21, 43.0), (0.28, 50.0)]      # «ГСП-1» и «ГСП 1» — одна группа


def test_cumulative_per_well(data):
    r = run(data, key='well_date', x_transform={'op': 'cumsum'})
    # скв. 1: 0,1 → 0,1 (простой) → пропуск −999,25 → 0,3; скв. 2: 0,05 / 0,11 / 0,18
    assert points(r) == [(0.1, 40.0), (0.1, 41.0), (0.1, 43.0), (0.18, 50.0)]


def test_object_scope_ignores_row_wells_but_keeps_period(data):
    r = run(data, key='date', wells=['2'], x_scope='object', x_transform={'op': 'cumsum'})
    assert points(r) == [(0.28, 50.0)]                       # Y только скв. 2, а X — накопленное по всему объекту
    r = run(data, key='date', x_scope='object', x_transform={'op': 'cumsum'}, date_from='2025-01-02')
    assert points(r)[0] == (0.06, 41.0)                     # накопленное идёт с начала периода ряда


def test_scope_without_transform_sums_object(data):
    r = run(data, key='date', x_scope='object')
    assert points(r) == [(60.0, 41.0), (60.0, 43.0), (70.0, 50.0), (150.0, 40.0)]


def test_pressure_x_is_averaged_not_summed(data):
    row = {'dataset': 'production', 'y': 'q', 'x_dataset': 'operations', 'x': 'p_wellhead', 'key': 'date', 'x_scope': 'object', 'view': 'points'}
    r = builder.build(data, {'series': [row]})
    assert 'среднее' in text(r)


def test_multiply_transform_changes_unit(data):
    r = run(data, key='date', x_scope='object', x_transform={'op': 'div', 'value': 1000})
    assert points(r)[0][0] == 0.06


def test_bad_values_are_param_errors(data):
    with pytest.raises(ParamError):
        run(data, x_scope='всё')
    with pytest.raises(ParamError):
        run(data, x_transform={'op': 'month'})


def test_mixed_kinds_warning(data):
    data[builder.K.PRODUCTION].loc[0, 'kind'] = 'injection'
    assert 'отбор и закачка вместе' in text(run(data, key='date', x_scope='object'))


def test_no_pairs_suggests_working_key(data):
    r = run(data, key='nearest', days=0, x_dataset='gdi', x='p_res')        # ГДИ 3 января, замеры давления в другие дни, ±0 дней
    assert 'нет ни одной пары' in text(r) and 'скважина' in text(r)
