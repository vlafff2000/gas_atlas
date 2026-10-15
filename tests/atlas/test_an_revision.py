"""Авторский надзор: табл. 1.8 ревизии КРУ — расчёт на присланных файлах (история 2021–2025, ревизия 2025/26).

Нумерация: в скрипте-источнике (well_report.py, README) эта таблица названа 1.9; в отчёте АН — табл. 1.8.

Эталон — результат исходного скрипта well_report.py на тех же файлах (ГСП-1 — 12 скважин, ГСП-2 — 20 строк).
"""
from pathlib import Path

import pytest

from atlas.contract import Data, ParamError
from atlas.engine.modules import revision_report as rr
from atlas.modules.an_revision import RevisionModule

DATA = Path(__file__).parent / 'data'
HISTORY = DATA / 'revision_history_2021_2025.xlsx'
REVISION = DATA / 'revision_2025_26.docx'


@pytest.fixture(scope='module')
def dataset():
    history = rr.parse_history(HISTORY)
    revision, issues, source, hints = rr.parse_revision(REVISION)
    return rr.append_season(history, '2025/26', revision, issues, source)


def test_seasons_and_groups(dataset):
    assert dataset.seasons == ['2021/22', '2022/23', '2023/24', '2024/25', '2025/26']
    assert dataset.gsps == ['ГСП-1', 'ГСП-2', 'ГСП-3', 'ГСП-4', 'ГСП-5', 'ГСП-6', 'ГСП-7', 'ГСП-8', 'ГСП-9']


def test_revision_counts_match_reference(dataset):
    assert len(dataset.get('ГСП-1', '2025/26').unique) == 12
    assert len(dataset.get('ГСП-2', '2025/26').unique) == 20
    assert dataset.get('ГСП-6', '2025/26').known is False          # ГСП нет в ревизии → «нет данных»
    assert dataset.get('ГСП-7', '2025/26').known is False


def test_history_keeps_source_count_and_unique_analytics(dataset):
    # ГСП-1, 2024/25: в исходной графе 19, номер 57 повторён — аналитика по 18 уникальным
    entry = dataset.get('ГСП-1', '2024/25')
    assert entry.raw_count == 19
    assert len(entry.unique) == 18
    # ГСП-9, 2024/25: текстовая пометка, сезон исключён из числовой аналитики
    assert dataset.get('ГСП-9', '2024/25').raw_wells == 'Ревизия не проводилась'
    assert dataset.get('ГСП-9', '2024/25').known is False


def test_analytics_by_hand_values(dataset):
    analytics = rr.analyse(dataset)
    summary = {r['gsp']: r for r in analytics['summary']}
    assert summary['ГСП-1']['unique'] == 25
    assert summary['ГСП-1']['coverage'] == 5
    assert summary['ГСП-2']['unique'] == 34
    assert summary['ГСП-6']['coverage'] == 4                         # 2025/26 без данных
    assert analytics['totals'][-1]['complete'] is False             # не у всех ГСП есть данные за последний сезон


def test_module_builds_table_19(dataset):
    result = RevisionModule().run(Data({}), {'history': str(HISTORY), 'revision': str(REVISION), 'season': '2025/26',
                                              'filter': '', 'absent_zero': False})
    ids = [t.id for t in result.tables]
    assert ids[0] == 'an-rev-1-8'
    table = result.tables[0]
    row = table.frame[table.frame.gsp.eq('ГСП-1')].iloc[0]
    assert row['c4'] == 12 or row['c4'] == '12'
    assert '38' in row['w4']
    assert len(table.header[0]) == 1 + len(dataset.seasons)
    assert any(s.label.startswith('Сезонов') and s.value == '5' for s in result.summary)


def test_module_missing_files_is_a_note_not_an_error():
    result = RevisionModule().run(Data({}), {'history': '', 'revision': '', 'season': '2025/26', 'filter': '', 'absent_zero': False})
    assert result.tables == []
    assert result.notes and 'Выберите' in result.notes[0].text
    bad = RevisionModule().run(Data({}), {'history': str(DATA / 'нет.xlsx'), 'revision': str(REVISION), 'season': '2025/26',
                                           'filter': '', 'absent_zero': False})
    assert bad.tables == [] and bad.notes[0].level == 'warning'


def test_file_param_coerce_strips_quotes():
    spec = RevisionModule.spec
    param = next(p for p in spec.params if p.name == 'revision')
    assert param.kind == 'file'
    assert param.coerce('  "C:\\Данные\\ревизия.docx" ') == 'C:\\Данные\\ревизия.docx'
    assert param.coerce(None) == ''
    with pytest.raises(ParamError):
        spec.coerce({'unknown': 1})
