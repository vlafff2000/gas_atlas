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
    assert_labels_apart(sch)


def assert_labels_apart(sch):
    """Подписи справа: расстояние между соседними не меньше шага и все внутри окна схемы (в координатах после сжатия разрывов)."""
    ats = sorted(l['at'] for l in sch['labels'])
    gap = (sch['bottom'] - sch['top']) * .045
    assert all(b - a >= gap - 1e-6 for a, b in zip(ats, ats[1:]))
    assert all(sch['top'] <= a <= sch['bottom'] for a in ats)


def test_labels_do_not_overlap_after_break_compression():
    # длинный пустой участок сжимается; раньше подписи разводили до сжатия, и после него они слипались
    cons = frame([('Эксплуатационная колонна', 0, 1510, 168, 150), ('НКТ', 0, 1500, 73, 62), ('Пакер', 1100, 1102, None, None),
                  ('Фильтр', 1490, 1508, None, None), ('Интервал перфорации', 1495, 1505, None, None)])
    sch = pc.schematic(cons, 1503.0)
    assert sch.get('breaks') and len(sch['labels']) >= 5
    assert_labels_apart(sch)


def test_overlapping_intervals_are_merged_for_drawing():
    cons = frame([('Эксплуатационная колонна', 0, 1010, 168, 150), ('Эксплуатационная колонна', 0, 1010, 168, 150),
                  ('Интервал перфорации', 960, 980, None, None), ('Интервал перфорации', 975, 1000, None, None),
                  ('Интервал перфорации', 1000.3, 1005, None, None)])
    sch = pc.schematic(cons, None)
    assert [i['kind'] for i in sch['items']].count('casing') == 1
    perf = [i for i in sch['items'] if i['kind'] == 'perf']
    assert len(perf) == 1 and (perf[0]['top'], perf[0]['bottom']) == (960, 1005)
    assert sum(1 for l in sch['labels'] if l['text'].startswith('Перфорация')) == 1
    assert any('слито строк — 3' in n for n in sch['notes'])


def test_gis_packs_are_drawn_separately_with_own_colour_and_label():
    cons = frame([('Эксплуатационная колонна', 0, 1010, 168, 150), ('Интервал перфорации', 960, 1000, None, None),
                  ('Пласт, пачка «верхняя»', 950, 980, None, None), ('Пласт, пачка «нижняя»', 975, 1005, None, None)])
    sch = pc.schematic(cons, None)
    pay = [i for i in sch['items'] if i['kind'] == 'pay']
    assert len(pay) == 2                                  # соседние пачки с наложением не слиты
    texts = [l['text'] for l in sch['labels'] if 'ачка' in l['text']]
    assert any(t.startswith('Пачка «верхняя»') for t in texts) and any(t.startswith('Пачка «нижняя»') for t in texts)
    fills = {s_['fill'] for s_ in sch['shapes'] if s_.get('name') == 'pay'}
    assert len(fills) == 2


def codes(sch):
    return {c['code'] for c in sch['checks']}


def test_artificial_bottom_conflicts_are_flagged_with_reason():
    cons = frame([('Эксплуатационная колонна', 0, 1010, 168, 150), ('Интервал перфорации', 960, 1000, None, None),
                  ('НКТ', 0, 990, 73, 62), ('Искусственный забой', 995, 995, None, None)])
    sch = pc.schematic(cons, 1003)
    assert {'below_artificial', 'current_vs_artificial'} <= codes(sch)
    deeper = [c for c in sch['checks'] if c['code'] == 'current_vs_artificial'][0]
    assert deeper['level'] == 'warning' and 'глубже искусственного' in deeper['text']
    ok = pc.schematic(frame([('Эксплуатационная колонна', 0, 1010, 168, 150), ('Искусственный забой', 1005, 1005, None, None)]), 1005)
    assert 'current_vs_artificial' not in codes(ok)


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
    assert card['krs']['works'] == [] and '«Импорт»' in card['krs']['note'] and not any('«Импорт»' in n or 'конструкции' in n for n in card['notes'])
    assert next(k for k in card['kpi'] if k['label'] == 'Проведено КР')['value'] is None


def test_pdf_starts_with_card_page(env):
    client, pid, _ = env
    with_card = client.post(f'/api/projects/{pid}/passport/pdf', json={'well': WELL, 'sections': ['gdi'], 'card': True})
    without = client.post(f'/api/projects/{pid}/passport/pdf', json={'well': WELL, 'sections': ['gdi']})
    assert with_card.status_code == 200 and without.status_code == 200, with_card.text
    pages = lambda b: len(re.findall(rb'/Type\s*/Page[^s]', b))
    assert pages(with_card.content) == pages(without.content) + 2        # страница карточки и страница графиков
    only = client.post(f'/api/projects/{pid}/passport/pdf', json={'well': WELL, 'sections': [], 'card': True})
    assert only.status_code == 200 and pages(only.content) >= 1


def test_card_blocks_use_shared_contract_and_export(env):
    """Графики и таблицы паспорта — в общем контракте (рисует общее ядро) и выгружаются общим экспортом."""
    client, pid, _ = env
    card = client.get(f'/api/projects/{pid}/passport/card', params={'well': WELL}).json()
    assert {c['id'] for c in card['charts']} >= {'passport-seasons', 'passport-daily'}
    assert {t['id'] for t in card['tables']} >= {'passport-seasons', 'passport-gdi'}
    seasons = next(t for t in card['tables'] if t['id'] == 'passport-seasons')
    assert [c['key'] for c in seasons['columns']][:3] == ['kind', 'period', 'volume']
    png = client.post(f'/api/projects/{pid}/passport/export', json={'well': WELL, 'target': 'chart', 'id': 'passport-seasons', 'format': 'png'})
    assert png.status_code == 200 and png.content[:4] == b'\x89PNG'
    xlsx = client.post(f'/api/projects/{pid}/passport/export', json={'well': WELL, 'target': 'table', 'id': 'passport-gdi', 'format': 'xlsx'})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b'PK'
    assert client.post(f'/api/projects/{pid}/passport/export', json={'well': WELL, 'target': 'chart', 'id': 'нет'}).status_code == 400


def test_perforation_is_sawtooth_and_bridge_is_recognized():
    assert pc.classify('Цементный мост') == 'bridge'
    cons = frame([('Эксплуатационная колонна', 0, 1010, 168, 150), ('Интервал перфорации', 960, 1000, None, None),
                  ('Цементный мост', 1000, 1008, None, None)])
    sch = pc.schematic(cons, None)
    saw = [s for s in sch['shapes'] if s['t'] == 'poly' and s['name'] == 'perf']
    assert len(saw) == 2 and all(len(s['pts']) >= 7 for s in saw)            # пила с каждой стороны колонны
    assert {p[0] for p in saw[1]['pts']} == {1.12, 1.6}
    assert any(s.get('pattern') == 'cement' for s in sch['shapes'])


def test_season_choice_limits_card_and_exports(env):
    client, pid, _ = env
    full = client.get(f'/api/projects/{pid}/passport/card', params={'well': WELL}).json()
    pick = full['season_options'][:2]
    import json
    part = client.get(f'/api/projects/{pid}/passport/card', params={'well': WELL, 'seasons': json.dumps(pick)}).json()
    assert part['season_options'] == full['season_options']                          # список вариантов не сужается
    assert [f"{'Отбор' if s['kind'] == 'withdrawal' else 'Закачка'} {s['period']}" for s in part['seasons']] == pick
    assert part['tables'][0]['count'] == 2
    assert part['kpi'][0]['value'] != full['kpi'][0]['value'] or len(full['seasons']) == 2
    pdf = client.post(f'/api/projects/{pid}/passport/pdf', json={'well': WELL, 'sections': [], 'card': True, 'seasons': pick})
    assert pdf.status_code == 200 and pdf.content[:4] == b'%PDF'


def _row(kind, period, start):
    return {'kind': kind, 'period': period, 'start': start}


def test_seasons_chart_groups_withdrawal_with_following_injection():
    """Пара — отбор и следующая за ним закачка (отбор 2025-2026 + закачка 2026): один столбцовый блок, а не две отдельные категории."""
    from atlas import passport_blocks as pb
    rows = pc.assign_pairs([
        {**_row('injection', '2025', '2025-05-10'), 'volume': 3.0, 'days': 100, 'max_rate': 30.0},
        {**_row('withdrawal', '2025-2026', '2025-11-20'), 'volume': 5.0, 'days': 150, 'max_rate': 50.0},
        {**_row('injection', '2026', '2026-05-12'), 'volume': 4.0, 'days': 90, 'max_rate': 40.0}])
    dated = [r | {'end': pd.Timestamp(r['start']).strftime('%d.%m.%Y')} for r in rows]
    chart = pb.seasons_chart(pc.chronological(dated))
    assert chart.x.categories == ['2024/2025', '2025/2026']                    # закачка 2025 одна в своём цикле; отбор 2025-2026 + закачка 2026
    by = {s.name: dict(zip(s.x, s.y)) for s in chart.series}
    assert by['Отбор'] == {'2025/2026': 5.0} and by['Закачка'] == {'2024/2025': 3.0, '2025/2026': 4.0}


def test_manual_pairs_override_auto(env):
    from atlas import passport_blocks as pb
    rows = pc.assign_pairs([{**_row('withdrawal', '2025-2026', '2025-11-20'), 'volume': 5.0},
                            {**_row('injection', '2026', '2026-05-12'), 'volume': 4.0}], {'Закачка 2026': 2030})
    assert [r['cycle'] for r in rows] == [2025, 2030]


def test_construction_checks_are_hints_with_reason():
    cons = frame([('Эксплуатационная колонна', 0, 950, 168, 150), ('НКТ', 0, 990, 73, 62), ('Фильтр', 960, 1005, None, None),
                  ('Фильтр', 980, 1000, None, None)])
    sch = pc.schematic(cons, 900.0)
    codes = {c['code'] for c in sch['checks']}
    assert {'casing_above_work', 'tubing_below_casing', 'bottom_above_filter', 'overlap'} <= codes
    assert 'tubing_below_work' not in codes
    assert all(c['text'] and c['level'] in ('warning', 'info') for c in sch['checks'])
    assert len(sch['items']) == 3                                       # на схеме наложенные фильтры слиты в один, а проверка видит обе строки


def test_construction_checks_reaming_downgrades_and_inverted():
    ok = pc.schematic(frame([('Эксплуатационная колонна', 0, 950, 168, 150), ('Фильтр', 960, 1005, None, None),
                             ('Интервал расширки', 940, 1000, 300, None)]), None)
    assert [c['level'] for c in ok['checks'] if c['code'] == 'casing_above_work'] == ['info']
    bad = pc.schematic(frame([('Эксплуатационная колонна', 0, 1010, 168, 150), ('НКТ', 0, 1100, 73, 62), ('Фильтр', 1005, 960, None, None)]), None)
    assert 'inverted' in {c['code'] for c in bad['checks']} and 'tubing_below_casing' in {c['code'] for c in bad['checks']}
    clean = pc.schematic(frame([('Эксплуатационная колонна', 0, 1010, 168, 150), ('НКТ', 0, 940, 73, 62), ('Фильтр', 960, 1005, None, None)]), 1000.0)
    assert clean['checks'] == []
