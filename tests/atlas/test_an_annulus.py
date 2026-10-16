"""Табл. 11.3 «Межколонные давления»: отбор скважин, группы и текст статистики на малом примере, рассчитанном вручную."""
import pandas as pd

from atlas.modules import an_annulus


def rows(*items):
    """(скважина, расход МКП м³/сут, давление МКД кгс/см²) за одну дату — в именах колонок Атласа."""
    return pd.DataFrame([{'well': str(w), 'q': q, 'p': p} for w, q, p in items])


def test_only_wells_with_flow_or_pressure_and_sorted_by_number():
    data = rows((9, 0.0, 0.0), (5, 12.0, 8.0), (2, 0.0, 30.0), (7, 0.0, 0.0))
    wells = an_annulus.annulus_wells(data)
    assert wells['well'].tolist() == [2, 5]


def test_max_over_period_and_duplicate_rows():
    # две строки на одну скважину и дату: берётся максимум, как в скрипте анализа
    data = rows((3, 50.0, 20.0), (3, 53.0, 25.0), (3, 0.0, 0.0))
    wells = an_annulus.annulus_wells(data)
    assert wells.loc[0, 'q_max'] == 53.0
    assert wells.loc[0, 'p_max'] == 25.0


def test_pressure_groups_follow_report_limits():
    # 0 при расходе — близкое к нулю; 28 включительно — до 28; выше 28 — свыше 28
    data = rows((1, 5.0, 0.0), (2, 4.0, 28.0), (3, 4.0, 28.5), (4, 2.0, 2.0))
    groups = an_annulus.annulus_wells(data).set_index('well')['group'].to_dict()
    assert groups == {1: an_annulus.GROUP_NEAR_ZERO, 2: an_annulus.GROUP_LOW,
                      3: an_annulus.GROUP_HIGH, 4: an_annulus.GROUP_LOW}


def test_flow_groups_boundaries():
    assert an_annulus.flow_group(10.0) == 'малый'
    assert an_annulus.flow_group(10.1) == 'средний'
    assert an_annulus.flow_group(90.0) == 'средний'
    assert an_annulus.flow_group(90.1) == 'большой'


def test_table_rounding_and_columns():
    data = rows((37, 37.44, 25.6), (344, 2.88, 0.0))
    table = an_annulus.table_11_3(an_annulus.annulus_wells(data))
    assert list(table.columns) == list(an_annulus.COLUMNS)
    assert table.iloc[0].tolist() == [37, 37.4, 26, an_annulus.GROUP_LOW]
    assert table.iloc[1].tolist() == [344, 2.9, 0, an_annulus.GROUP_NEAR_ZERO]


def test_classification_text_lists_numbers_per_group():
    data = rows((344, 2.9, 0.0), (37, 37.4, 26.0), (78, 50.4, 35.0), (81, 96.5, 67.0))
    lines = an_annulus.classification_text(an_annulus.annulus_wells(data))
    text = '\n'.join(lines)
    assert 'отмечаются на 4 скважинах' in text
    assert 'минимальным (близким к нулю) МКД - 1 скв. (№ 344)' in text
    assert 'до 28 кгс/см² - 1 скв. (№ 37)' in text
    assert 'свыше 28 кгс/см² - 2 скв. (№ 78, 81)' in text
    assert 'малой величиной расхода из МКП (0 < Q ≤ 10) - 1 ед. (скв. № 344)' in text
    assert 'большой величиной расхода из МКП (Q > 90) - 1 ед. (скв. № 81)' in text


def test_empty_period_gives_note_not_error():
    wells = an_annulus.annulus_wells(rows((1, 0.0, 0.0)))
    assert wells.empty
    assert an_annulus.classification_text(wells) == ['В выбранном периоде межколонные давления и расход из МКП не отмечены.']
    assert an_annulus.table_11_3(wells).empty


# --- База межколонок: распознавание, импорт и табл. 11.3 в модуле «Авторский надзор: сезон» ---

from pathlib import Path  # noqa: E402

from atlas.contract import Data  # noqa: E402
from atlas.domain import DatasetKind  # noqa: E402
from atlas.engine.core.loader import detect_layout, load_file  # noqa: E402
from atlas.modules import an_report  # noqa: E402

PRODUCTION_STUB = pd.DataFrame([('1', pd.Timestamp('2025-01-01'), 100.0, 'withdrawal', '2024-2025')], columns=['well', 'date', 'q', 'kind', 'period'])
DB_HEADER = 'дата;год;месяц;сезон;номер_скважины;расход_газа_МК_сут;расход_газа_МК_мес;давление_МК'


def test_db_header_is_detected_as_annulus():
    head = [[c for c in DB_HEADER.split(';')], ['2025-09-01', 2025, 'Сентябрь', 'Межсезонье 2025', 78, 50.4, 1512, 9]]
    assert detect_layout(head)['module'] == 'annulus'


def test_import_keeps_season_and_values(tmp_path):
    path = tmp_path / 'mk.csv'
    path.write_text(DB_HEADER + '\n2025-09-01;2025;Сентябрь;Межсезонье 2025;78;50,4;1512;9\n'
                    '2025-09-01;2025;Сентябрь;Межсезонье 2025;344;2,88;86,4;\n', encoding='utf-8')
    r = load_file(path, 'annulus', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    frame = r.frames['annulus'].assign(well=lambda f: f['well'].astype(int)).sort_values('well').reset_index(drop=True)
    assert frame['well'].tolist() == [78, 344]
    assert frame['q'].tolist() == [50.4, 2.88]
    assert frame['p'].tolist() == [9.0, 0.0]              # пустое давление — ноль, как в базе
    assert set(frame['season']) == {'Межсезонье 2025'}


def test_author_report_builds_table_11_3_for_chosen_season():
    rows_ = pd.DataFrame([
        {'well': '344', 'date': pd.Timestamp('2025-09-01'), 'season': 'Межсезонье 2025', 'q': 2.9, 'p': 0.0},
        {'well': '37', 'date': pd.Timestamp('2025-09-01'), 'season': 'Межсезонье 2025', 'q': 37.4, 'p': 1.0},
        {'well': '37', 'date': pd.Timestamp('2024-09-01'), 'season': 'Межсезонье 2024', 'q': 9.0, 'p': 5.0},
    ])
    data = Data({DatasetKind.ANNULUS: rows_, DatasetKind.PRODUCTION: PRODUCTION_STUB})
    result = an_report.AuthorReportModule().run(data, {'kind': 'withdrawal', 'periods': [], 'annulus': ['Межсезонье 2025']})
    table = next(t for t in result.tables if t.id == 'an-annulus-113')
    assert table.frame['№ скв.'].tolist() == [37, 344]
    assert table.frame['Qм/к, м³/сут'].tolist() == [37.4, 2.9]
    assert any('близким к нулю' in n.text for n in result.notes)


def test_author_report_without_annulus_is_a_note():
    result = an_report.AuthorReportModule().run(Data({DatasetKind.PRODUCTION: PRODUCTION_STUB}), {'kind': 'withdrawal', 'periods': [], 'annulus': []})
    assert not any(t.id == 'an-annulus-113' for t in result.tables)
    assert any('Табл. 11.3 не построена' in n.text for n in result.notes)
