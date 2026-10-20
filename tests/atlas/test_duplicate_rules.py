"""Дубли суток одной скважины: правило выбирает инженер; по умолчанию — строка с расходом (как раньше)."""
import pandas as pd

from atlas.engine.core.loader import prefer_flow


def _frame():
    return pd.DataFrame({'kind': ['withdrawal'] * 3, 'well': ['1'] * 3,
                         'date': pd.to_datetime(['2023-01-01'] * 3), 'q': [0.0, 5.0, 7.0]})


def test_default_rule_keeps_flow_row():
    out, dropped = prefer_flow(_frame())
    assert dropped == 2 and out.q.tolist() == [7.0]


def test_first_and_last_keep_row_as_is():
    first, dropped_first = prefer_flow(_frame(), 'first')
    last, dropped_last = prefer_flow(_frame(), 'last')
    assert first.q.tolist() == [0.0] and dropped_first == 2
    assert last.q.tolist() == [7.0] and dropped_last == 2


def test_no_duplicates_untouched():
    frame = _frame().iloc[:1]
    out, dropped = prefer_flow(frame, 'last')
    assert dropped == 0 and len(out) == 1
