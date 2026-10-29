"""Сохранение выгрузок через проводник: каждый формат из программы уходит на /api/fs/save, файл записан и открывается."""
import io
import sys
import zipfile
from urllib.parse import unquote

import pandas as pd
import pytest
from starlette.testclient import TestClient

import atlas.api_projects as api_projects
from atlas.api import create_app
from atlas.projects import Projects

sys.path.insert(0, 'tests/atlas')

HEAD = {'X-PXG': '1'}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('PXG_HOME', str(tmp_path / 'cfg'))
    monkeypatch.setattr(api_projects, 'LOG_DIR', tmp_path / 'logs')
    projects = Projects(tmp_path / 'storage')
    client = TestClient(create_app(projects))
    return client, client.post('/api/projects/demo').json()['id'], projects, tmp_path


def _name(response):
    disposition = response.headers['content-disposition']
    return unquote(disposition.split("filename*=UTF-8''")[1]) if "filename*=UTF-8''" in disposition else disposition.split('filename="')[1].rstrip('"')


def _check_opens(path):
    """Файл читается своей программой: картинка — Pillow, Excel — openpyxl, Word и ZIP — как архив, PDF/SVG/CSV — по началу."""
    raw = path.read_bytes()
    assert raw, path
    ext = path.suffix.lower()
    if ext == '.png':
        from PIL import Image
        Image.open(io.BytesIO(raw)).load()
    elif ext == '.xlsx':
        import openpyxl
        assert openpyxl.load_workbook(io.BytesIO(raw)).sheetnames
    elif ext in ('.zip', '.docx'):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            assert z.testzip() is None and z.namelist()
            if ext == '.docx':
                assert 'word/document.xml' in z.namelist()
    elif ext == '.pdf':
        assert raw.startswith(b'%PDF') and b'%%EOF' in raw[-1024:]
    elif ext == '.svg':
        assert b'<svg' in raw[:2000]
    elif ext == '.csv':
        assert raw.decode('utf-8-sig').strip()
    else:
        raise AssertionError(f'неизвестный формат {ext}')


def _save(client, folder, name, content):
    r = client.post('/api/fs/save', params={'path': str(folder / name)}, content=content, headers=HEAD)
    assert r.status_code == 200, r.text
    path = folder / name
    assert path.read_bytes() == content
    _check_opens(path)
    return path


def test_every_chart_and_table_format_is_saved_and_opens(env):
    client, pid, _, tmp = env
    out = tmp / 'выгрузки'
    out.mkdir()
    params = {'wells': ['31', '70']}
    base = {'project': pid, 'params': params}
    got = {}
    for fmt in ('png', 'svg', 'pdf', 'xlsx', 'csv'):
        r = client.post('/api/modules/gdi/export', json={**base, 'target': 'chart', 'id': 'gdi-31', 'format': fmt, 'dpi': 150})
        assert r.status_code == 200, (fmt, r.text)
        got[f'график.{fmt}'] = r.content
    r = client.post('/api/modules/gdi/export', json={**base, 'target': 'tables'})
    assert r.status_code == 200, r.text
    got['таблицы.xlsx'] = r.content
    r = client.post('/api/modules/gdi/export', json={**base, 'target': 'tables', 'id': 'studies', 'format': 'csv'})
    assert r.status_code == 200, r.text
    got['таблица.csv'] = r.content
    r = client.post('/api/modules/gdi/export', json={**base, 'target': 'charts', 'layout': 'zip'})
    assert r.status_code == 200, r.text
    got['графики.zip'] = r.content
    r = client.post('/api/modules/gdi/export', json={**base, 'target': 'charts', 'layout': 'sheet', 'cols': 2})
    assert r.status_code == 200, r.text
    got['лист.png'] = r.content
    # «Экспорт → Любой график»
    found = client.post(f'/api/projects/{pid}/export/any/charts', json={'module': 'gdi', 'params': params}).json()['charts'][0]
    for fmt in ('png', 'svg', 'pdf', 'xlsx', 'csv'):
        r = client.post(f'/api/projects/{pid}/export/any/file', json={'module': 'gdi', 'params': params, 'chart': found['id'], 'settings': {'format': fmt}})
        assert r.status_code == 200, (fmt, r.text)
        got[f'любой.{fmt}'] = r.content
    assert len(got) == 14
    for name, content in got.items():
        _save(client, out, name, content)
    assert {p.suffix for p in out.iterdir()} == {'.png', '.svg', '.pdf', '.xlsx', '.csv', '.zip'}


def test_word_report_from_project_exports_is_saved_and_opens(env):
    client, pid, projects, tmp = env
    packs = pd.DataFrame({
        'well': ['115', '115'], 'date': pd.to_datetime(['2024-10-01', '2025-10-01']), 'season': ['осень', 'осень'],
        'pack': ['верхняя', 'верхняя'], 'gvk_abs_m': [-1000.0, -1003.0], 'h_eff_m': [1.5, 1.4], 'kg_avg': [0.3, 0.28]})
    projects.store.commit(pid, frames={'gis_packs': packs}, action='Тест: база ГИС')
    r = client.post(f'/api/projects/{pid}/export/gis', json={'form': {'gis_wells': ['115'], 'gis_start': 1, 'gis_dpi': 150}})
    assert r.status_code == 200, r.text
    files = [f['name'] for f in client.get(f'/api/projects/{pid}/exports').json()]
    assert any(n.endswith('.docx') for n in files), files
    for name in files:
        d = client.get(f'/api/projects/{pid}/exports/{name}')
        assert d.status_code == 200
        _save(client, tmp, _name(d), d.content)


def test_fs_save_is_protected_and_remembers_folder(env):
    client, _, _, tmp = env
    (tmp / 'a').mkdir()
    # чужая страница не может записать файл: без заголовка X-PXG запрос отклоняется
    assert client.post('/api/fs/save', params={'path': str(tmp / 'a' / 'x.png')}, content=b'1').status_code == 403
    assert not (tmp / 'a' / 'x.png').exists()
    _save(client, tmp / 'a', 'x.csv', b'a;b\n1;2\n')
    last = client.get('/api/fs/last').json()
    assert last['save_dir'] == str(tmp / 'a')
    # существующий файл без подтверждения не затирается
    r = client.post('/api/fs/save', params={'path': str(tmp / 'a' / 'x.csv')}, content=b'new', headers=HEAD)
    assert r.status_code == 409 and (tmp / 'a' / 'x.csv').read_bytes() == b'a;b\n1;2\n'
