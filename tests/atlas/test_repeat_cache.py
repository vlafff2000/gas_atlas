"""Повторные запросы разделов не пересчитывают одно и то же: история ГДИ и выборка сезона помнятся, результат тот же."""
import pandas as pd

from atlas.engine.core.demo import demo_frames
from atlas.modules import _rows, gdi_trend


def test_gdi_histories_repeat_is_equal_and_independent():
    gdi = demo_frames()['gdi']
    first = gdi_trend.histories(gdi, 0.95, [])
    again = gdi_trend.histories(gdi.copy(), 0.95, [])        # другая копия с тем же содержимым
    pd.testing.assert_frame_equal(first, again)
    again.loc[:, 'a'] = -1                                    # правка копии не портит запомненное
    pd.testing.assert_frame_equal(first, gdi_trend.histories(gdi, 0.95, []))
    assert not first.empty


def test_rows_of_matches_plain_filter():
    prod = pd.DataFrame({'kind': ['injection', 'withdrawal', 'injection'], 'period': ['2024', '2024', '2025'], 'q': [1.0, 2.0, 3.0]})
    pd.testing.assert_frame_equal(_rows.rows_of(prod, 'injection'), prod[prod.kind.eq('injection')])
    pd.testing.assert_frame_equal(_rows.rows_of(prod, 'injection', '2025'), prod[prod.kind.eq('injection') & prod.period.eq('2025')])
