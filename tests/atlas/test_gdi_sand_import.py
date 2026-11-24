"""ГДИ на вынос песка: итоговая таблица предельных депрессий по затрубу (Word/CSV) → набор ``gdi_sand``; ручная правка; замена по скважине и дате."""
import io
import zipfile

import pytest

from _wells_data import make_project
from atlas.engine.core import gdi_sand_import as gs, tabular
from atlas.imports import Imports, special_kind
from atlas.projects import Projects

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
HEAD = ['№ скв', 'dP(затр), кгс/см2', 'Q, тыс. м3/сут', 'КРУ, %']
ROWS = [HEAD, ['522', '1,58', '888', '31'], ['523', '0,73', '360', '9'], ['527', '0,918', '828', '6'], ['532', '1,14', '1032', '64']]
NAME = 'Отчёт ГДИ песок 03.11.2025.docx'


def docx(rows):
    body = ''.join('<w:tr>' + ''.join(f'<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>' for c in r) + '</w:tr>' for r in rows)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body><w:tbl>{body}</w:tbl></w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', xml)
    return buf.getvalue()


def test_read_table_with_comma_decimals_and_date_from_name():
    df, warn = gs.read(NAME, docx(ROWS))
    assert not warn and df.well.tolist() == ['522', '523', '527', '532']
    assert df.dp_annulus.tolist() == [1.58, 0.73, 0.918, 1.14] and df.q.tolist() == [888, 360, 828, 1032] and df.kru.tolist() == [31, 9, 6, 64]
    assert set(df.date.dt.strftime('%Y-%m-%d')) == {'2025-11-03'}


def test_manual_date_wins_and_missing_date_warns():
    df, warn = gs.read('отчёт.docx', docx(ROWS))
    assert df.date.isna().all() and any('Дата исследования' in w for w in warn)
    assert set(gs.read(NAME, docx(ROWS), '10.12.2025')[0].date.dt.strftime('%d.%m.%Y')) == {'10.12.2025'}


def test_recognized_by_common_import_and_csv():
    _, tables = tabular.read_content(docx(ROWS), NAME)
    assert special_kind(tables, NAME) == ('gdi_sand', 'ГДИ на вынос песка')
    csv = '\n'.join(';'.join(r) for r in ROWS).encode('utf-8-sig')
    assert len(gs.read('песок 2025-11-03.csv', csv)[0]) == 4


def test_missing_number_is_kept_with_note():
    rows = [r[:] for r in ROWS]
    rows[2][1] = '—'
    df, warn = gs.read(NAME, docx(rows))
    assert len(df) == 4 and df.dp_annulus.isna().sum() == 1 and any('523' in w for w in warn)


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    return make_project(projects), projects


def test_load_replaces_same_well_and_date_and_keeps_manual_rows(env):
    pid, projects = env
    out = Imports(projects).gdi_sand_load(pid, NAME, docx(ROWS), 'new')
    assert 'скважин 4' in out['message']
    imp = Imports(projects)
    frame = imp._raw_frames(pid, projects.manifest(pid))['gdi_sand']
    manual = frame.iloc[:1].assign(well='999', source='вручную')            # правка инженера: добавленная вручную строка
    m = projects.manifest(pid)
    frames = imp._raw_frames(pid, m)
    frames['gdi_sand'] = __import__('pandas').concat([frame, manual], ignore_index=True)
    imp._commit(pid, frames, m['revision'], 'Правка вручную')
    rows = ROWS[:2] + [['523', '0,80', '400', '10']]
    imp.gdi_sand_load(pid, NAME, docx(rows), 'new')
    frame = imp._raw_frames(pid, projects.manifest(pid))['gdi_sand']
    assert sorted(frame.well) == ['522', '523', '527', '532', '999']          # скважины 527 и 532 не в новом файле: остаются; 999 вручную: остаётся
    assert frame[frame.well.eq('523')].dp_annulus.tolist() == [0.80]
