"""КРС: приоритет по книге из «Работы с исходными данными» и ухудшение ГДИ как признак для ремонта."""
import pandas as pd
import pytest

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.engine.core.demo import well_demo_frames
from atlas.modules import krs_status
from atlas.modules.gdi_trend import VERDICTS
from atlas.modules.krs_status import HINT_BOTH, HINT_GDI, KrsStatusModule

PARAMS = {'gdi_last': 0, 'threshold': 0.95, 'change': 10.0}


def degraded():
    g = well_demo_frames()['gdi'].copy()
    g.loc[g.well.eq('31') & g.date.gt('2025-01-01'), 'dp2'] *= 1.3
    return g


@pytest.fixture()
def krs():
    wells = sorted(degraded().well.unique(), key=int)
    prio = pd.DataFrame({'well': [wells[0], wells[1]], 'group': ['ГСП-1', 'ГСП-2'], 'priority': [3., 1.], 'priority_calc': [3., 1.],
                         'priority_manual': [None, None], 'sand': ['2024-2025', '2023-2024, 2024-2025'], 'last_year': [2019., 2023.],
                         'last_type': ['Замена фильтра', 'Колтюбинг с СКО / СКО'], 'planned': [None, None],
                         'reason': ['песок в ревизии 2024-2025', 'песок два сезона']})
    works = pd.DataFrame({'well': ['31', '31', '32'], 'year': [2019., 2023., 2023.],
                          'work_type': ['Замена фильтра', 'Колтюбинг с СКО / СКО', 'Колтюбинг без СКО'], 'detail': ['', '', '']})
    return {DatasetKind.KRS_PRIORITY: prio, DatasetKind.KRS_WORKS: works}, wells


def table(result, tid):
    return next(t for t in result.tables if t.id == tid).frame


def test_priority_and_gdi_hint(krs):
    frames, wells = krs
    assert wells[0] == '31'
    result = KrsStatusModule().run(Data({DatasetKind.GDI: degraded(), **frames}), PARAMS)
    rows = table(result, 'krs-priority').set_index('well')
    assert rows.loc['31', 'verdict'] == VERDICTS['down'] and rows.loc['31', 'hint'] == HINT_BOTH
    assert rows.loc['31', 'Приоритет итог'] == 3                       # приоритет ГДИ не меняет
    assert table(result, 'krs-priority').iloc[0].well == wells[1]       # сначала приоритет 1
    assert {c.id for c in result.charts} == {'krs-works'}


def test_gdi_only_hint_and_no_gdi(krs):
    frames, wells = krs
    prio = frames[DatasetKind.KRS_PRIORITY].copy()
    prio.loc[0, ['priority_calc', 'priority']] = None
    flags = krs_status.gdi_flags(degraded(), 0.95, 10.0, 0)
    book_prio, _ = krs_status.from_project(Data({**frames, DatasetKind.KRS_PRIORITY: prio}))
    out = krs_status.combine(book_prio, flags)
    assert out.set_index('well').loc['31', 'hint'] == HINT_GDI
    result = KrsStatusModule().run(Data(frames), PARAMS)
    assert any('Данных ГДИ' in n.text for n in result.notes) and table(result, 'krs-priority').hint.eq('').all()


def test_no_krs_in_project_points_to_import():
    result = KrsStatusModule().run(Data({}), PARAMS)
    assert any('во вкладке «Импорт»' in n.text for n in result.notes) and not result.tables
    assert not any(p.kind == 'file' for p in KrsStatusModule.spec.params)


def test_book_imported_in_import_tab_is_seen_by_module(tmp_path):
    """Сквозная связка: книга → krs_import.read (то, что делает вкладка «Импорт») → модуль."""
    import io
    from atlas.engine.core import krs_import
    wells = ['31', '32']
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        pd.DataFrame({'Скважина': [31, 32], 'ГСП': ['ГСП-1', 'ГСП-2'], 'Приоритет итог': [3, 1]}).to_excel(xw, sheet_name='Приоритет', index=False)
        pd.DataFrame({'Скважина': [31], 'Год': [2019], 'Тип ремонта': ['Замена фильтра']}).to_excel(xw, sheet_name='Ремонты', index=False)
    parts, _ = krs_import.read('КРС_для_Атласа.xlsx', buf.getvalue())
    result = KrsStatusModule().run(Data({DatasetKind.KRS_PRIORITY: parts['krs_priority'], DatasetKind.KRS_WORKS: parts['krs_works']}), PARAMS)
    assert list(table(result, 'krs-priority').well) == wells[::-1]
