"""Блок «Оценка состояния» паспорта: сбор улик, ручное решение главнее, сохранение через API."""
import pandas as pd

from atlas import passport_assess as pa
from atlas import well_assess as wa


def test_bottom_source_distinguishes_gis_report_and_geo_service():
    assert pa.bottom_source({'method': 'Шаблонирование геологической службой'}) == 'geo_template'
    assert pa.bottom_source({'method': 'шаблон', 'comment': 'отчёт ГИС'}) == 'gis_report'
    assert pa.bottom_source({'method': 'ГИС'}) == 'gis_report' and pa.bottom_source({'method': 'ручной замер'}) == 'other'
    assert pa.bottom_source(None) == 'unknown' and pa.bottom_source({'method': float('nan')}) == 'unknown'


def test_bottom_source_from_templating_db_comment():
    """Строки «Комментарий» листа «Замеры забоя» БД шаблонирования (`pxg_core.templating_db.bottom_frame`): «вид; источник данных»."""
    src = lambda text: pa.bottom_source({'method': 'шаблон', 'comment': text})
    assert src('доход шаблона; БД ГИС из отчётов') == 'gis_report' and src('остановка прибора; Отчёт ГИС') == 'gis_report'
    assert src('шаблонирование (Excel); Excel') == 'geo_template'
    assert pa.bottom_source({'method': 'текущий забой', 'comment': 'текущий забой; Конструкции из Word'}) == 'other'
    assert pa.bottom_source({'method': 'решение инженера', 'comment': 'решение инженера; Решение инженера'}) == 'other'


def test_collect_sand_old_gdi_and_manual_override_wins():
    krs = {'works': [], 'priority': {'value': 1.0, 'reason': 'песок в 3 ревизиях подряд'}}
    gdi = [{'date': '01.01.2018', 'reliable': True}]
    ev = pa.collect(bottom_m=None, bottom_date=pd.NaT, bottom_row=None, filter_bottom_m=None, krs=krs, seasons=[], gdi=gdi, elpro=[], today='01.01.2026')
    assert [e.mechanism for e in ev] == ['sand', 'gdi_old'] and ev[0].level == 'strong' and '3 ревизиях' in ev[0].reason
    rows = pa.rows(ev, {'sand': {'level': 'none', 'note': 'ревизия 2026 чистая'}, 'throttle': {'level': 'weak', 'note': ''}})
    by = {r['mechanism']: r for r in rows}
    assert by['sand']['level'] == 'none' and by['sand']['auto_level'] == 'strong' and by['sand']['manual'] and by['sand']['note'] == 'ревизия 2026 чистая'
    assert by['throttle']['manual'] and by['gdi_old']['manual'] is False
    assert pa.rows(ev, {'sand': {'level': 'bad'}})[0]['manual'] is False


def test_throttle_from_last_elpro_season_attention_only():
    elpro = [{'period': '2025-2026', 'verdict': 'внимание', 'reason': 'КРУ ≥ 90 % в 40 % суток'}]
    ev = pa.collect(bottom_m=None, bottom_date=None, bottom_row=None, filter_bottom_m=None, krs={'works': []}, seasons=[], gdi=[{'date': '01.01.2025', 'reliable': True}], elpro=elpro, today='01.01.2026')
    assert [e.mechanism for e in ev] == ['throttle'] and ev[0].level == 'weak'


def test_api_saves_and_clears_manual_decision():
    import sys
    from pathlib import Path
    from starlette.testclient import TestClient
    sys.path.insert(0, str(Path(__file__).parent))
    from _wells_data import make_project
    import tempfile
    from atlas.api import create_app
    from atlas.projects import Projects
    projects = Projects(tempfile.mkdtemp())
    pid = make_project(projects)
    client = TestClient(create_app(projects))
    ok = client.post(f'/api/projects/{pid}/passport/assess', json={'well': '31', 'mechanism': 'gdi_old', 'level': 'strong', 'note': 'проверено'})
    assert ok.status_code == 200
    card = client.get(f'/api/projects/{pid}/passport/card', params={'well': '31'}).json()
    row = next(r for r in card['assess'] if r['mechanism'] == 'gdi_old')
    assert row['manual'] and row['level'] == 'strong' and any(t['id'] == 'passport-assess' for t in card['tables'])
    client.post(f'/api/projects/{pid}/passport/assess', json={'well': '31', 'mechanism': 'gdi_old', 'level': None})
    card = client.get(f'/api/projects/{pid}/passport/card', params={'well': '31'}).json()
    assert not any(r['mechanism'] == 'gdi_old' and r['manual'] for r in card['assess'])
    assert client.post(f'/api/projects/{pid}/passport/assess', json={'well': '31', 'mechanism': 'x', 'level': 'weak'}).status_code == 400


def test_operations_table_override_beats_auto_hint_and_defaults_restore():
    from atlas import passport_assess as pa
    from atlas import well_assess as wa
    ev = [wa.Evidence('sand', 'strong', 'причина', '', 1.0, 'авто-подсказка')]
    assert pa.rows(ev, None)[0]['recommendation'] == 'авто-подсказка'
    assert pa.rows(ev, None, {'sand': {'strong': 'Своя операция'}})[0]['recommendation'] == 'Своя операция'
    assert pa.rows(ev, None, {'sand': {'weak': 'для слабой'}})[0]['recommendation'] == 'авто-подсказка'      # правка другого уровня не мешает
    assert pa.operations_of({'well_operations': {'sand': {'weak': 'X'}}})['sand'] == {'strong': pa.DEFAULT_OPERATIONS['sand']['strong'], 'weak': 'X'}


def test_sand_priority_restored_on_date_from_seasons_and_resets():
    from atlas import passport_assess as pa
    sand = '2021-2022, 2022-2023, 2024-2025'
    assert pa.sand_priority_at(sand, [], 2022) is None                              # ревизия сезона 2021-2022 известна только с 2022 года, на 1.01.2022 ещё нет
    assert pa.sand_priority_at(sand, [], 2023)['value'] == 3.0                      # 2021-2022 → 1 ревизия → 3
    assert pa.sand_priority_at(sand, [], 2024)['value'] == 2.0                      # + 2022-2023 → 2
    assert pa.sand_priority_at(sand, [], 2026)['value'] == 1.0                      # + 2024-2025 → 3 ревизии → 1 (срочно)
    reset = [{'year': 2023, 'type': 'КР с заменой фильтра'}]
    assert pa.sand_priority_at(sand, reset, 2026)['value'] == 3.0                   # после замены фильтра в 2023 остаётся одна ревизия (2024-2025)
    wash = [{'year': 2023, 'type': 'Колтюбинг без СКО'}]
    assert pa.sand_priority_at(sand, wash, 2026)['value'] == 1.0                    # промывка счёт не сбрасывает
    assert pa.sand_priority_at(None, [], 2026) is None
