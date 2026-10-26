"""«Спад давления в конце закачки»: максимум и конец закачки, темп последнего месяца, поправки «Вручную», пустое давление."""
import pandas as pd
import pytest

from atlas.contract import Data, ParamError
from atlas.domain import DatasetKind
from atlas.modules.injection_decline import InjectionDeclineModule

PROD, OBJ = DatasetKind.PRODUCTION, DatasetKind.OBJECT_PRESSURE


def production():
    rows = []
    for period, start in (('2022', '2022-05-01'), ('2023', '2023-05-01')):
        for d in pd.date_range(start, periods=60):
            rows.append({'well': '1', 'date': d, 'q': 100000.0, 'kind': 'injection', 'period': period})
    rows.append({'well': '1', 'date': pd.Timestamp('2022-08-01'), 'q': 9e6, 'kind': 'withdrawal', 'period': '2022-2023'})
    return pd.DataFrame(rows)


def pressure():
    # 2022: давление растёт до конца закачки; 2023: максимум 140 за 2 суток до конца, к концу спад до 135
    p22 = [(d, 100 + i) for i, d in enumerate(pd.date_range('2022-05-01', periods=60, freq='D')[::5])]
    p23 = [(d, 120 + i * 0.3) for i, d in enumerate(pd.date_range('2023-05-01', periods=50, freq='D')[::5])]
    p23 += [(pd.Timestamp('2023-06-27'), 140.0), (pd.Timestamp('2023-06-29'), 135.0)]
    return pd.DataFrame(p22 + p23, columns=['date', 'pressure'])


def run(params=None, frame=None, pres=None):
    data = Data({PROD: production() if frame is None else frame, OBJ: pressure() if pres is None else pres})
    base = {'seasons': 5, 'periods': [], 'source': 'auto', 'last_days': 30, 'tail_days': 45, 'manual': None}
    return InjectionDeclineModule().run(data, {**base, **(params or {})})


def table(result):
    return result.tables[0].frame.set_index('period')


def test_max_end_drop_and_last_month():
    t = table(run())
    row = t.loc['2022']
    assert row.max_date == pd.Timestamp('2022-06-25')        # последний замер сезона — наибольший, до конца 4 сут
    assert row.pmax == pytest.approx(111.0)
    assert row.p_end == pytest.approx(111.0)                 # ближайший замер к концу закачки 29.06.2022
    assert row.fall == pytest.approx(0.0)
    assert row.last_mean == pytest.approx(100.0)
    assert row.last_share == pytest.approx(100.0)            # ровный темп: последний месяц = среднему за сезон
    assert 'наибольший замер' in row.basis


def test_decline_after_peak_and_warning_near_end():
    result = run()
    row = table(result).loc['2023']
    assert row.max_date == pd.Timestamp('2023-06-27') and row.pmax == pytest.approx(140.0)
    assert row.since_max == 2
    assert row.p_end == pytest.approx(135.0) and row.fall == pytest.approx(5.0)
    assert 'проверьте' in row.basis
    assert any('2023' in n.text and n.level == 'warning' for n in result.notes)


def test_manual_overrides_win_over_hints():
    manual = {'2023': {'start': '2023-05-01', 'end': '2023-06-28', 'max_date': '2023-06-10', 'last_from': '2023-06-01'}}
    row = table(run({'manual': manual})).loc['2023']
    assert row.end == pd.Timestamp('2023-06-28') and row.max_date == pd.Timestamp('2023-06-10')
    assert row.last_volume == pytest.approx(28 * 0.1, rel=1e-6)   # 1-28 июня, 100 тыс. м³/сут = 0,1 млн м³ на сутки
    assert 'граница: вручную' in row.basis and 'максимум: вручную' in row.basis and 'окно последнего месяца: вручную' in row.basis


def test_bad_manual_date_is_explained():
    with pytest.raises(ParamError, match='не распознана'):
        run({'manual': {'2023': {'end': 'не дата'}}})


def test_no_pressure_is_a_note_not_an_error():
    data = Data({PROD: production()})
    result = InjectionDeclineModule().run(data, {'seasons': 5, 'periods': [], 'source': 'auto', 'last_days': 30, 'tail_days': 45,
                                                 'manual': None})
    assert result.tables and any('Нет давления объекта' in n.text for n in result.notes)
    assert {c.id for c in result.charts} == {'decline-rate', 'decline-tail'}


def test_no_seasons_gives_note():
    result = run({'periods': ['нет такого']})
    assert not result.tables and result.notes
