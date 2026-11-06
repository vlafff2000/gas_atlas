"""Активные дни и простой считаются по часам работы, а не по расходу (если часы есть)."""
import pandas as pd
from atlas.engine.core import performance
from atlas.engine.modules import production


def frame():
    dates = pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04'])
    return pd.DataFrame({'well': '1', 'date': dates, 'kind': 'withdrawal',
                         'q': [1000.0, 0.0, 0.0, 2000.0], 'hours': [24.0, 12.0, 0.0, float('nan')]})


def test_hours_decide_active_and_idle():
    # Тест: tests/test_active_days_by_hours.py::test_hours_decide_active_and_idle
    d = production.periods(frame(), 11, 4)
    for df in (d, performance.with_index(d.copy(), 'production')):
        a = production.averages(df, 'withdrawal', list(d.period.unique()), ['1'])
        row = a.iloc[0]
        assert row.active == 3     # 24 ч, 12 ч при нулевом расходе, нет часов -> по расходу
        assert row.zero == 1       # только 0 ч


def test_without_hours_column_uses_flow():
    d = production.periods(frame().drop(columns='hours'), 11, 4)
    a = production.averages(d, 'withdrawal', list(d.period.unique()), ['1']).iloc[0]
    assert a.active == 2 and a.zero == 2
