"""Программа ГДИ на сезон (Word-таблица: этапы, причины, «ГСП-N: номера»): разбор, сезон из имени, сверка группы с проектом, загрузка."""
import io
import zipfile

import pytest

from _wells_data import make_project
from atlas.engine.core import gdi_program_import as gp
from atlas.imports import Imports, special_kind
from atlas.engine.core import tabular
from atlas.projects import Projects

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def cell(*lines):
    return '<w:tc>' + ''.join(f'<w:p><w:r><w:t>{x}</w:t></w:r></w:p>' for x in lines) + '</w:tc>'


def docx(rows):
    body = ''.join('<w:tr>' + ''.join(cell(*c) for c in r) + '</w:tr>' for r in rows)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body><w:tbl>{body}</w:tbl></w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', xml)
    return buf.getvalue()


ROWS = [[[''], ['Кол-во скважин'], ['Номера исследуемых скважин']],
        [['I этап'], ['4'], ['После капремонта - замена противопесочного фильтра', 'ГСП-1: 38', 'ГСП-2: 71',
                             'Скважины, указанные в плане капремонта на 2026 год', 'ГСП-6: 307, 328']],
        [['II этап'], ['2'], ['Скважины, где более 5 лет не проводились ГДИ', 'ГСП-2:92, 94']],
        [['ИТОГО:'], ['7'], ['']]]
NAME = 'Программа 25-26 для ГА.docx'


def test_read_blocks_reasons_and_season():
    df, warn = gp.read(NAME, docx(ROWS))
    assert not warn and len(df) == 6 and set(df.season) == {'2025-2026'}
    assert df.groupby('reason_kind').well.apply(list).to_dict() == {
        'filter': ['38', '71'], 'krs_plan': ['307', '328'], 'gap': ['92', '94']}
    assert df[df.reason_kind.eq('krs_plan')].krs_injection.all() and not df[df.reason_kind.eq('filter')].krs_injection.any()


def test_count_mismatch_and_missing_season_are_warnings():
    rows = [r[:] for r in ROWS]
    rows[1][1] = ['9']
    df, warn = gp.read('программа.docx', docx(rows))
    assert any('указано скважин 9, в перечне найдено 4' in w for w in warn) and any('Сезон программы не определён' in w for w in warn)
    assert set(gp.read('программа.docx', docx(rows), '2026-2027')[0].season) == {'2026-2027'}


def test_recognized_by_common_import():
    _, tables = tabular.read_content(docx(ROWS), NAME)
    assert special_kind(tables, NAME) == ('gdi_program', 'программа ГДИ')


def test_group_from_project_wins():
    df, _ = gp.read(NAME, docx(ROWS))
    fixed, warn = gp.reconcile(df, {'307': 'ГСП 5', '38': 'ГСП-1'})
    assert fixed[fixed.well.eq('307')].group.tolist() == ['ГСП 5'] and any('307' in w and 'ГСП-6' in w for w in warn)
    assert fixed[fixed.well.eq('38')].group.tolist() == ['ГСП-1']          # «ГСП-1» = «ГСП 1»: не расхождение


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    return make_project(projects), projects


def test_load_replaces_same_season(env):
    pid, projects = env
    out = Imports(projects).gdi_program_load(pid, NAME, docx(ROWS), 'new')
    assert 'скважин 6' in out['message']
    again = Imports(projects).gdi_program_load(pid, NAME, docx(ROWS[:2] + [ROWS[3]]), 'new')
    frame = Imports(projects)._raw_frames(pid, projects.manifest(pid))['gdi_program']
    assert len(frame) == 4 and 'gdi_program' in projects.manifest(pid)['tables'] and again['undo']
