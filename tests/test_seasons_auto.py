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
    out = production.periods(d, 11, 4, 3, 10.0)
    assert set(out[out.kind.eq('withdrawal')].period) == {'2022-2023', '2023-2024', 'Нейтральный период Весна 2023'}
    assert set(out[out.kind.eq('injection')].period) == {'2023'}
    assert out.loc[out.date.eq('2023-05-01'), 'period'].iloc[0] == 'Нейтральный период Весна 2023'


def test_explicit_season_and_year_win():
    d = _frame()
    d.loc[d.kind.eq('withdrawal') & d.date.lt('2023-01-01'), 'season'] = '2021–2022'
    d.loc[d.kind.eq('injection'), 'year'] = '2030'
    out = production.periods(d, 11, 4, 3, 10.0)
    assert '2021-2022' in set(out.period) and '2030' in set(out.period)
    assert '2022-2023' in set(out.period)       # строки без явного сезона (после 01.01.2023) определены по расходу


def test_off_by_default_matches_month_rule():
    d = _frame()
    a, b = production.periods_for(d, {}), production.periods(d, 11, 4)
    assert a.period.tolist() == b.period.tolist()
    assert production.period_rule({}) == (11, 4)
    assert production.period_rule({'auto_seasons': True}) == (11, 4, 3, 10.0, None)


def test_empty_and_zero_flow():
    z = pd.DataFrame({'well': ['1'], 'date': [pd.Timestamp('2023-01-01')], 'kind': ['withdrawal'], 'q': [0.0], 'season': [''], 'year': ['']})
    assert seasons.detect_runs(z.date, z.q) == []
    assert production.periods(z, 11, 4, 3, 10.0).period.iloc[0] == 'Нейтральный период Осень 2022'


def test_settings_validation():
    from atlas.projects import EDITABLE_SETTINGS as ok
    assert ok['auto_seasons'](True) and not ok['auto_seasons'](1)
    assert ok['season_gap_days'](3) and not ok['season_gap_days'](0) and not ok['season_gap_days'](True)
    assert ok['season_rate_share'](10) and not ok['season_rate_share'](0) and not ok['season_rate_share'](60)


def test_short_stop_inside_season_is_not_neutral_but_real_pause_is():
    rows = []
    for a, b in [('2023-11-01', '2024-01-10'), ('2024-01-15', '2024-03-31')]:      # остановка 4 сут: тот же вид вернулся устойчиво
        rows += [{'well': '1', 'date': d, 'kind': 'withdrawal', 'q': 100.0, 'season': '', 'year': ''} for d in pd.date_range(a, b)]
    d = pd.DataFrame(rows)
    assert len(seasons.detect_runs(d.date, d.q)) == 1
    out = production.periods(d, 11, 4, 3, 10.0)
    assert set(out.period) == {'2023-2024'}


def test_pause_with_injection_in_between_splits_season_and_neutral_names():
    rows = []
    for kind, a, b in [('withdrawal', '2023-11-01', '2024-01-10'), ('withdrawal', '2024-01-15', '2024-03-10'),
                       ('injection', '2024-03-12', '2024-06-30'), ('withdrawal', '2024-10-20', '2024-12-31')]:
        rows += [{'well': '1', 'date': d, 'kind': kind, 'q': 100.0, 'season': '', 'year': ''} for d in pd.date_range(a, b)]
    d = pd.DataFrame(rows)
    d = pd.concat([d, pd.DataFrame([{'well': '1', 'date': pd.Timestamp('2024-09-10'), 'kind': 'withdrawal', 'q': 0.2, 'season': '', 'year': ''},
                                    {'well': '1', 'date': pd.Timestamp('2024-01-12'), 'kind': 'withdrawal', 'q': 0.2, 'season': '', 'year': ''}])])
    out = production.periods(d, 11, 4, 3, 10.0)
    assert out.loc[out.date.eq('2024-09-10'), 'period'].iloc[0] == 'Нейтральный период Весна 2024'   # пауза началась 01.07
    assert out.loc[out.date.eq('2024-01-12'), 'period'].iloc[0] == '2023-2024'                         # короткая остановка внутри сезона
    assert set(out[out.kind.eq('injection')].period) == {'2024'}
    assert seasons.neutral_label(pd.Timestamp('2026-04-10')) == 'Нейтральный период Весна 2026'
    assert seasons.neutral_label(pd.Timestamp('2026-10-01')) == 'Нейтральный период Осень 2026'
    assert seasons.neutral_label(pd.Timestamp('2026-02-01')) == 'Нейтральный период Осень 2025'


def test_schedule_parse_and_labels():
    text = '28.06.2021 inj\n25.10.2021 none\n01.11.2021 prod\n# комментарий\n10.04.2022 none\n'
    schedule, peaks = seasons.parse_schedule(text + '10.01.2022 12.01.2022 peak\n')
    assert peaks == [('2022-01-10', '2022-01-12')]
    assert schedule[0] == ('2021-06-28', 'injection') and schedule[1] == ('2021-10-25', 'none')
    rows = [('injection', '2021-07-01'), ('injection', '2021-10-26'), ('withdrawal', '2021-12-01'),
            ('withdrawal', '2022-04-20'), ('withdrawal', '2021-05-01')]
    d = pd.DataFrame([{'well': '1', 'date': pd.Timestamp(x), 'kind': k, 'q': 1.0, 'season': 'Х', 'year': '1999'} for k, x in rows])
    out = production.periods(d, 11, 4, None, None, tuple(schedule)).period.tolist()
    assert out == ['2021', 'Нейтральный период Осень 2021', '2021-2022', 'Нейтральный период Весна 2022',
                   'Х']                          # до первой даты расписания — обычное правило (явный сезон)
    assert production.period_rule({'season_schedule': [list(x) for x in schedule]})[4] == tuple(schedule)


def test_schedule_errors_name_the_line():
    for bad, fragment in [('28.06.2021', 'Строка 1'), ('32.13.2021 inj', 'не распознана'), ('01.01.2021 xx', 'неизвестен'),
                          ('01.01.2021 inj\n01.01.2021 prod', 'повторяется'), ('\n\n', 'нет ни одной')]:
        try:
            seasons.parse_schedule(bad)
        except ValueError as e:
            assert fragment in str(e)
        else:
            raise AssertionError(bad)


def test_auto_peaks_inside_season():
    rows = []
    for date in pd.date_range('2023-11-01', '2024-03-31'):
        q = 100.0 * (4 if date in pd.date_range('2024-01-10', '2024-01-12') else 1)
        rows.append({'well': '1', 'date': date, 'kind': 'withdrawal', 'q': q, 'season': '', 'year': ''})
    d = pd.DataFrame(rows)
    assert seasons.detect_peaks(d) == [(pd.Timestamp('2024-01-10'), pd.Timestamp('2024-01-12'))]
    got = seasons.peaks_for(d, {'auto_peaks': True, 'peak_windows': [['2023-12-01', '2023-12-02']]})
    assert got[0] == (pd.Timestamp('2023-12-01'), pd.Timestamp('2023-12-02')) and len(got) == 2
    assert seasons.peaks_for(d, {}) == []


def test_peak_events_on_charts():
    from atlas.modules._events import regime_events
    d = production.periods(pd.DataFrame([{'well': '1', 'date': pd.Timestamp('2024-01-05'), 'kind': 'withdrawal', 'q': 1.0, 'season': '', 'year': ''}]), 11, 4)
    d.attrs['_atlas_peaks'] = [(pd.Timestamp('2024-01-10'), pd.Timestamp('2024-01-12'))]
    events = [e for e in regime_events(d) if e.kind == 'peak']
    assert len(events) == 1 and events[0].label == 'Пик · 10.01.2024–12.01.2024'
