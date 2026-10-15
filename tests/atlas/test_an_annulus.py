"""Табл. 11.3 «Межколонные давления»: отбор скважин, группы и текст статистики на малом примере, рассчитанном вручную."""
import pandas as pd

from atlas.modules import an_annulus


def rows(*items):
    """(скважина, расход МКП м³/сут, давление МКД кгс/см²) за одну дату."""
    return pd.DataFrame([{'номер_скважины': w, 'расход_газа_МК_сут': q, 'давление_МК': p} for w, q, p in items])


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
