"""ЭЛПРО в паспорте: сезоны отбора, расход на 1 % КРУ, давление при обычном расходе, подсказка с причиной."""
import numpy as np
import pandas as pd

from atlas import passport_elpro as pe
from atlas.passport_blocks import blocks, elpro_table


def make(open_by_period, gaps=()):
    days, el = [], []
    for k, (period, start, cru, q) in enumerate(open_by_period):
        for i in range(30):
            date = pd.Timestamp(start) + pd.Timedelta(days=i)
            days.append({'date': date, 'period': period, 'gas_volume_m3': q * 1000.0, 'work_hours': 24.0})
            if (period, i) not in gaps:
                el.append({'kind': 'withdrawal', 'well': '31', 'date': date, 'p': 80.0 + k, 't': 10.0, 'y': cru, 'q': q})
    return pd.DataFrame(el), pd.DataFrame(days)


def test_season_rows_effect_per_percent_and_verdict():
    elpro, daily = make([('2024-2025', '2024-12-01', 50.0, 100.0), ('2025-2026', '2025-12-01', 95.0, 100.0)])
    rows = pe.season_rows(elpro, daily, '31')
    assert [r['period'] for r in rows] == ['2024-2025', '2025-2026']
    assert rows[0]['eff'] == 2.0 and round(rows[1]['eff'], 3) == round(100 / 95, 3)
    assert rows[0]['verdict'] == 'норма' and rows[1]['verdict'] == 'внимание'
    assert 'запас регулирования' in rows[1]['reason'] and 'на 1 % КРУ упал на 47 %' in rows[1]['reason']
    assert rows[1]['p_change'] == 1.0


def test_season_without_elpro_is_empty_not_zero():
    elpro, daily = make([('2024-2025', '2024-12-01', 50.0, 100.0), ('2025-2026', '2025-12-01', 50.0, 100.0)],
                        gaps={('2025-2026', i) for i in range(30)})
    rows = pe.season_rows(elpro, daily, '31')
    assert rows[1]['days'] == 0 and rows[1]['mean_open'] is None and rows[1]['verdict'] == 'нет данных ЭЛПРО'
    assert pe.season_rows(None, daily, '31') == []


def test_blocks_add_cru_axis_and_table():
    elpro, daily = make([('2024-2025', '2024-12-01', 50.0, 100.0)])
    card = {'seasons': [], 'gdi_diagrams': [], 'gdi': [], 'krs': {'works': []}, 'elpro': pe.season_rows(elpro, daily, '31'),
            'elpro_cru': pe.cru_series(elpro, '31'),
            'daily': {'withdrawal': {'date': ['2024-12-01'], 'volume': [100.0], 'hours': [24.0]}, 'injection': {}}}
    charts, tables = blocks(card)
    daily_chart = next(c for c in charts if c.id == 'passport-daily')
    assert daily_chart.y2 is not None and daily_chart.series[-1].axis == 'y2'
    assert [t.id for t in tables] == ['passport-elpro'] and elpro_table([]) is None
