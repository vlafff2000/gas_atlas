"""Word «ГИС и ГВК»: страница на скважину, таблица изменения ГВК по пачкам и выгрузка через API.
Данные — литеральные, в тесте; реальных данных компании в репозитории нет."""
import io
import zipfile

import pandas as pd
import pytest
from starlette.testclient import TestClient

from atlas import gis_report
from atlas.api import create_app
from atlas.projects import Projects


def _packs():
    return pd.DataFrame({
        'well': ['115', '115', '115', '113'],
        'date': pd.to_datetime(['2024-10-01', '2025-03-01', '2025-10-01', '2024-10-01']),
        'season': ['осень', 'весна', 'осень', 'осень'],
        'pack': ['верхняя', 'верхняя', 'верхняя', 'нижняя'],
        'gvk_abs_m': [-1000.0, -1001.0, -1003.0, -990.0],
        'h_eff_m': [1.5, 1.2, 1.4, 3.0],
        'kg_avg': [0.3, 0.25, 0.28, 0.5],
    })


def test_change_rows_give_delta_and_rate_per_pack():
    rows = gis_report.change_rows(_packs()[_packs().well == '115'])
    assert rows == [('pack', 'верхняя', '', ['3', '10.2024', '-1000.00', '10.2025', '-1003.00', '-3.00', '-3.00'])]


def test_build_docx_has_one_page_and_figure_per_well():
    items = [{'well': '115', 'frame': _packs()[_packs().well == '115']}, {'well': '113', 'frame': _packs()[_packs().well == '113']}]
    blob = gis_report.build_docx(items, start=3)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        document = z.read('word/document.xml').decode('utf-8')
        media = [n for n in z.namelist() if n.startswith('word/media/')]
    assert len(media) == 2
    assert 'Рисунок 3 — Скважина №115' in document and 'Рисунок 4 — Скважина №113' in document
    assert document.count('pageBreakBefore') == 1               # вторая страница — с разрывом, первая — без


@pytest.fixture()
def client(tmp_path):
    projects = Projects(tmp_path / 'storage')
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects/demo').json()['id']
    return client, pid, projects


def test_export_endpoint_writes_word_for_selected_wells(client):
    api, pid, projects = client
    projects.store.commit(pid, frames={'gis_packs': _packs()}, action='Тест: база ГИС')
    r = api.post(f'/api/projects/{pid}/export/gis', json={'form': {'gis_wells': ['115'], 'gis_start': 1, 'gis_dpi': 150}})
    assert r.status_code == 200, r.text
    assert r.json()['planned'] == 1 and r.json()['completed'] == 1


def test_export_without_gis_data_is_a_russian_error(client):
    api, pid, _ = client
    r = api.post(f'/api/projects/{pid}/export/gis', json={'form': {}})
    assert r.status_code == 400 and 'Базы ГИС' in r.text
