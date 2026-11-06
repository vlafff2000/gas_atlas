"""КРС: лист «План КР» книги → krs_plan; таблица 7.1 по справке (ремонт будет — в таблице, не будет — нет)."""
import io

import pandas as pd

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.engine.core import krs_import
from atlas.modules.krs_report import KrsReportModule

ROWS = [
    # год, скважина, тип, вид, шифры, коды, квартал, цвет, состояние, начало, конец, статус, будет, в 7.1, проверить
    (2026, '11', 'эксплуатационная', 'КР', 'КР 1.094 Замена фильтра', 'КР 1.094', '2', 'зелёный', 'Выполнено', '06.07.2026', '01.09.2026', '', 'Да', 'Да', ''),
    (2026, '12', 'эксплуатационная', 'КР', 'КР 1.094 Замена фильтра', 'КР 1.094', '2', 'жёлтый', 'В процессе', '14.01.2026', '', '', 'Да', 'Да', ''),
    (2026, '13', 'эксплуатационная', 'КР', 'КР 4.033', 'КР 4.033', '2', 'красный', 'Не делают', '', '', 'В план КР', 'Нет', 'Нет', 'красный'),
    (2026, '14', 'наблюдательная', 'КР', 'КР 2.022', 'КР 2.022', '3', '', 'Не начато', '', '', 'Утвержден', 'Да', 'Да', ''),
    (2026, '7', 'эксплуатационная', 'ТР', 'ТР 2 Поддержание режима', 'ТР 2', '', 'зелёный', 'Выполнено', '25.05.2026', '28.05.2026', '', 'Да', 'Да', ''),
]
HEAD = ['Год', 'Скважина', 'Тип скважины', 'Вид', 'Шифры работ', 'Коды работ', 'Квартал', 'Цвет в справке', 'Состояние', 'Дата начала', 'Дата окончания',
        'Статус справки', 'Ремонт будет', 'В таблицу 7.1', 'Проверить']


def book() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as xw:
        pd.DataFrame({'Скважина': [11], 'Год': [2026], 'Тип ремонта': ['Замена фильтра']}).to_excel(xw, sheet_name='Ремонты', index=False)
        pd.DataFrame({'Скважина': [11], 'ГСП': ['ГСП-1'], 'Приоритет итог': [2]}).to_excel(xw, sheet_name='Приоритет', index=False)
        pd.DataFrame(ROWS, columns=HEAD).to_excel(xw, sheet_name='План КР', index=False)
    return buf.getvalue()


def test_plan_sheet_is_read_and_optional():
    parts, _ = krs_import.read('k.xlsx', book())
    plan = parts[krs_import.PLAN]
    assert plan.well.tolist() == ['11', '12', '13', '14', '7'] and plan.in_table.tolist() == ['Да', 'Да', 'Нет', 'Да', 'Да']
    assert plan.start.iloc[0] == pd.Timestamp('2026-07-06') and pd.isna(plan.end.iloc[1])
    buf = io.BytesIO()                                              # книга без листа «План КР» читается как раньше
    with pd.ExcelWriter(buf, engine='openpyxl') as xw:
        pd.DataFrame({'Скважина': [1]}).to_excel(xw, sheet_name='Ремонты', index=False)
        pd.DataFrame({'Скважина': [1]}).to_excel(xw, sheet_name='Приоритет', index=False)
    assert krs_import.PLAN not in krs_import.read('k.xlsx', buf.getvalue())[0]


def test_table_71_follows_will_rule():
    plan = krs_import.read('k.xlsx', book())[0][krs_import.PLAN]
    res = KrsReportModule().run(Data({DatasetKind.KRS_PLAN: plan}), {'year': 0, 'scope': 'table'})
    kr, tr = res.tables[0].frame, res.tables[1].frame
    assert kr.well.tolist() == ['11', '12', '14'] and tr.well.tolist() == ['7']      # 13 — красная, статус «В план КР»: не в таблице
    assert kr.set_index('well').loc['12', 'state'] == 'В процессе' and pd.isna(kr.set_index('well').loc['12', 'end'])
    allrows = KrsReportModule().run(Data({DatasetKind.KRS_PLAN: plan}), {"year": 0, "scope": "all"}).tables[0].frame
    assert '13' in allrows.well.tolist()
    assert not KrsReportModule().run(Data({}), {'year': 0, 'scope': 'table'}).tables       # нет данных — заметка, не ошибка
