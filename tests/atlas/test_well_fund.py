"""Фонд скважин по сезонам: расход, форма кривой, раскрытие КРУ, фон группы и объекта, ГДИ по сезонам."""
import numpy as np
import pytest
import pandas as pd

from atlas.engine.modules import well_fund as fund


def daily_frame(rows):
    """rows: (well, date, period, group, gas_m3); объект и группа — суммы по суткам, как в well_analysis."""
    d = pd.DataFrame(rows, columns=['well', 'date', 'period', 'group', 'gas_volume_m3'])
    d['date'] = pd.to_datetime(d.date)
    d['object_volume'] = d.groupby('date').gas_volume_m3.transform(lambda v: v.sum(min_count=1))
    d['group_volume'] = d.groupby(['group', 'date']).gas_volume_m3.transform(lambda v: v.sum(min_count=1))
    return d


def season_rows(well, period, start, days, rate, group='ГСП-1'):
    return [(well, pd.Timestamp(start) + pd.Timedelta(days=int(i)), period, group, rate(i) * 1000) for i in range(days)]


def test_mean_rate_skips_missing_and_zero_days_as_idle():
    rows = season_rows('1', '2023/2024', '2023-11-01', 20, lambda i: 100.0)
    rows[0] = ('1', rows[0][1], '2023/2024', 'ГСП-1', np.nan)     # нет записи — не ноль
    rows[1] = ('1', rows[1][1], '2023/2024', 'ГСП-1', 0.0)         # простой — ноль, в работающие не входит
    d = daily_frame(rows)
    out = fund.seasonal(d, ['2023/2024'])
    r = out.iloc[0]
    assert r.gas_days == 19 and r.working_days == 18
    assert r.mean_rate == 100.0
    assert np.isnan(r.kru_mean) and r.kru_days == 0


def test_kru_high_rate_and_correlation_from_elpro():
    rows = season_rows('1', '2023/2024', '2023-11-01', 20, lambda i: 100.0 + 2 * i)
    d = daily_frame(rows)
    elpro = pd.DataFrame({'well': '1', 'date': d.date, 'y': np.where(np.arange(20) < 10, 20.0, 80.0)})
    out = fund.seasonal(d, ['2023/2024'], elpro=elpro, high_kru=50)
    r = out.iloc[0]
    assert r.kru_days == 20 and r.high_days == 10
    assert r.rate_high == np.mean([100.0 + 2 * i for i in range(10, 20)])
    assert r.kru_corr > 0.8                      # КРУ и расход растут вместе (ранговая связь)
    assert r['shape'] == 'растёт'


def test_compare_with_previous_season_and_background():
    s1 = season_rows('1', 'A', '2023-11-01', 30, lambda i: 100.0, 'ГСП-1') + season_rows('2', 'A', '2023-11-01', 30, lambda i: 100.0, 'ГСП-1')
    s2 = season_rows('1', 'B', '2024-11-01', 30, lambda i: 60.0, 'ГСП-1') + season_rows('2', 'B', '2024-11-01', 30, lambda i: 60.0, 'ГСП-1')
    d = daily_frame(s1 + s2)
    out = fund.seasonal(d, ['A', 'B'])
    row = out[(out.well == '1') & (out.period == 'B')].iloc[0]
    assert row.prev_period == 'A'
    assert round(row.d_rate, 6) == -40.0
    assert round(row.d_group, 6) == -40.0        # группа упала так же: падение скважины объяснимо фоном
    assert round(row.d_object, 6) == -40.0


def test_season_without_records_stays_in_grid_and_previous_is_last_worked():
    d = daily_frame(season_rows('1', 'A', '2023-11-01', 30, lambda i: 100.0)
                    + season_rows('1', 'C', '2025-11-01', 30, lambda i: 50.0))
    out = fund.seasonal(d, ['A', 'B', 'C'])
    assert list(out.period) == ['A', 'B', 'C']
    b = out[out.period == 'B'].iloc[0]
    assert b.gas_days == 0 and np.isnan(b.mean_rate)
    c = out[out.period == 'C'].iloc[0]
    assert c.prev_period == 'A' and round(c.d_rate, 6) == -50.0


def test_gdi_median_by_season_uses_reliable_studies_only():
    d = daily_frame(season_rows('1', 'A', '2023-11-01', 30, lambda i: 100.0))
    gdi = pd.DataFrame({'well': ['1', '1', '1'], 'date': pd.to_datetime(['2023-11-05', '2023-11-10', '2023-11-15']),
                        'reliable': [True, True, False], 'q_reference': [100.0, 120.0, 500.0]})
    out = fund.seasonal(d, ['A'], gdi=gdi)
    assert out.iloc[0].gdi_q == 110.0 and out.iloc[0].gdi_studies == 2


def test_empty_inputs_return_empty_frame_with_columns():
    out = fund.seasonal(pd.DataFrame(), [])
    assert out.empty and list(out.columns) == fund.COLUMNS


def test_fund_section_through_api(tmp_path):
    from starlette.testclient import TestClient

    from _wells_data import make_project, well_frames
    from atlas.api import create_app
    from atlas.modules.wells import SECTION_FUND
    from atlas.projects import Projects

    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    frames = well_frames()
    prod = frames['production']
    prod = prod[prod.kind.eq('withdrawal') & prod.well.isin(['31', '45'])]
    rng = np.random.default_rng(3)
    elpro = pd.DataFrame({'well': prod.well.astype(str).to_numpy(), 'date': prod.date.to_numpy(),
                          'kind': 'withdrawal', 'q': prod.q.to_numpy() / 1000, 'p': 50.0, 't': 20.0,
                          'y': rng.uniform(20, 90, len(prod)).round(1), 'group': 'ГСП-1'})
    projects.store.commit(pid, frames={**frames, 'elpro': elpro}, action='Тест фонда по сезонам')
    r = client.post('/api/modules/wells/run', json={'project': pid, 'params': {'section': SECTION_FUND, 'seasons_n': 2,
                                                                                'wells': ['31']}})
    assert r.status_code == 200, r.text
    body = r.json()
    table = next(t for t in body['tables'] if t['id'] == 'fund-seasons')
    wells = set(table['rows'][0])                           # первый столбец — скважина
    assert len(table['rows'][0]) == 2 * len(wells)          # все скважины × два сезона, пустой сезон — строкой
    chart_ids = {c['id'] for c in body['charts']}
    assert {'fund-daily-31', 'fund-seasons-31'} <= chart_ids
    assert any(t['id'] == 'fund-studies-31' for t in body['tables']) or 'Нет ГДИ в выбранных сезонах.' in str(body['notes'])
    assert not any('ЭЛПРО' in n['text'] for n in body['notes'])


def test_daily_series_zero_for_missing_day_and_gap_for_missing_kru():
    rows = season_rows('1', 'A', '2023-11-01', 5, lambda i: 100.0)
    rows.append(('2', pd.Timestamp('2023-11-03'), 'A', 'ГСП-1', 50.0 * 1000))   # у скважины 1 нет записи 3 ноября
    rows = [r for r in rows if not (r[0] == '1' and r[1] == pd.Timestamp('2023-11-03'))]
    d = daily_frame(rows)
    elpro = pd.DataFrame({'well': '1', 'date': pd.to_datetime(['2023-11-01', '2023-11-02']), 'y': [30.0, 150.0]})
    s = fund.daily_series(d, elpro, '1', ['A'])
    assert list(s.rate) == [100.0, 100.0, 0.0, 100.0, 100.0]     # без записи — 0, не пропуск
    assert list(s.kru.iloc[:2]) == [30.0, 100.0]                  # КРУ ограничен 0–100, без записи — пропуск
    assert s.kru.iloc[2:].isna().all()


def test_studies_assigned_to_season_by_object_dates():
    d = daily_frame(season_rows('1', 'A', '2023-11-01', 30, lambda i: 100.0)
                    + season_rows('1', 'B', '2024-11-01', 30, lambda i: 100.0))
    hist = pd.DataFrame({'well': ['1', '1'], 'date': pd.to_datetime(['2023-11-10', '2024-11-10']), 'method': 'м1',
                         'study': ['s1', 's2'], 'a': 0.5, 'b': 0.01, 'r2': 0.99, 'distinct_q': 4,
                         'reliable': [True, False], 'reference_dp2': 500.0, 'q_reference': [100.0, np.nan],
                         'q_free': [120.0, 130.0]})
    out = fund.studies_by_season(hist, d, ['A', 'B'])
    assert list(out.period) == ['A', 'B'] and list(out.study) == ['s1', 's2']


def _table(rows):
    """rows: (well, period, prev, mean_rate, rate_high, d_rate, d_high, d_group, d_object) — строка таблицы фонда."""
    cols = ['well', 'period', 'prev_period', 'mean_rate', 'rate_high', 'd_rate', 'd_high', 'd_group', 'd_object', 'group']
    frame = pd.DataFrame([(w, p, pv, m, h, dr, dh, dg, do, 'ГСП-1') for w, p, pv, m, h, dr, dh, dg, do in rows], columns=cols)
    return frame


def test_classify_improvement_stable_and_degradation_kinds():
    t = _table([
        ('1', 'A', None, 100.0, 100.0, np.nan, np.nan, np.nan, np.nan),
        ('1', 'B', 'A', 130.0, 130.0, 30.0, 30.0, 0.0, 0.0),                 # улучшение
        ('2', 'A', None, 100.0, 100.0, np.nan, np.nan, np.nan, np.nan),
        ('2', 'B', 'A', 102.0, 102.0, 2.0, 2.0, 0.0, 0.0),                   # стабильно
        ('3', 'A', None, 100.0, 100.0, np.nan, np.nan, np.nan, np.nan),
        ('3', 'B', 'A', 60.0, 60.0, -40.0, -40.0, -38.0, -30.0),             # падение почти как фон группы
        ('4', 'A', None, 100.0, 100.0, np.nan, np.nan, np.nan, np.nan),
        ('4', 'B', 'A', 60.0, 60.0, -40.0, -40.0, -5.0, -3.0),               # фон не падал — техсостояние
        ('5', 'A', None, 100.0, np.nan, np.nan, np.nan, np.nan, np.nan),
        ('5', 'B', None, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan),    # нет работы — не в сравнении
    ])
    out = fund.classify(t, threshold=10, ratio=1.5).set_index('well')
    assert out.loc['1', 'category'] == 'Улучшение'
    assert out.loc['2', 'category'] == 'Стабильно'
    assert out.loc['3', 'category'] == 'Ухудшение' and 'фоном' in out.loc['3', 'note']
    assert out.loc['4', 'category'] == 'Ухудшение' and 'техсостояние' in out.loc['4', 'note']
    assert out.loc['1', 'metric'] == 'Расход при высоком КРУ'


def test_classify_uses_mean_rate_without_kru_and_flags_missing_comparison():
    t = _table([
        ('1', 'A', None, 100.0, np.nan, np.nan, np.nan, np.nan, np.nan),
        ('1', 'B', 'A', 80.0, np.nan, -20.0, np.nan, np.nan, np.nan),
        ('2', 'B', None, 80.0, np.nan, np.nan, np.nan, np.nan, np.nan),
    ])
    out = fund.classify(t).set_index('well')
    assert out.loc['1', 'metric'] == 'Средний расход' and out.loc['1', 'category'] == 'Ухудшение'
    assert 'фон' in out.loc['1', 'note'].lower()
    assert out.loc['2', 'category'] == 'Нет сравнения'


def test_well_category_overrides_are_validated_and_removed_when_empty():
    from atlas.contract import ParamError
    from atlas.modules.wells import WELL_CATEGORIES_KEY, with_well_categories

    s = with_well_categories({}, {'31': {'category': 'Ухудшение'}, '45': 'Стабильно'})
    assert s[WELL_CATEGORIES_KEY] == {'31': {'category': 'Ухудшение'}, '45': {'category': 'Стабильно'}}
    s = with_well_categories(s, {'31': {'category': ''}})
    assert s[WELL_CATEGORIES_KEY] == {'45': {'category': 'Стабильно'}}
    with pytest.raises(ParamError):
        with_well_categories(s, {'31': {'category': 'Нет сравнения'}})
    with pytest.raises(ParamError):
        with_well_categories(s, {})


def test_engineer_category_overrides_hint_through_api(tmp_path):
    from starlette.testclient import TestClient

    from _wells_data import make_project
    from atlas.api import create_app
    from atlas.modules.wells import CATEGORY_LABELS, SECTION_FUND
    from atlas.projects import Projects

    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    params = {'section': SECTION_FUND, 'seasons_n': 2, 'wells': ['31']}
    r = client.post(f'/api/projects/{pid}/well-categories', json={'changes': {'31': {'category': 'Ухудшение'}}})
    assert r.status_code == 200, r.text
    body = client.post('/api/modules/wells/run', json={'project': pid, 'params': params}).json()
    table = next(t for t in body['tables'] if t['id'] == 'fund-categories')
    keys = [c['key'] for c in table['columns']]
    cells = dict(zip(table['rows'][keys.index('Скважина')], table['rows'][keys.index(CATEGORY_LABELS['category'][0])]))
    assert cells['31'] == 'Ухудшение'                       # ручная правка перекрывает подсказку
    assert table['action']['target'] == 'well-categories'
