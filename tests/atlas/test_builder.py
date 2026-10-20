"""Конструктор графиков: каталог полей, связь X↔Y по ключу, пропуски и нули, пустая выборка, оси Y1–Y5."""
import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.api import create_app
from atlas.contract import Data, ParamError
from atlas.domain import DatasetKind as K
from atlas.modules import builder
from atlas.projects import Projects
from tests.atlas._wells_data import make_project

D = pd.to_datetime


def frames():
    days = D(['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-04'])
    production = pd.DataFrame({
        'well': ['1'] * 4 + ['2'] * 4, 'date': list(days) * 2, 'kind': 'withdrawal',
        'q': [100_000.0, 0.0, -999.25, 200_000.0, 50_000.0, 60_000.0, 70_000.0, 80_000.0],     # м³/сут: ноль — простой
        'group': 'ГСП-1', '_point_id': [f'p{i}' for i in range(8)]})
    operations = pd.DataFrame({
        'well': ['1', '1', '1', '2'], 'date': D(['2025-01-01', '2025-01-02', '2025-01-02', '2025-01-03']),
        'p_wellhead': [40.0, 41.0, 43.0, 50.0], 'comment': ['a', 'b', 'c', 'd'], 'p_line': np.nan,
        'kind': 'withdrawal'})
    gas_db = pd.DataFrame({'date': days, 'kind': 'withdrawal', 'gas': [1000.0, 1100.0, 1200.0, 1300.0]})
    construction = pd.DataFrame({'well': ['1', '2'], 'date': D(['2020-01-01', '2020-01-01']), 'element': 'колонна',
                                 'bottom_m': [1500.0, 1600.0]})
    gdi = pd.DataFrame({'well': ['1', '1'], 'date': D(['2025-01-03', '2025-02-01']), 'p_res': [70.0, 69.0],
                        'q': [300.0, 310.0], 'dp2': [10.0, 11.0], 'method': 'изохронный'})
    return {K.PRODUCTION: production, K.OPERATIONS: operations, K.GAS_DB: gas_db, K.CONSTRUCTION: construction, K.GDI: gdi}


@pytest.fixture()
def data():
    return Data(frames())


def build(data, *rows, **labels):
    return builder.build(data, {'series': list(rows), **labels})


def text(result):
    return ' '.join(n.text for n in result.notes)


def test_catalog_only_present_numeric_and_date_fields(data):
    cat = builder.catalog(data)
    fields = {f['id']: f for c in cat['categories'] for f in c['fields']}
    assert 'production.q' in fields and fields['production.q']['unit'] == 'тыс. м³/сут'
    assert fields['operations.p_wellhead']['category'] == 'pressure'
    assert 'operations.p_line' not in fields            # колонка без значений
    assert 'operations.comment' not in fields and 'gdi.method' not in fields      # текст
    assert not any(f.endswith('.date') or f.endswith('._point_id') for f in fields)
    labels = [c['label'] for c in cat['categories']]
    assert labels.index('Производительность скважин') < labels.index('Давления') < labels.index('ГДИ')
    sets = {d['id']: d for d in cat['datasets']}
    assert sets['production']['entities'] == ['1', '2'] and sets['production']['kinds'][0]['label'] == 'Отбор'
    assert sets['gas_db']['entity'] == '' and fields['gas_db.gas']['category'] == 'object'
    assert next(f for f in sets['production']['fields'] if f['field'] == 'date')['kind'] == 'date'
    assert {k['value'] for k in cat['keys']} == {'well_date', 'date', 'well', 'nearest'}


def test_zero_kept_nodata_is_gap(data):
    r = build(data, {'dataset': 'production', 'y': 'q', 'wells': ['1']})
    s = r.charts[0].series[0]
    assert r.charts[0].x.scale == 'time' and r.charts[0].y.unit == 'тыс. м³/сут'
    assert list(s.y[:2]) == [100.0, 0.0] and np.isnan(s.y[2]) and s.y[3] == 200.0     # ноль остался, −999,25 — разрыв линии
    assert list(s.ids) == ['p0', 'p1', 'p2', 'p3'] and s.dataset == K.PRODUCTION
    pts = build(data, {'dataset': 'production', 'y': 'q', 'wells': ['1'], 'view': 'points'}).charts[0].series[0]
    assert list(pts.y) == [100.0, 0.0, 200.0] and pts.kind == 'points'          # у точек пропуск не рисуется


def test_one_series_per_well_and_all_wells_by_default(data):
    r = build(data, {'dataset': 'production', 'y': 'q'})
    assert [s.name for s in r.charts[0].series] == ['Суточный расход газа · скв. 1', 'Суточный расход газа · скв. 2']
    assert r.charts[0].series[1].facets == {'Ряд': '1. Суточный расход газа', 'Скважина': '№ 2'}


def test_key_well_date(data):
    r = build(data, {'dataset': 'operations', 'y': 'p_wellhead', 'x_dataset': 'production', 'x': 'q'})
    s = {x.name: x for x in r.charts[0].series}
    one = s['Руст · скв. 1']
    # 01.01: Q 100; 02.01: Q 0 (простой — точка с нулём), два замера Руст на эту дату — обе точки
    assert list(one.x) == [0.0, 0.0, 100.0] and sorted(one.y[:2]) == [41.0, 43.0] and one.y[2] == 40.0
    assert list(s['Руст · скв. 2'].x) == [70.0]
    assert r.charts[0].x.scale == 'value' and r.charts[0].x.label == 'Суточный расход газа, тыс. м³/сут'
    assert 'скважина + дата' in text(r) and 'найдено пар: 4' in text(r)


def test_key_date_object_dataset(data):
    r = build(data, {'dataset': 'production', 'y': 'q', 'wells': ['2'], 'x_dataset': 'gas_db', 'x': 'gas', 'key': 'date'})
    assert list(r.charts[0].series[0].x) == [1000.0, 1100.0, 1200.0, 1300.0]
    # «скважина + дата» с набором без скважин — только по дате, с пояснением
    r2 = build(data, {'dataset': 'production', 'y': 'q', 'wells': ['2'], 'x_dataset': 'gas_db', 'x': 'gas'})
    assert list(r2.charts[0].series[0].x) == [1000.0, 1100.0, 1200.0, 1300.0] and 'только по дате' in text(r2)


def test_key_date_averages_duplicates(data):
    r = build(data, {'dataset': 'gas_db', 'y': 'gas', 'x_dataset': 'operations', 'x': 'p_wellhead', 'key': 'date'})
    s = r.charts[0].series[0]
    assert sorted(zip(s.x, s.y)) == [(40.0, 1000.0), (42.0, 1100.0), (50.0, 1200.0)]     # 02.01: (41 + 43) / 2
    assert 'среднее' in text(r) and 'найдено пар: 3' in text(r)


def test_key_well(data):
    r = build(data, {'dataset': 'production', 'y': 'q', 'x_dataset': 'construction', 'x': 'bottom_m', 'key': 'well',
                     'view': 'points'})
    s = {x.name: x for x in r.charts[0].series}
    assert set(s['Суточный расход газа · скв. 1'].x) == {1500.0} and len(s['Суточный расход газа · скв. 2'].x) == 4
    # без общей колонки скважин ключ «скважина» невозможен — заметка, не ошибка
    bad = build(data, {'dataset': 'gas_db', 'y': 'gas', 'x_dataset': 'construction', 'x': 'bottom_m', 'key': 'well'})
    assert not bad.charts and 'ключ «дата»' in text(bad)


def test_key_nearest_date_tolerance(data):
    row = {'dataset': 'gdi', 'y': 'p_res', 'x_dataset': 'production', 'x': 'q', 'key': 'nearest', 'view': 'points'}
    r = build(data, {**row, 'days': 3})
    s = r.charts[0].series[0]
    # 03.01 — Q −999,25 (пропуск) не берётся, ближайший замер — сутки простоя 02.01 (ноль); 01.02 — дальше 3 дней, пары нет
    assert list(s.x) == [0.0] and list(s.y) == [70.0] and 'найдено пар: 1' in text(r)
    wide = build(data, {**row, 'days': 30}).charts[0].series[0]
    assert sorted(wide.x) == [0.0, 200.0]          # 01.02 → 04.01 (28 дней)


def test_empty_selection_is_note(data):
    r = build(data, {'dataset': 'production', 'y': 'q', 'wells': ['1'], 'date_from': '2030-01-01'})
    assert not r.charts and 'нет точек' in text(r)
    assert 'Добавьте ряд' in text(builder.build(data, {'series': []}))
    missing = build(data, {'dataset': 'water', 'y': 'water_rate'})
    assert not missing.charts and 'нет набора' in text(missing)


def test_period_and_kind_filter(data):
    r = build(data, {'dataset': 'production', 'y': 'q', 'wells': ['2'], 'date_from': '2025-01-02', 'date_to': '2025-01-03',
                     'kind': 'withdrawal'})
    s = r.charts[0].series[0]
    assert list(s.y) == [60.0, 70.0] and '(отбор)' in s.name
    assert not build(data, {'dataset': 'production', 'y': 'q', 'kind': 'injection'}).charts


def test_axes_y1_to_y5_and_manual_labels(data):
    rows = [{'dataset': 'production', 'y': 'q', 'wells': ['1'], 'axis': a} for a in ('y', 'y2', 'y3', 'y4', 'y5')]
    r = build(data, *rows, title='Мой график', x_label='Время', axes={'y3': 'Третья ось'})
    c = r.charts[0]
    assert c.axis_names() == ['y', 'y2', 'y3', 'y4', 'y5'] and [s.axis for s in c.series] == ['y', 'y2', 'y3', 'y4', 'y5']
    assert c.title == 'Мой график' and c.x.label == 'Время'
    assert c.y3.label == 'Третья ось' and c.y3.unit == '' and c.y2.label == 'Суточный расход газа'
    # Y3 без Y2: правые шкалы идут подряд, ряд встаёт на вторую шкалу, подпись Y3 едет с ним
    gap = build(data, rows[0], {**rows[2]}, axes={'y3': 'Третья'}).charts[0]
    assert gap.axis_names() == ['y', 'y2'] and gap.series[1].axis == 'y2' and gap.y2.label == 'Третья'
    # ряд только на Y2: левая шкала не остаётся пустой
    alone = build(data, rows[1])
    assert alone.charts[0].axis_names() == ['y'] and alone.charts[0].series[0].axis == 'y' and 'Y1 пуста' in text(alone)


def test_mixed_x_kinds_skip_second(data):
    r = build(data, {'dataset': 'production', 'y': 'q', 'wells': ['1']},
              {'dataset': 'operations', 'y': 'p_wellhead', 'x_dataset': 'production', 'x': 'q'})
    assert len(r.charts[0].series) == 1 and 'ось X одна' in text(r)


def test_bad_layout_is_param_error(data):
    with pytest.raises(ParamError, match='Ряд 1'):
        build(data, {'dataset': 'production', 'y': 'q', 'axis': 'y9'})
    with pytest.raises(ParamError, match='набор'):
        build(data, {'dataset': 'nope', 'y': 'q'})


def test_api_catalog_run_and_saved_state(tmp_path):
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    cat = client.post('/api/modules/builder/catalog', json={'project': pid})
    assert cat.status_code == 200, cat.text
    assert cat.json()['categories']
    well = next(d for d in cat.json()['datasets'] if d['id'] == 'production')['entities'][0]
    layout = {'series': [{'dataset': 'production', 'y': 'q', 'wells': [well], 'kind': 'withdrawal'},
                         {'dataset': 'operations', 'y': 'p_wellhead', 'wells': [well], 'axis': 'y2'}]}
    r = client.post('/api/modules/builder/run', json={'project': pid, 'params': {'layout': layout}})
    assert r.status_code == 200, r.text
    chart = r.json()['charts'][0]
    assert chart['y2']['unit'] == 'кгс/см²' and {s['axis'] for s in chart['series']} == {'y', 'y2'}
    assert client.post('/api/modules/builder/run', json={'project': pid, 'params': {'layout': 'текст'}}).status_code == 400
    svg = client.post('/api/modules/builder/export', json={'project': pid, 'params': {'layout': layout}, 'target': 'chart',
                                                            'id': 'builder', 'format': 'svg'})
    assert svg.status_code == 200, svg.text
    saved = client.post(f'/api/projects/{pid}/state/builder', json={'params': {'layout': layout}})
    assert saved.status_code == 200, saved.text
    assert client.get(f'/api/projects/{pid}/state/builder').json()['panel']['layout'] == layout
    assert client.post('/api/modules/gdi/catalog', json={'project': pid}).status_code == 404


def test_line_breaks_on_long_gap_not_on_zero():
    days = list(D(['2025-01-01', '2025-01-02', '2025-01-03', '2025-03-01', '2025-03-02']))
    prod = pd.DataFrame({'well': '1', 'date': days, 'kind': 'withdrawal', 'q': [1000.0, 0.0, 1000.0, 2000.0, 2000.0],
                         '_point_id': list('abcde')})
    s = build(Data({K.PRODUCTION: prod}), {'dataset': 'production', 'y': 'q'}).charts[0].series[0]
    assert len(s.x) == 6 and np.isnan(s.y[3]) and s.y[1] == 0.0       # разрыв между 03.01 и 01.03, ноль — точка
    assert s.ids[3] == '' and s.ids[1] == 'b'
