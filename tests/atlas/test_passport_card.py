"""Карточка паспорта: конструкция у забоя, сезоны с максимальным расходом, ГДИ за всё время, КРС и PDF."""
import re

import pandas as pd
import pytest
from starlette.testclient import TestClient

from _wells_data import make_project
from atlas import passport_card as pc
from atlas.api import create_app
from atlas.projects import Projects

WELL = '31'


@pytest.fixture(scope='module')
def env(tmp_path_factory):
    projects = Projects(tmp_path_factory.mktemp('card'))
    return TestClient(create_app(projects)), make_project(projects), projects


@pytest.fixture()
def krs_loaded(env):
    from atlas.imports import Imports
    _, pid, projects = env
    Imports(projects).krs_load(pid, 'КРС_для_Атласа.xlsx', krs_book(), 'new')


def test_classify_keeps_only_bottomhole_elements():
    assert pc.classify('Эксплуатационная колонна') == 'casing'
    assert pc.classify('НКТ 73 мм') == 'tubing'
    assert pc.classify('Интервал расширки') == 'reaming'
    assert pc.classify('Фильтр') == 'filter' and pc.classify('Интервал перфорации') == 'perf'
    assert pc.classify('Кондуктор') is None and pc.classify('Потайная колонна') is None
    assert pc.classify('Потайная колонна-фильтр') == 'filter'


def frame(rows):
    return pd.DataFrame(rows, columns=['element', 'top_m', 'bottom_m', 'diameter_mm', 'inner_diameter_mm'])


def test_schematic_skips_conductor_and_reports_sand_plug():
    cons = frame([('Кондуктор', 0, 300, 245, 226), ('Эксплуатационная колонна', 0, 1010, 168, 150), ('НКТ', 0, 940, 73, 62),
                  ('Фильтр', 960, 1005, None, None), ('Расширка', 970, 1000, 300, None)])
    sch = pc.schematic(cons, 990.0)
    assert {i['kind'] for i in sch['items']} == {'casing', 'tubing', 'filter', 'reaming'}
    assert sch['skipped'] == ['Кондуктор']
    assert sch['covered_m'] == 15.0 and any('перекрыто' in n for n in sch['notes'])
    assert sch['top'] > 0 and sch['top'] < 940 < sch['bottom']             # окно у забоя, не вся скважина
    assert {s['name'] for s in sch['shapes']} >= {'casing', 'tubing', 'filter', 'reaming', 'fill', 'bottom'}
    assert all(l['at'] >= l['y'] for l in sch['labels'])


def test_schematic_without_construction_is_a_note():
    sch = pc.schematic(frame([]), None)
    assert sch['items'] == [] and 'конструкции' in sch['notes'][0]


def krs_book():
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        pd.DataFrame({'Скважина': [31, 31, 45], 'Год': [2019, 2023, 2022],
                      'Тип ремонта': ['Замена фильтра', 'Колтюбинг без СКО', 'Замена фильтра']}).to_excel(xw, sheet_name='Ремонты', index=False)
        pd.DataFrame({'Скважина': [31], 'Приоритет итог': [2], 'Причина': ['песок']}).to_excel(xw, sheet_name='Приоритет', index=False)
    return buf.getvalue()


def test_krs_book_is_recognized_and_imported_through_import(env):
    from atlas.engine.core import krs_import
    from atlas.imports import Imports, special_kind
    client, pid, projects = env
    parts, warn = krs_import.read('КРС_для_Атласа.xlsx', krs_book())
    assert parts['krs_works'].well.tolist() == ['31', '31', '45'] and parts['krs_priority'].priority.tolist() == [2.0] and not warn
    tables = {n: pd.read_excel(__import__('io').BytesIO(krs_book()), sheet_name=n, header=None) for n in ('Ремонты', 'Приоритет')}
    assert special_kind(tables, 'КРС_для_Атласа.xlsx')[0] == 'krs'
    done = Imports(projects).krs_load(pid, 'КРС_для_Атласа.xlsx', krs_book(), 'new')
    assert 'проведённые КР: строк 3' in done['message']
    again = Imports(projects).krs_load(pid, 'КРС_для_Атласа.xlsx', krs_book(), 'new')      # повтор заменяет, не дублирует
    assert projects.manifest(pid)['tables']['krs_works'] == 3 and 'строк 3' in again['message']


def test_checklist_lists_krs_kinds(env, krs_loaded):
    from atlas import import_checklist
    _, pid, projects = env
    items = {i['key']: i for i in import_checklist.build(projects.manifest(pid))}
    assert items['krs_works']['count'] == 3 and items['krs_priority']['count'] == 1
    assert 'Паспорт скважины' in items['krs_works']['used'] and items['krs_works']['columns'][0] == 'Скважина'


def test_card_endpoint_has_seasons_gdi_and_krs(env, krs_loaded):
    client, pid, _ = env
    r = client.get(f'/api/projects/{pid}/passport/card', params={'well': WELL})
    assert r.status_code == 200, r.text
    card = r.json()
    assert [w['year'] for w in card['krs']['works']] == [2019, 2023] and card['krs']['priority']['value'] == 2
    out = [s for s in card['seasons'] if s['kind'] == 'withdrawal']
    assert out and all(s['max_rate'] >= s['mean_rate'] > 0 and s['days'] > 0 for s in out)
    assert card['gdi'] and card['gdi'][0]['date'].count('.') == 2
    assert {k['label'] for k in card['kpi']} >= {'Максимальный суточный отбор', 'ГДИ за всё время', 'Проведено КР'}
    assert card['schematic']['items'] and card['schematic']['bottom_m'] == 985.0
    assert client.get(f'/api/projects/{pid}/passport/card', params={'well': 'нет'}).status_code == 400
    sections = client.get(f'/api/projects/{pid}/passport').json()['sections']
    assert not [x for x in sections if x['value'].startswith('krs')]


def test_card_without_krs_tells_where_to_import(tmp_path):
    projects = Projects(tmp_path)
    client, pid = TestClient(create_app(projects)), make_project(projects)
    card = client.get(f'/api/projects/{pid}/passport/card', params={'well': WELL}).json()
    assert card['krs']['works'] == [] and any('«Импорт»' in n for n in card['notes'])
    assert next(k for k in card['kpi'] if k['label'] == 'Проведено КР')['value'] is None


def test_pdf_starts_with_card_page(env):
    client, pid, _ = env
    with_card = client.post(f'/api/projects/{pid}/passport/pdf', json={'well': WELL, 'sections': ['gdi'], 'card': True})
    without = client.post(f'/api/projects/{pid}/passport/pdf', json={'well': WELL, 'sections': ['gdi']})
    assert with_card.status_code == 200 and without.status_code == 200, with_card.text
    pages = lambda b: len(re.findall(rb'/Type\s*/Page[^s]', b))
    assert pages(with_card.content) == pages(without.content) + 1
    only = client.post(f'/api/projects/{pid}/passport/pdf', json={'well': WELL, 'sections': [], 'card': True})
    assert only.status_code == 200 and pages(only.content) >= 1
