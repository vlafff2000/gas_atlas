"""«БД давлений по замерам» (месячные отчёты, База ПХГ): распознавание, загрузка во вкладке «Импорт», замена по скважине и дате,
чек-лист и ряд Рпл на графике «Производительность скважин»."""
import io

import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from _wells_data import make_project
from atlas.api import create_app
from atlas.engine.core import survey_import
from atlas.imports import Imports, special_kind
from atlas.projects import Projects

HEAD = ['Скважина', 'Дата', 'Горизонт', 'Категория', 'Руст', 'Избыточное давление', 'Рпл', 'Уровень жидкости', 'Примечание', 'Источник']


def book(rows):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        pd.DataFrame(rows, columns=HEAD).to_excel(xw, sheet_name='Данные', index=False)
    return buf.getvalue()


ROWS = [[31, '2025-09-15', 'Щигровский', 'Эксплуатационная', 95.0, None, 108.5, None, '', 'сентябрь.xlsx'],
        [31, '2025-10-15', 'Щигровский', 'Эксплуатационная', 96.0, None, 'н.д.', None, 'н.д.', 'октябрь.xlsx'],
        [540, '2025-09-20', 'Окский', 'Наблюдательная', None, None, 77.0, 120.0, '', 'сентябрь.xlsx'],
        [None, '2025-09-20', '', '', None, None, 1.0, None, '', '']]


@pytest.fixture()
def env(tmp_path):
    projects = Projects(tmp_path)
    return TestClient(create_app(projects)), make_project(projects), projects


def test_read_keeps_raw_values_and_reports_skipped():
    d, warn = survey_import.read('БД давлений по замерам.xlsx', book(ROWS))
    assert d.well.tolist() == ['31', '31', '540'] and any('Пропущено строк' in w for w in warn)
    assert d.p_res.tolist()[0] == 108.5 and np.isnan(d.p_res.tolist()[1])         # текст «н.д.» — пропуск, не ноль
    assert d.note.tolist()[1] == 'н.д.' and d.level.iloc[2] == 120.0


def test_survey_book_is_recognized_and_replaced_by_well_and_date(env):
    _, pid, projects = env
    tables = pd.read_excel(io.BytesIO(book(ROWS)), sheet_name=None, header=None)
    assert special_kind(tables, 'БД давлений по замерам.xlsx')[0] == 'survey'
    done = Imports(projects).survey_load(pid, 'a.xlsx', book(ROWS), 'new')
    assert 'замеров 3' in done['message'] and projects.manifest(pid)['tables']['pressure_survey'] == 3
    fix = [[31, '2025-09-15', 'Щигровский', 'Эксплуатационная', 95.0, None, 110.0, None, '', 'сентябрь.xlsx']]
    Imports(projects).survey_load(pid, 'b.xlsx', book(fix), 'new')          # та же скважина и дата заменяется, остальные остаются
    d = projects.data(pid)['pressure_survey']
    assert len(d) == 3 and d[(d.well == '31') & (d.date == '2025-09-15')].p_res.iloc[0] == 110.0
    Imports(projects).survey_load(pid, 'c.xlsx', book(fix[:1] and [[31, '2025-09-15'] + fix[0][2:6] + [999.0] + fix[0][7:]]), 'old')
    assert projects.data(pid)['pressure_survey'].query("well=='31' and date=='2025-09-15'").p_res.iloc[0] == 110.0   # «оставить прежние»


def test_checklist_lists_survey(env):
    from atlas import import_checklist
    _, pid, projects = env
    Imports(projects).survey_load(pid, 'a.xlsx', book(ROWS), 'new')
    items = {i['key']: i for i in import_checklist.build(projects.manifest(pid))}
    assert items['pressure_survey']['count'] == 3 and 'Производительность' in items['pressure_survey']['used']
