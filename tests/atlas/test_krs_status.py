"""КРС: приоритет по книге из «Работы с исходными данными» и ухудшение ГДИ как признак для ремонта."""
import pandas as pd
import pytest

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.engine.core.demo import well_demo_frames
from atlas.modules import krs_status
from atlas.modules.gdi_trend import VERDICTS
from atlas.modules.krs_status import HINT_BOTH, HINT_GDI, KrsStatusModule

PARAMS = {'book': '', 'gdi_last': 0, 'threshold': 0.95, 'change': 10.0}


def degraded():
    g = well_demo_frames()['gdi'].copy()
    g.loc[g.well.eq('31') & g.date.gt('2025-01-01'), 'dp2'] *= 1.3
    return g


@pytest.fixture()
def book(tmp_path):
    wells = sorted(degraded().well.unique(), key=int)
    prio = pd.DataFrame({'Скважина': [int(wells[0]), int(wells[1])], 'ГСП': ['ГСП-1', 'ГСП-2'],
                         'Приоритет (расчёт)': [3, 1], 'Приоритет вручную': [None, None], 'Приоритет итог': [3, 1],
                         'Песок в ревизиях КРУ': ['2024-2025', '2023-2024, 2024-2025'], 'Последний КР': [2019, 2023],
                         'Тип последнего КР': ['Замена фильтра', 'Колтюбинг с СКО / СКО'], 'Всего КР': [2, 3], 'В плане КР': [None, None],
                         'Причина': ['песок в ревизии 2024-2025', 'песок два сезона']})
    works = pd.DataFrame({'Скважина': [31, 31, 32], 'Год': [2019, 2023, 2023],
                          'Тип ремонта': ['Замена фильтра', 'Колтюбинг с СКО / СКО', 'Колтюбинг без СКО']})
    need = pd.DataFrame({'Год': [2024, 2025], 'Приоритет 1': [0, 1], 'Приоритет 3': [2, 3], 'Всего нуждается': [2, 4]})
    path = tmp_path / 'КРС_для_Атласа.xlsx'
    with pd.ExcelWriter(path) as xw:
        prio.to_excel(xw, sheet_name='Приоритет', index=False)
        works.to_excel(xw, sheet_name='Ремонты', index=False)
        need.to_excel(xw, sheet_name='Потребность по годам', index=False)
    return path, wells


def table(result, tid):
    return next(t for t in result.tables if t.id == tid).frame


def test_priority_and_gdi_hint(book):
    path, wells = book
    assert wells[0] == '31'
    result = KrsStatusModule().run(Data({DatasetKind.GDI: degraded()}), {**PARAMS, 'book': str(path)})
    rows = table(result, 'krs-priority').set_index('well')
    assert rows.loc['31', 'verdict'] == VERDICTS['down'] and rows.loc['31', 'hint'] == HINT_BOTH
    assert rows.loc['31', 'Приоритет итог'] == 3                       # приоритет ГДИ не меняет
    assert table(result, 'krs-priority').iloc[0].well == wells[1]       # сначала приоритет 1
    assert {c.id for c in result.charts} == {'krs-works', 'krs-need'}


def test_gdi_only_hint_and_no_gdi(book):
    path, wells = book
    prio = pd.read_excel(path, sheet_name='Приоритет')
    prio.loc[0, ['Приоритет (расчёт)', 'Приоритет итог']] = None
    flags = krs_status.gdi_flags(degraded(), 0.95, 10.0, 0)
    out = krs_status.combine(prio, flags)
    assert out.set_index('well').loc['31', 'hint'] == HINT_GDI
    result = KrsStatusModule().run(Data({}), {**PARAMS, 'book': str(path)})
    assert any('Данных ГДИ' in n.text for n in result.notes) and table(result, 'krs-priority').hint.eq('').all()


def test_bad_book(tmp_path):
    bad = tmp_path / 'x.xlsx'
    pd.DataFrame({'a': [1]}).to_excel(bad, index=False)
    result = KrsStatusModule().run(Data({}), {**PARAMS, 'book': str(bad)})
    assert any('нет листов' in n.text for n in result.notes)
    assert KrsStatusModule().run(Data({}), PARAMS).notes
