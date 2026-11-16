"""План КР на год (Excel): разбор, пропуск «-», план не попадает в таблицу 7.1 и в даты ремонтов, справка приоритетнее."""
import io

import pandas as pd
from openpyxl import Workbook

from atlas.engine.core import krs_plan_file_import as kp
from atlas.engine.core import tabular
from atlas.imports import special_kind
from atlas.modules.gdi_summary import repairs
from atlas.modules.krs_report import select

HEAD = ['Номер скважины', 'Полное наименование', 'Инвентарный номер', 'Краткое описание работ', 'Начало работ', 'Окончание работ']


def book(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(HEAD)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ts = pd.Timestamp
ROWS = [[35, 'Скважина № 35 ГСП-2', '1', 'КР 1.094-ПА Замена противопесочного фильтра', ts('2026-04-01').to_pydatetime(), ts('2026-09-30').to_pydatetime()],
        [42, 'Скважина № 42', '2', 'КР 2.022-ГТ Ликвидация пробки', ts('2026-07-01').to_pydatetime(), ts('2026-10-30').to_pydatetime()],
        ['-', 'без номера', '3', 'КР 2.022-ГТ Ликвидация пробки', ts('2026-07-01').to_pydatetime(), ts('2026-09-30').to_pydatetime()]]


def test_read_skips_dash_and_marks_source():
    plan, warn = kp.read('План КР 2026.xlsx', book(ROWS))
    assert plan.well.tolist() == ['35', '42'] and set(plan.source) == {'план'} and plan.year.tolist() == [2026, 2026]
    assert plan.codes.tolist() == ['КР 1.094-ПА', 'КР 2.022-ГТ'] and plan.start.iloc[0] == ts('2026-04-01') and any('пропущено' in w for w in warn)
    assert special_kind(tabular.read_content(book(ROWS), 'План КР 2026.xlsx', 31)[1], 'План КР 2026.xlsx')[0] == 'krs_plan_file'


def test_plan_never_leaks_into_table_7_1_or_repair_dates_and_sprav_wins():
    plan, _ = kp.read('p.xlsx', book(ROWS))
    fact = plan.iloc[:1].assign(source='', start=ts('2026-05-10'), end=ts('2026-06-20'), in_table='Да')
    store = kp.merge(fact.copy(), plan)                                     # справка по 35/2026 уже есть: строка плана не добавляется
    assert store.well.tolist() == ['35', '42'] and store.source.fillna('').tolist() == ['', 'план']
    assert select(store, 'all', 2026).well.tolist() == ['35']               # таблица 7.1 — только справка
    works = pd.DataFrame({'well': ['42'], 'year': [2026], 'work_type': ['КР'], 'detail': ['']})
    assert not repairs(works, store).dated.iloc[0]                         # плановая дата ремонта не используется
    assert kp.merge(store, plan).source.tolist().count('план') == 1         # повторная загрузка заменяет строки плана, не дублирует


def test_load_into_project_keeps_source_and_undo(tmp_path):
    from _wells_data import make_project
    from atlas.imports import Imports
    from atlas.projects import Projects
    projects = Projects(tmp_path)
    pid = make_project(projects)
    done = Imports(projects).krs_plan_file_load(pid, 'План КР 2026.xlsx', book(ROWS), 'new')
    assert 'только в Атласе' in done['message'] and done['undo']
    frame = Imports(projects)._raw_frames(pid, projects.manifest(pid))['krs_plan']
    assert frame.well.tolist() == ['35', '42'] and set(frame.source) == {'план'}
