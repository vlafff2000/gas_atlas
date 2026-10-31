"""Эффект ремонта до/после: выбор сезонов, сравнение с группой, пропуски."""
import pandas as pd
import pytest

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules.repair_effect import RepairEffectModule, effects, pick_periods, withdrawal_seasons

P, W = DatasetKind.PRODUCTION, DatasetKind.KRS_WORKS
PARAMS = {'month': 7, 'seasons': 1, 'threshold': 0.95}
SEASONS = (('2023-2024', '2023-11-01', 1), ('2024-2025', '2024-11-01', 1), ('2025-2026', '2025-11-01', 1))


def production():
    rows = []
    # скв. 1: ремонт в 2024 — расход 100 → 150; скв. 2, 3 той же группы: 100 → 110 → 110; скв. 3 в 2025-2026 данных не имеет
    rate = {'1': (100, 100, 150), '2': (100, 100, 110), '3': (100, 110, None)}
    for w, qs in rate.items():
        for (period, start, _), q in zip(SEASONS, qs):
            if q is None:
                continue
            for d in pd.date_range(start, periods=10):
                rows.append(dict(well=w, date=d, q=q * 1e3, kind='withdrawal', period=period))
    return pd.DataFrame(rows)


def data(works):
    d = Data({P: production(), W: pd.DataFrame(works)})
    d.mapping = {w: {'group': 'ГСП-1'} for w in '123'}
    return d


def test_seasons_before_and_after_cut():
    seasons = withdrawal_seasons(production())
    assert seasons.period.tolist() == ['2023-2024', '2024-2025', '2025-2026']
    assert pick_periods(seasons, 2025, 7, 1) == (['2024-2025'], ['2025-2026'])
    assert pick_periods(seasons, 2025, 7, 2) == (['2023-2024', '2024-2025'], ['2025-2026'])
    assert pick_periods(seasons, 2023, 7, 1) == ([], ['2023-2024', '2024-2025', '2025-2026'][:1])


def test_effect_against_group_median():
    row = effects(data({'well': ['1'], 'year': [2025.], 'work_type': ['Замена фильтра'], 'detail': ['']}), PARAMS).iloc[0]
    assert row.q_before == pytest.approx(100) and row.q_after == pytest.approx(150) and row.q_change == pytest.approx(50)
    assert row.group_change == pytest.approx(10)      # скв. 2: 100→110; скв. 3 без данных после не входит в медиану
    assert row.net_change == pytest.approx(40)


def test_missing_season_is_gap_not_zero():
    row = effects(data({'well': ['3'], 'year': [2025.], 'work_type': ['КС'], 'detail': ['']}), PARAMS).iloc[0]
    assert pd.isna(row.q_after) and pd.isna(row.q_change)        # 2025-2026 не загружен — пропуск, а не −100%


def test_module_result_and_no_works_note():
    result = RepairEffectModule().run(data({'well': ['1'], 'year': [2025.], 'work_type': ['КС'], 'detail': ['']}), PARAMS)
    assert next(t for t in result.tables if t.id == 'repair-effect').frame.shape[0] == 1
    empty = RepairEffectModule().run(Data({P: production(), W: pd.DataFrame(columns=['well', 'year', 'work_type', 'detail'])}), PARAMS)
    assert not empty.tables and empty.notes
