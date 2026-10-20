"""«Исправленная БД» вкладки: выгрузка с исключениями, структура листов и обратная загрузка в импорт."""
import io
from urllib.parse import unquote

import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas import corrected_db
from atlas.api import create_app
from atlas.domain import DatasetKind
from atlas.engine.core import config
from atlas.engine.core.loader import load_file
from atlas.projects import Projects


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path / 'storage')
    projects = Projects(tmp_path / 'storage')
    pid = projects.create_demo()
    gdi = projects.data(pid).raw[DatasetKind.GDI]['_point_id'].iloc[0]
    response = projects.data(pid).raw[DatasetKind.RESPONSE]['_point_id'].iloc[0]
    production = projects.data(pid).raw[DatasetKind.PRODUCTION]['_point_id'].iloc[0]
    projects.change_exclusions(pid, DatasetKind.GDI, add=[gdi], reason='тест')
    projects.change_exclusions(pid, DatasetKind.RESPONSE, add=[f'{response}:level'], reason='тест')
    projects.change_exclusions(pid, DatasetKind.PRODUCTION, add=[production], reason='тест')
    return TestClient(create_app(projects)), pid, tmp_path


def test_gdi_export_drops_excluded_study_and_reimports(project):
    client, pid, tmp_path = project
    reply = client.get(f'/api/projects/{pid}/corrected-db', params={'module': 'gdi'})
    assert reply.status_code == 200
    assert reply.headers['content-type'].startswith('application/vnd.openxmlformats')
    assert 'исправленная_БД.xlsx' in unquote(reply.headers['content-disposition'])
    book = pd.read_excel(io.BytesIO(reply.content), sheet_name=None)
    assert list(book) == ['ГДИ']
    assert len(book['ГДИ']) == 119                      # 120 в проекте, одна точка исключена
    assert {'Скважина', 'Дата', 'Q', 'Рпл', 'Рзаб', 'Рпл2рз2', 'a', 'b', 'Метод'} <= set(book['ГДИ'].columns)
    path = tmp_path / 'gdi.xlsx'
    path.write_bytes(reply.content)
    loaded = load_file(str(path))
    assert loaded.counts['gdi'] == 119                  # файл загружается обратно в Атлас без потерь


def test_response_export_blanks_excluded_metric_and_keeps_rows(project):
    client, pid, _ = project
    reply = client.get(f'/api/projects/{pid}/corrected-db', params={'module': 'response'})
    frame = pd.read_excel(io.BytesIO(reply.content), sheet_name=0)
    assert len(frame) == 352                            # строки на месте, исключён только уровень
    assert frame['Уровень'].isna().sum() >= 1
    assert frame['Рпл привед'].notna().any()


def test_production_export_drops_excluded_day(project):
    client, pid, _ = project
    frame = pd.read_excel(io.BytesIO(client.get(f'/api/projects/{pid}/corrected-db',
                                                params={'module': 'production'}).content), sheet_name=0)
    assert len(frame) == 7907
    assert frame['Q'].notna().all()


def test_unknown_module_and_missing_project(project):
    client, pid, _ = project
    assert client.get(f'/api/projects/{pid}/corrected-db', params={'module': 'nope'}).status_code == 404
    assert client.get(f'/api/projects/{pid}/corrected-db').status_code == 400
    assert client.get('/api/projects/нет/corrected-db', params={'module': 'gdi'}).status_code == 404


def test_build_keeps_empty_dataset_headers():
    frame = pd.DataFrame({'_point_id': pd.Series(dtype=str), 'well': pd.Series(dtype=str),
                          'date': pd.Series(dtype='datetime64[ns]'), 'q': pd.Series(dtype=float), 'kind': pd.Series(dtype=str)})
    book = pd.read_excel(io.BytesIO(corrected_db.workbook({DatasetKind.PRODUCTION: corrected_db.dataset_frame(frame, DatasetKind.PRODUCTION, {})})),
                         sheet_name=None)
    assert list(book['Отбор и закачка'].columns) == ['Скважина', 'Дата', 'Q', 'Тип']
