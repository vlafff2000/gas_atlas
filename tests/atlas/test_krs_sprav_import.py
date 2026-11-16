"""Справка о выполнении плана КР (.docx) в общем импорте: распознавание, цвет выделения, даты, статусы, ТР отдельно, загрузка в проект."""
import io
import zipfile
from xml.sax.saxutils import escape

from _wells_data import make_project
from atlas.engine.core import krs_sprav_import as ks
from atlas.engine.core import tabular
from atlas.imports import special_kind
from atlas.projects import Projects

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def run(txt, hl=None):
    pr = f'<w:rPr><w:highlight w:val="{hl}"/></w:rPr>' if hl else ''
    return f'<w:r>{pr}<w:t>{escape(txt)}</w:t></w:r>'


def cell(items):
    items = items if isinstance(items, list) else [(items, None)]
    return '<w:tc>' + ''.join(f'<w:p>{run(t, h)}</w:p>' for t, h in items) + '</w:tc>'


def row(*cells):
    return '<w:tr>' + ''.join(cell(c) for c in cells) + '</w:tr>'


def sprav() -> bytes:
    head = row('Шифр', 'План', 'План', 'Выполнено', 'Выполнено', 'Примечания', '', '')
    kr = row('КР 1.094-ПА Замена фильтра', '2', [('11(Э)', 'green'), ('13(Н)', 'red')], '1', [('11(Э)', 'green')],
             '2 квартал / Cкв№11 / Начата ремонтом / 06.07.26г / Дата окончания / 01.09.2026г', 'Скв13 статус / В план КР', '')
    tr = row('ТР 3.01 Текущий ремонт', '1', [('15(П)', 'green')], '1', [('15(П)', 'green')], 'Скв 15-25.05.2026-28.05.2026г', '', '')
    body = f'<w:p>{run("Справка по выполнению Плана капитального ремонта скважин на ПХГ в 2026г.")}</w:p><w:tbl>{head}{kr}{tr}</w:tbl>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def test_recognised_by_general_import_and_parsed():
    _, tables = tabular.read_content(sprav(), 'Справка.docx')
    assert special_kind(tables, 'Справка.docx')[0] == 'krs_sprav'
    plan, warnings = ks.read('Справка.docx', sprav())
    p = plan.set_index('well')
    assert set(p.index) == {'11', '13', '15'} and (plan.year == 2026).all()
    assert p.loc['11', 'state'] == 'Выполнено' and p.loc['11', 'end'].strftime('%d.%m.%Y') == '01.09.2026'
    assert p.loc['13', 'will'] == 'Нет' and p.loc['13', 'well_type'] == 'наблюдательная'
    assert p.loc['15', 'kind'] == 'ТР' and p.loc['15', 'well_type'] == 'поглотительная'


def test_not_confused_with_other_word_tables():
    other = io.BytesIO()
    with zipfile.ZipFile(other, 'w') as z:
        z.writestr('word/document.xml', f'<w:document {W}><w:body><w:tbl>{row("а", "б", "в", "г", "д", "е")}</w:tbl></w:body></w:document>')
    _, tables = tabular.read_content(other.getvalue(), 'x.docx')
    assert special_kind(tables, 'x.docx')[0] != 'krs_sprav'
