"""Автоопределение сезонов по накопленному расходу: нейтральные периоды, явные «Сезон»/«Год», паритет без включения."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.modules import production, seasons


def _frame(with_season=False):
    rows = []
    # отбор 10.11.2022–05.03.2023 и 20.11.2023–15.04.2024; закачка 01.06–30.09.2023; нейтраль между ними
    spans = [('withdrawal', '2022-11-10', '2023-03-05'), ('injection', '2023-06-01', '2023-09-30'),
             ('withdrawal', '2023-11-20', '2024-04-15')]
    for kind, a, b in spans:
        for date in pd.date_range(a, b):
            for well in ('1', '2'):
                rows.append({'well': well, 'date': date, 'kind': kind, 'q': 100.0, 'season': '', 'year': ''})
    d = pd.DataFrame(rows)
    d.loc[d.date.eq('2023-01-10') & d.well.eq('1'), 'q'] = 0       # единичный нуль не рвёт сезон
    return d


def test_runs_follow_cumulative_growth_and_skip_neutral_gap():
    d = _frame()
    w = d[d.kind.eq('withdrawal')]
    runs = seasons.detect_runs(w.date, w.q)
    assert runs == [(pd.Timestamp('2022-11-10'), pd.Timestamp('2023-03-05')),
                    (pd.Timestamp('2023-11-20'), pd.Timestamp('2024-04-15'))]
    inj = seasons.detect_runs(d[d.kind.eq('injection')].date, d[d.kind.eq('injection')].q)
    assert inj == [(pd.Timestamp('2023-06-01'), pd.Timestamp('2023-09-30'))]


def test_labels_and_neutral_rows():
    d = _frame()
    d.loc[len(d)] = {'well': '1', 'date': pd.Timestamp('2023-05-01'), 'kind': 'withdrawal', 'q': 0.5, 'season': '', 'year': ''}
    out = production.periods(d, 11, 4, 14, 10.0)
    assert set(out[out.kind.eq('withdrawal')].period) == {'2022-2023', '2023-2024', 'Вне сезона 2023'}
    assert set(out[out.kind.eq('injection')].period) == {'2023'}
    assert out.loc[out.date.eq('2023-05-01'), 'period'].iloc[0] == 'Вне сезона 2023'


def test_explicit_season_and_year_win():
    d = _frame()
    d.loc[d.kind.eq('withdrawal') & d.date.lt('2023-01-01'), 'season'] = '2021–2022'
    d.loc[d.kind.eq('injection'), 'year'] = '2030'
    out = production.periods(d, 11, 4, 14, 10.0)
    assert '2021-2022' in set(out.period) and '2030' in set(out.period)
    assert '2022-2023' in set(out.period)       # строки без явного сезона (после 01.01.2023) определены по расходу


def test_off_by_default_matches_month_rule():
    d = _frame()
    a, b = production.periods_for(d, {}), production.periods(d, 11, 4)
    assert a.period.tolist() == b.period.tolist()
    assert production.period_rule({}) == (11, 4)
    assert production.period_rule({'auto_seasons': True}) == (11, 4, 14, 10.0)


def test_empty_and_zero_flow():
    z = pd.DataFrame({'well': ['1'], 'date': [pd.Timestamp('2023-01-01')], 'kind': ['withdrawal'], 'q': [0.0], 'season': [''], 'year': ['']})
    assert seasons.detect_runs(z.date, z.q) == []
    assert production.periods(z, 11, 4, 14, 10.0).period.iloc[0] == 'Вне сезона 2023'


def test_settings_validation():
    from atlas.projects import EDITABLE_SETTINGS as ok
    assert ok['auto_seasons'](True) and not ok['auto_seasons'](1)
    assert ok['season_gap_days'](14) and not ok['season_gap_days'](0) and not ok['season_gap_days'](True)
    assert ok['season_rate_share'](10) and not ok['season_rate_share'](0) and not ok['season_rate_share'](60)
