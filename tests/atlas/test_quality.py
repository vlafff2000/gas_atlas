"""Проверка данных: находки на подложенных ошибках, чистое демо без находок, раздел, отчёт при импорте."""
import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas.engine.core import config
from atlas.engine.core.config import DEFAULT_SETTINGS
from atlas.engine.core.demo import well_demo_frames
from atlas.engine.core.storage import Store
from atlas import quality
from atlas.api import create_app
from atlas.projects import Projects
from tests.atlas.test_import import import6, upload


def broken():
    frames = well_demo_frames()
    p = frames['production'].copy().reset_index(drop=True)
    p.loc[10, 'q'] *= 10          # скачок
    p.loc[20, 'q'] = 0            # ноль посреди отбора
    p.loc[30, 'q'] = -5           # отрицательный расход
    p = pd.concat([p, p.iloc[[40]]], ignore_index=True)       # повтор даты
    g = frames['gdi'].copy()
    g.loc[2, 'p_bh'] = g.loc[2, 'p_res'] + 5                  # Рзаб выше Рпл
    g.loc[3, 'dp2'] *= 2                                      # ΔP² не сходится с давлениями
    r = frames['response'].copy()
    r.loc[5, 'pressure'] *= 2                                 # скачок давления
    return {**frames, 'production': p, 'gdi': g, 'response': r}


def checks(found):
    return set(zip(found.dataset, found.check))


def test_demo_data_has_no_findings():
    assert quality.scan(well_demo_frames()).empty


def test_each_check_finds_its_planted_error():
    found = quality.scan(broken())
    assert {('production', 'Скачок дебита'), ('production', 'Ноль посреди отбора'), ('production', 'Отрицательный расход'),
            ('production', 'Повтор даты'), ('gdi', 'Рзаб не ниже Рпл'), ('gdi', 'ΔP² не сходится с давлениями'),
            ('response', 'Скачок давления')} <= checks(found)
    assert found.level.isin(['ошибка', 'внимание']).all() and list(found.columns) == quality.COLUMNS
    assert found[found.level.eq('ошибка')].index.max() < found[found.level.eq('внимание')].index.min()   # ошибки сверху
    assert found[found.check.eq('Скачок дебита')].value.iloc[0] == 'в 10,0 раза выше'
    assert quality.summary(found)['count'].sum() == len(found)


def test_jump_limit_and_pressure_in_other_units():
    frames = broken()
    assert ('production', 'Скачок дебита') not in checks(quality.scan(frames, quality.Limits(jump=50)))
    mpa = well_demo_frames()
    mpa['gdi'] = mpa['gdi'].assign(p_res=mpa['gdi'].p_res / 10)
    units = quality.scan({'gdi': mpa['gdi']})
    assert ('gdi', 'Единицы давления') in checks(units)
    assert 'МПа' in units[units.check.eq('Единицы давления')].details.iloc[0]


def test_limit_per_check_and_empty_frames():
    big = pd.DataFrame({'well': '1', 'date': pd.date_range('2020-01-01', periods=quality.LIMIT + 50), 'q': -1.0})
    assert len(quality.scan({'production': big})) == quality.LIMIT
    assert quality.scan({'production': big.iloc[0:0], 'gdi': pd.DataFrame(), 'response': pd.DataFrame()}).empty


@pytest.fixture()
def project(tmp_path):
    store = Store(tmp_path)
    pid = store.create('Объект', demo=True)
    store.commit(pid, broken(), settings={**DEFAULT_SETTINGS}, action='Загрузка')
    return TestClient(create_app(Projects(tmp_path))), pid, store


def test_module_lists_findings_and_excludes_points(project):
    client, pid, store = project
    body = client.post('/api/modules/quality/run', json={'project': pid, 'params': {}}).json()
    ids = [t['id'] for t in body['tables']]
    assert 'summary' in ids and 'found_production' in ids and 'found_gdi' in ids
    table = next(t for t in body['tables'] if t['id'] == 'found_gdi')
    assert table['action']['kind'] == 'exclude' and table['action']['dataset'] == 'gdi' and len(table['action']['ids']) == len(table['rows'][0])
    only_errors = client.post('/api/modules/quality/run', json={'project': pid, 'params': {'level': 'error'}}).json()
    assert all(v == 'ошибка' for t in only_errors['tables'] if t['id'].startswith('found_')
               for v in t['rows'][[c['key'] for c in t['columns']].index('level')])
    # исключение подтверждённой точки — тем же запросом, что и на графиках
    point = table['action']['ids'][0]
    r = client.post(f'/api/projects/{pid}/exclusions', json={'dataset': 'gdi', 'add': [point], 'reason': 'Проверка данных'})
    assert r.status_code == 200, r.text
    again = client.post('/api/modules/quality/run', json={'project': pid, 'params': {}}).json()
    shown = next(t for t in again['tables'] if t['id'] == 'found_gdi')
    assert any(shown['action']['checked'])


def test_module_without_findings_and_without_data(tmp_path):
    store = Store(tmp_path)
    pid = store.create('Чистый', demo=True)
    client = TestClient(create_app(Projects(tmp_path)))
    empty = client.post('/api/modules/quality/run', json={'project': pid, 'params': {}}).json()
    assert 'нет данных' in empty['notes'][0]['text']
    store.commit(pid, well_demo_frames(), settings={**DEFAULT_SETTINGS}, action='Загрузка')
    clean = client.post('/api/modules/quality/run', json={'project': pid, 'params': {}}).json()
    assert 'не найдено' in clean['notes'][0]['text'] and not clean['tables']


def test_import_check_reports_quality_before_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path)
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = projects.store.create('Объект')
    token = upload(client, '01_long_format.xlsx')
    r = client.post(f'/api/projects/{pid}/import/check', json={'view': 'simple', 'mode': 'auto', 'files': [{'token': token}]})
    assert r.status_code == 200, r.text
    report = r.json()['quality']
    assert set(report) == {'errors', 'attention', 'by_check', 'table'} and report['errors'] >= 0
    if report['table']:
        assert report['table']['columns'][0]['label'] == 'Набор'
        done = client.post(f'/api/projects/{pid}/import/table', json={'pending': r.json()['id'], 'table': 'quality', 'format': 'csv'})
        assert done.status_code == 200 and done.content


def test_pending_report_json_for_broken_frames():
    from atlas.imports import Imports
    frames = {k: v for k, v in broken().items() if k in quality.CHECKS}
    pending = {'frames': frames}
    report = Imports._quality_json(pending)
    assert report['errors'] > 0 and report['attention'] > 0 and report['table']['count'] == report['errors'] + report['attention']
    assert [c['label'] for c in report['table']['columns']][:4] == ['Набор', 'Скважина', 'Дата', 'Проверка']
    assert pending['quality'] is not None                       # посчитано один раз: скачивание таблицы берёт то же
    assert Imports._quality_json({'frames': well_demo_frames()})['table'] is None


def test_lazy_values_match_full_column_format():
    """Подписи считаются только для найденных строк (ускорение), но совпадают с форматом по всей колонке."""
    found = quality.scan(broken())
    p = broken()['production'].reset_index(drop=True)
    neg = found[found.check.eq('Отрицательный расход')]
    assert list(neg.value) == list(quality._fmt(p.q[p.q.lt(0)]))
    assert neg.value.iloc[0] == '-5,0'
    assert found[found.check.eq('Скачок дебита')].value.str.startswith('в ').all()
