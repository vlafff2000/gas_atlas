"""Самопроверка на данных объекта (atlas.selfcheck): отчёт строится, ошибки данных видны, исходные файлы не меняются."""
import json

import pandas as pd
import pytest

from atlas import selfcheck


def production(path, extra=None):
    rows = []
    for d in pd.date_range('2025-01-01', periods=12):
        for w, g in (('11', 'ГСП 1'), ('12', 'ГСП 1'), ('13', 'ГСП 2')):
            zero = w == '12' and d.day in (4, 5)
            rows.append({'Скважина': w, 'Дата': d, 'Часовой расход газа': 0 if zero else 100.0, 'Время работы': 24,
                         'Суточный расход газа': 0 if zero else 2400.0, 'Тип данных': 'отбор', 'Источник': g,
                         'Сезон': '2024-2025'})
    rows.append({'Скважина': '54/80', 'Дата': pd.Timestamp('2025-01-01'), 'Часовой расход газа': 10.0,
                 'Время работы': 24, 'Суточный расход газа': 240.0, 'Тип данных': 'отбор', 'Источник': 'ГСП 2',
                 'Сезон': '2024-2025'})
    rows.append({'Скважина': '11', 'Дата': pd.Timestamp('2025-01-01'), 'Часовой расход газа': 0.0, 'Время работы': 0,
                 'Суточный расход газа': 0.0, 'Тип данных': 'отбор', 'Источник': 'ГСП 1', 'Сезон': '2024-2025'})
    pd.DataFrame(rows + (extra or [])).to_excel(path, index=False, sheet_name='Отборы')


def gdi(path):
    rows = []
    for w, a, b in (('11', 0.1, 0.01), ('12', 0.2, 0.02)):
        for q in (60.0, 90.0, 120.0, 150.0):
            pl, dp2 = 90.0, (a * q + b * q * q)
            pz = (pl ** 2 - dp2) ** 0.5
            rows.append({'№скв': w, 'дата': pd.Timestamp('2025-01-10'), 'ГСП': 1, 'Qгаза тыс.м3/сут': q,
                         'Рпл, кгс/см2': pl, 'Рзаб, кгс/см2': round(pz, 3)})
    pd.DataFrame(rows).to_excel(path, index=False, sheet_name='ГДИ')


@pytest.fixture()
def folder(tmp_path):
    d = tmp_path / 'obj'
    d.mkdir()
    production(d / 'otbor.xlsx')
    gdi(d / 'gdi.xlsx')
    return d


def by_id(rep, cid, scope=None):
    return [c for c in rep.checks if c['id'] == cid and (scope is None or c['scope'] == scope)]


def test_report_files_and_statuses(folder, tmp_path):
    out = tmp_path / 'out'
    rep = selfcheck.run([str(folder)], out, quick=False, say=lambda s: None)
    assert (out / 'selfcheck_report.json').exists() and (out / 'selfcheck_report.md').exists()
    data = json.loads((out / 'selfcheck_report.json').read_text(encoding='utf-8'))
    assert {f['file'] for f in data['files']} == {'otbor.xlsx', 'gdi.xlsx'}
    assert not rep.counts().get('error'), [c for c in rep.checks if c['status'] == 'error']
    assert not rep.counts().get('fail'), [c for c in rep.checks if c['status'] == 'fail']
    assert by_id(rep, 'prod.fidelity', 'otbor.xlsx')[0]['status'] == 'ok'
    assert by_id(rep, 'prod.combined', 'otbor.xlsx')[0]['status'] == 'ok'
    assert by_id(rep, 'prod.open_zero', 'otbor.xlsx')[0]['data']['days'] == 2
    assert by_id(rep, 'proj.idempotent')[0]['status'] == 'ok'
    assert by_id(rep, 'gdi.group', 'gdi.xlsx')[0]['status'] == 'ok'
    assert 'Самопроверка' in (out / 'selfcheck_report.md').read_text(encoding='utf-8')


def test_quick_mode_skips_independent_checks(folder, tmp_path):
    rep = selfcheck.run([str(folder)], tmp_path / 'q', quick=True, say=lambda s: None)
    assert not by_id(rep, 'prod.fidelity')
    assert by_id(rep, 'prod.basic', 'otbor.xlsx')[0]['status'] == 'ok'


def test_source_files_are_not_modified(folder, tmp_path):
    before = {p.name: (p.stat().st_size, p.read_bytes()) for p in folder.iterdir()}
    selfcheck.run([str(folder)], tmp_path / 'o', quick=True, say=lambda s: None)
    assert {p.name: (p.stat().st_size, p.read_bytes()) for p in folder.iterdir()} == before


def test_unrecognised_file_is_warning_not_crash(folder, tmp_path):
    pd.DataFrame({'Фамилия': ['А'], 'Город': ['Б']}).to_excel(folder / 'junk.xlsx', index=False)
    rep = selfcheck.run([str(folder)], tmp_path / 'o', quick=True, say=lambda s: None)
    c = by_id(rep, 'import.recognised', 'junk.xlsx')[0]
    assert c['status'] == 'warn'
    assert not rep.counts().get('error')


def test_empty_folder(tmp_path):
    (tmp_path / 'e').mkdir()
    rep = selfcheck.run([str(tmp_path / 'e')], tmp_path / 'o', say=lambda s: None)
    assert rep.counts() == {'fail': 1}


def test_sheet_with_service_sheets_passes(folder, tmp_path):
    path = folder / 'obs.xlsx'
    with pd.ExcelWriter(path) as w:
        pd.DataFrame({'Скважина': ['1', '2'], 'Дата': pd.to_datetime(['2025-01-01'] * 2), 'Горизонт': ['Щ', 'Щ'],
                      'Уровень жидкости': [100.0, 120.0]}).to_excel(w, sheet_name='Данные', index=False)
        pd.DataFrame({'a': [1]}).to_excel(w, sheet_name='Статистика', index=False)
    rep = selfcheck.run([str(folder)], tmp_path / 'o', quick=True, say=lambda s: None)
    assert not by_id(rep, 'import.blocked', 'obs.xlsx')
    assert by_id(rep, 'import.ok', 'obs.xlsx')


def test_main_returns_nonzero_on_failure(tmp_path):
    (tmp_path / 'e').mkdir()
    assert selfcheck.main([str(tmp_path / 'e'), '--out', str(tmp_path / 'o')]) == 1
