"""ГГХ: разбор листа «Общий», импорт через API, график и таблица модуля, страницы Word по референсу отчёта."""
import io
import zipfile

import pandas as pd
import pytest
from starlette.testclient import TestClient

from app.core import config, ggh_import as ggh
from atlas.api import create_app
from atlas.modules._ggh import caption, gas_axis, horizon_genitive, rows_for
from atlas.projects import Projects
from tools.make_ggh_sample import HEADER, make_book, make_rows


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'STORAGE', tmp_path)
    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = client.post('/api/projects', json={'name': 'ГГХ'}).json()['id']
    return client, pid, tmp_path


def book(tmp_path, **kw) -> bytes:
    path = tmp_path / 'ggh.xlsx'
    make_book(path, **kw)
    return path.read_bytes()


def load(client, pid, content):
    token = client.post('/api/import/files', params={'name': 'ГГХ.xlsx'}, content=content).json()['token']
    check = client.post(f'/api/projects/{pid}/import/ggh', json={'token': token})
    assert check.status_code == 200, check.text
    return check.json()


def test_normalize_handles_messy_rows():
    raw = pd.read_excel(io.BytesIO(open_book()), sheet_name='Общий', header=None)
    data, notes = ggh.normalize(raw)
    assert list(data.columns)[:3] == ['well', 'date', 'horizon']
    assert data.well.nunique() == 4 and data.well.is_unique is False
    assert data.gas.notna().sum() == data.shape[0]                    # «350,5» прочитано как число
    assert 350.5 in set(data.gas)
    text = ' '.join(n['Причина'] for n in notes)
    assert 'перелив' in text and 'повтор даты' in text and 'неиспользуемые' in text
    assert any(n['Уровень'] == 'Ошибка' and 'нет даты' in n['Причина'] for n in notes)
    assert not data.duplicated(['well', 'date']).any()
    assert '999' not in set(data.well)                               # строка без даты не загружена


def open_book() -> bytes:
    buf = io.BytesIO()
    make_book(buf)
    return buf.getvalue()


def test_header_with_latin_and_cyrillic_letters():
    cyr = ['№№ скв.', 'Дата отбора', 'Сумма УВ', 'Не', 'Н2', 'N2', 'O2', 'СО2']
    lat = ['№№ скв.', 'Дата отбора', 'Сумма УВ', 'He', 'H2', 'N2', 'O2', 'CO2']
    for names in (cyr, lat):
        raw = pd.DataFrame([names, ['5', '2020-01-01', 1, 2, 3, 4, 5, 6], ['5', '2021-01-01', 1, 2, 3, 4, 5, 6]])
        data, _ = ggh.normalize(raw)
        assert data.iloc[0][['hc', 'he', 'h2', 'n2', 'o2', 'co2']].tolist() == [1, 2, 3, 4, 5, 6]


def test_no_header_is_a_clear_error():
    with pytest.raises(ValueError, match='шапка'):
        ggh.normalize(pd.DataFrame([['a', 'b'], [1, 2]]))


def test_axis_and_caption_rules():
    assert gas_axis(pd.Series([590.0, 810.0, 5.0])) == (0.0, 810.0)      # кратно 10: как в референсе (810, шаг 81)
    assert gas_axis(pd.Series([785.0])) == (0.0, 790.0)
    assert gas_axis(pd.Series([3.2])) == (0.0, 10.0)
    assert gas_axis(pd.Series([0.0, 0.0])) == (0.0, 10.0)
    assert horizon_genitive('Ряжский') == 'ряжского'
    assert horizon_genitive('Окско-серпуховский') == 'окско-серпуховского'
    assert caption(55, '162', 'Ряжский') == 'Рисунок В.55 – Результаты ГГХИ по скважине № 162 ряжского горизонта'
    assert caption(1, '5', '') == 'Рисунок В.1 – Результаты ГГХИ по скважине № 5'


def test_merge_replaces_same_well_and_date():
    old, _ = ggh.normalize(pd.read_excel(io.BytesIO(open_book()), sheet_name='Общий', header=None))
    new = old.iloc[[0]].assign(hc=11.0)
    merged = ggh.merge(old, new)
    assert len(merged) == len(old) and merged[(merged.well == old.well[0]) & (merged.date == old.date[0])].hc.iloc[0] == 11.0
    assert len(ggh.merge(old, new, 'replace')) == 1


def test_import_module_and_export_through_api(env):
    client, pid, _ = env
    check = load(client, pid, open_book())
    assert check['sheet'] == 'Общий' and check['ready']['existing'] is None
    assert check['ready']['issues'] is not None
    r = client.post(f'/api/projects/{pid}/import/ggh/apply', json={'pending': check['ready']['id'], 'mode': 'merge'})
    assert r.status_code == 200, r.text
    # повторная загрузка: данные есть, предлагается выбор
    again = load(client, pid, open_book())
    assert again['ready']['existing']['wells'] == 4 and len(again['ready']['modes']) == 2

    run = client.post('/api/modules/ggh/run', json={'project': pid, 'params': {'wells': ['160', '167']}}).json()
    assert [c['id'] for c in run['charts']] == ['ggh-160', 'ggh-167']
    chart = run['charts'][0]
    assert chart['y']['maximum'] == 100 and chart['y']['minimum'] == 0 and chart['y2']['minimum'] == 0
    assert (chart['y']['maximum'] - 0) / chart['y']['step'] == (chart['y2']['maximum'] - 0) / chart['y2']['step'] == 10
    assert {s['name'] for s in chart['series']} >= {'Сумма УВ', 'He', 'Газонасыщенность'}
    assert [s['axis'] for s in chart['series'] if s['name'] == 'Газонасыщенность'] == ['y2']
    assert run['tables'][0]['columns'][0]['label'] == 'Параметр'

    out = client.post(f'/api/projects/{pid}/export/ggh', json={'form': {'ggh_wells': ['160', '167'], 'ggh_start': 55, 'ggh_dpi': 150}})
    assert out.status_code == 200, out.text
    name = out.json()['files'][0]
    docx = client.get(f'/api/projects/{pid}/exports/{name}').content
    z = zipfile.ZipFile(io.BytesIO(docx))
    xml = z.read('word/document.xml').decode('utf8')
    assert 'Рисунок В.55 – Результаты ГГХИ по скважине № 160 щигровского горизонта' in xml
    assert 'Рисунок В.56 – Результаты ГГХИ по скважине № 167 ' in xml
    assert xml.count('<w:pageBreakBefore/>') == 1 and xml.count('<w:tbl>') == 2 and xml.count('Times New Roman') > 10
    assert 'w:orient="landscape"' in xml and sum(n.startswith('word/media/') for n in z.namelist()) == 2
    assert z.read('word/media/ggh1.png')[:4] == b'\x89PNG'


def test_export_without_data_is_a_clear_error(env):
    client, pid, _ = env
    r = client.post(f'/api/projects/{pid}/export/ggh', json={'form': {}})
    assert r.status_code == 400 and 'ГГХ' in r.json()['error']


def test_rows_skip_empty_parameters():
    frame = make_rows(1, 3).rename(columns={})
    frame = pd.DataFrame({'well': ['1'] * 2, 'date': pd.to_datetime(['2020-01-01', '2021-01-01']), 'hc': [1.0, 2.0], 'gas': [100.0, None]})
    rows = rows_for(frame)
    assert [r[0] for r in rows] == ['hc', 'gas'] and rows[1][3] == [100.0, None]
