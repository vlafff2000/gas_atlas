"""«Анализ скважин для включения в программу ГДИ»: признаки, причины и ручное решение инженера."""
import pandas as pd
import pytest

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules.gdi_due import GdiDueModule, STATE_ADDED, STATE_AUTO, STATE_REMOVED, apply_manual, build, relative_drop, season_flows

P = DatasetKind.PRODUCTION
PARAMS = {'years': 5.0, 'gap': 15.0, 'threshold': 0.95, 'change': 10.0, 'kru_priority': 2, 'add': [], 'remove': [],
          'today': '2026-10-31'}


def production():
    rows = []
    # две скважины одной группы стабильны (−0%), третья упала на 40%, четвёртая — в другой группе без второго сезона
    for w, prev, last in (('1', 100, 100), ('2', 100, 100), ('3', 100, 60)):
        for period, q, start in (('2024-2025', prev, '2024-11-01'), ('2025-2026', last, '2025-11-01')):
            for d in pd.date_range(start, periods=10):
                rows.append(dict(well=w, date=d, q=q * 1e3, kind='withdrawal', period=period))
    for d in pd.date_range('2025-11-01', periods=10):
        rows.append(dict(well='4', date=d, q=50e3, kind='withdrawal', period='2025-2026'))
    return pd.DataFrame(rows)


def gdi(well, year, scale=1.0):
    rows = []
    for q in (45., 90., 140., 190.):
        dp2 = (0.7 * q + 0.012 * q * q) * scale
        rows.append(dict(well=well, date=pd.Timestamp(f'{year}-12-10'), q=q, p_res=75., p_bh=(75. ** 2 - dp2) ** .5, dp2=dp2,
                         a_db=0.7, b_db=0.012, method='Установившиеся отборы', study='', season=f'{year}-{year + 1}', group='ГСП-1'))
    return rows


def data(with_gdi=True, kru=None):
    frames = {P: production()}
    frames[DatasetKind.GDI] = pd.DataFrame(gdi('1', 2024) + gdi('2', 2018) + gdi('3', 2025)) if with_gdi else pd.DataFrame()
    if kru is not None:
        frames[DatasetKind.KRS_PRIORITY] = kru
    d = Data(frames)
    d.mapping = {'1': {'group': 'ГСП-1'}, '2': {'group': 'ГСП-1'}, '3': {'group': 'ГСП-1'}, '4': {'group': 'ГСП-2'}}
    d.wells = ['1', '2', '3', '4']
    return d


def test_flows_use_withdrawal_seasons_only_and_group_median():
    flows = relative_drop(season_flows(production()), {'1': 'A', '2': 'A', '3': 'A', '4': 'B'})
    row = flows.set_index('well')
    assert row.at['3', 'change'] == pytest.approx(-40)
    assert row.at['3', 'gap'] == pytest.approx(-40)           # медиана группы 0%
    assert pd.isna(row.at['4', 'change'])                     # нет предыдущего сезона — не нуль, а пропуск


def test_flags_and_reasons():
    t = build(data(), PARAMS).set_index('well')
    assert bool(t.at['2', 'f_age']) and 'лет назад' in t.at['2', 'reason']            # ГДИ 2018 года
    assert not t.at['1', 'f_age'] and t.at['1', 'score'] == 0                          # ГДИ 2024, расход стабилен
    assert bool(t.at['3', 'f_flow']) and 'упал на 40%' in t.at['3', 'reason']
    assert bool(t.at['4', 'f_age']) and t.at['4', 'reason'] == 'надёжного ГДИ нет'     # исследований нет


def test_priority_flag_follows_param():
    kru = pd.DataFrame({'well': ['1'], 'priority': [1.]})
    assert bool(build(data(kru=kru), PARAMS).set_index('well').at['1', 'f_kru'])
    off = {**PARAMS, 'kru_priority': -1}
    assert not build(data(kru=kru), off).f_kru.any()


def test_manual_decision_beats_calculation():
    t = apply_manual(build(data(), PARAMS), add=['1'], remove=['2']).set_index('well')
    assert t.at['1', 'in_list'] and t.at['1', 'state'] == STATE_ADDED
    assert not t.at['2', 'in_list'] and t.at['2', 'state'] == STATE_REMOVED
    assert 'лет назад' in t.at['2', 'reason']                       # расчёт остаётся виден
    assert t.at['3', 'state'] == STATE_AUTO and t.at['3', 'in_list']


def test_module_runs_and_empty_project_is_a_note():
    result = GdiDueModule().run(data(), PARAMS)
    table = next(t for t in result.tables if t.id == 'gdi-due').frame
    assert table.well.tolist()[0] in {'2', '3', '4'} and len(table) == 4
    empty = GdiDueModule().run(Data({}), PARAMS)
    assert not empty.tables and empty.notes


def seasonal(decline_well='3', days=60):
    """Два сезона по 60 суток; в последнем расход объекта растёт, у скважины decline_well падает; КРУ растёт у всех."""
    prod, elpro = [], []
    for w in ('1', '2', '3', '4'):
        for period, start, k in (('2024-2025', '2024-11-01', 0), ('2025-2026', '2025-11-01', 1)):
            for i, d in enumerate(pd.date_range(start, periods=days)):
                trend = (-0.5 if w == decline_well else 0.5) * i / days if k else 0.0
                q, y = (100 * (1 + trend)) * 1e3, 40 + 20 * k
                prod.append(dict(well=w, date=d, q=q, kind='withdrawal', period=period))
                elpro.append(dict(well=w, date=d, q=q / 1e3, y=y, p=80 - 10 * k, kind='withdrawal'))
    d = Data({P: pd.DataFrame(prod), DatasetKind.ELPRO: pd.DataFrame(elpro)})
    d.mapping = {w: {'group': 'ГСП-1'} for w in '1234'}
    d.wells = list('1234')
    return d


def test_cumulative_dynamics_and_kru_flags():
    t = build(seasonal(), PARAMS).set_index('well')
    assert t.at['3', 'cum_days'] == 60
    assert t.at['3', 'cum_change'] < 0 < t.at['1', 'cum_change']                  # падает против растущих
    assert bool(t.at['3', 'f_cum']) and not bool(t.at['1', 'f_cum'])
    assert t.at['3', 'slope_well'] < 0 < t.at['3', 'slope_obj'] + 20               # тренд скважины хуже объекта
    assert t.at['3', 'sync_obj'] < 50 and bool(t.at['3', 'f_sync']) and 'не совпадает' in t.at['3', 'reason']
    assert t.at['1', 'sync_obj'] > 50 and not bool(t.at['1', 'f_sync'])
    assert t.at['3', 'open_change'] == pytest.approx(50)                          # раскрытие 40 → 60%
    assert bool(t.at['3', 'f_open']) and not bool(t.at['1', 'f_open'])            # раскрыли больше, а расход упал


def test_without_elpro_kru_metrics_are_gaps_not_flags():
    t = build(_no_elpro(seasonal()), PARAMS)
    assert not t.f_open.any() and t.open_change.isna().all()


def _no_elpro(d):
    n = Data({P: d[P]})
    n.mapping, n.wells = d.mapping, d.wells
    return n


def test_interval_marks_only_declining_well_and_charts_are_built():
    from atlas.modules._gdi_due_metrics import last_two, productivity_intervals, withdrawal_days
    d = seasonal(days=120)
    days = withdrawal_days(d[P])
    iv = productivity_intervals(days, last_two(days)[0], d[DatasetKind.ELPRO])
    assert iv.well.unique().tolist() == ['3'] and (iv.days >= 14).all() and (iv.depth > 15).all()
    t = build(d, PARAMS).set_index('well')
    assert bool(t.at['3', 'f_int']) and 'интервал снижения продуктивности' in t.at['3', 'reason'] and not bool(t.at['1', 'f_int'])
    charts = GdiDueModule().run(d, {**PARAMS, 'show': ['3', '1']}).charts
    by = {c.id: c for c in charts}
    assert set(by) == {'gdi-due-1', 'gdi-due-3'}
    assert by['gdi-due-3'].style['annotations'][0]['kind'] == 'vband' and not by['gdi-due-1'].style
    assert [by['gdi-due-3'].y2.label, by['gdi-due-3'].y3.label, by['gdi-due-3'].y4.label, by['gdi-due-3'].y5.label] == [
        'Расход группы', 'Расход объекта', 'Давление (ЭЛПРО)', 'Раскрытие КРУ']      # каждый ряд на своей шкале
    assert not any('Накопленный' in x.name for x in by['gdi-due-3'].series)


def test_kru_cut_explains_the_drop():
    from atlas.modules._gdi_due_metrics import last_two, productivity_intervals, withdrawal_days
    d = seasonal()
    e = d[DatasetKind.ELPRO]
    e.loc[e.well.eq('3') & e.date.ge('2025-12-01'), 'y'] = 20.0          # раскрытие уменьшили вдвое: падение расхода — режим
    days = withdrawal_days(d[P])
    assert productivity_intervals(days, last_two(days)[0], e).empty


def test_no_gdi_five_years_table_uses_all_studies_and_calculated_ab():
    result = GdiDueModule().run(data(), PARAMS)
    t = next(x for x in result.tables if x.id == 'gdi-no-5y').frame.set_index('well')
    assert set(t.index[t.in_table]) == {'2', '4'}                       # ГДИ 2018 года и исследований нет вообще
    assert t.at['2', 'years_any'] > 5 and pd.isna(t.at['4', 'last_any']) and t.at['4', 'n_all'] == 0
    assert t.at['2', 'a_calc'] == pytest.approx(0.7, rel=0.05) and t.at['2', 'b_calc'] == pytest.approx(0.012, rel=0.05)   # расчёт по точкам
    detail = next(x for x in result.tables if x.id == 'gdi-no-5y-studies').frame
    assert set(detail.well) == {'2'}


def test_manual_decision_applies_to_new_tables():
    result = GdiDueModule().run(data(), {**PARAMS, 'add': ['1'], 'remove': ['2']})
    t = next(x for x in result.tables if x.id == 'gdi-no-5y').frame.set_index('well')
    assert t.at['1', 'state'] == STATE_ADDED and t.at['2', 'state'] == STATE_REMOVED and not t.at['2', 'in_table']
    assert t.index.tolist().index('2') > t.index.tolist().index('4')   # убранная внизу


def test_productivity_table_signals():
    result = GdiDueModule().run(seasonal(), PARAMS)
    t = next(x for x in result.tables if x.id == 'gdi-productivity').frame.set_index('well')
    assert t.index[t.in_table].tolist() == ['3'] and t.at['3', 'signals'] >= 2


def test_kru_response_uses_production_flow_not_elpro_flow():
    d = seasonal()
    base = build(d, PARAMS).set_index('well')
    d[DatasetKind.ELPRO]['q'] = 1.0                              # расход в ЭЛПРО испорчен: на результат влиять не должен
    t = build(d, PARAMS).set_index('well')
    assert t.at['3', 'eff_change'] == pytest.approx(base.at['3', 'eff_change']) and bool(t.at['3', 'f_open'])


def test_curves_are_real_daily_flows_and_x_axis_can_be_object_cumulative():
    from atlas.modules._gdi_due_metrics import last_two, well_curves, withdrawal_days
    d = seasonal()
    days = withdrawal_days(d[P])
    c = well_curves(days, last_two(days)[0], d[DatasetKind.ELPRO], {w: 'ГСП-1' for w in '1234'}, '3')
    first = c.iloc[0]
    assert first.q == pytest.approx(100.0, rel=0.01)     # настоящий суточный расход, тыс. м³/сут
    assert first.obj_q == pytest.approx(first.grp_q) == pytest.approx(400.0, rel=0.01)                  # сумма по четырём скважинам, не индекс
    assert c.cum_obj.iloc[-1] == pytest.approx(c.obj_q.sum() / 1e3)                                       # накопленный отбор объекта, млн м³
    by = {x.id: x for x in GdiDueModule().run(d, {**PARAMS, 'show': ['3'], 'xaxis': 'cumulative'}).charts}['gdi-due-3']
    assert by.x.unit == 'млн м³' and by.x.scale == 'value' and float(by.style['annotations'][0]['value']) > 0


def _season(tail_drop=False, start_shift=0, days=120, hours=True):
    """4 ровные скважины; у скважины 3 — либо провал только в последние 10 суток (закрытие), либо поздний старт."""
    prod, elpro = [], []
    for w in '1234':
        for i, d in enumerate(pd.date_range('2025-11-01', periods=days)):
            if w == '3' and i < start_shift:
                continue
            q = 100.0
            if w == '3' and tail_drop and i >= days - 10:
                q = 40.0
            if w == '3' and start_shift and i < start_shift + 7:
                q = 30.0                                             # выход на режим после позднего старта
            prod.append(dict(well=w, date=d, q=q * 1e3, kind='withdrawal', period='2025-2026', hours=24.0 if hours else float('nan')))
            elpro.append(dict(well=w, date=d, q=q, y=50.0, p=80.0, kind='withdrawal'))
    d = Data({P: pd.DataFrame(prod), DatasetKind.ELPRO: pd.DataFrame(elpro)})
    d.mapping = {w: {'group': 'ГСП-1'} for w in '1234'}
    d.wells = list('1234')
    return d


def test_tail_of_season_and_late_start_are_not_decline():
    from atlas.modules._gdi_due_metrics import last_two, productivity_intervals, withdrawal_days, work_starts
    for kw in ({'tail_drop': True}, {'start_shift': 40}):
        d = _season(**kw)
        days = withdrawal_days(d[P])
        last = last_two(days)[0]
        assert productivity_intervals(days, last, d[DatasetKind.ELPRO], tail_days=0, ramp_days=0).shape[0] >= 0   # без защит интервал может появиться
        assert productivity_intervals(days, last, d[DatasetKind.ELPRO]).empty, kw
    days = withdrawal_days(_season(start_shift=40)[P])
    assert work_starts(days, '2025-2026')['3'] == pd.Timestamp('2025-11-01') + pd.Timedelta(days=40)


def test_interval_without_kru_data_is_shown_but_not_a_sign():
    d = _season()
    p = d[P]
    p.loc[p.well.eq('3') & p.date.ge('2026-01-01') & p.date.lt('2026-02-20'), 'q'] = 50e3          # устойчивое падение на 50 суток
    nd = _no_elpro(d)
    t = build(nd, PARAMS).set_index('well')
    assert not bool(t.at['3', 'f_int']) and 'не подтверждён' in t.at['3', 'reason']
    t = build(nd, {**PARAMS, 'need_open': 0}).set_index('well')
    assert bool(t.at['3', 'f_int'])


def test_cumulative_counts_from_well_start_not_season_start():
    from atlas.modules._gdi_due_metrics import cumulative, last_two, withdrawal_days
    rows = []
    for period, start in (('2024-2025', '2024-11-01'), ('2025-2026', '2025-11-01')):
        for w, shift in (('1', 0), ('3', 40 if period == '2025-2026' else 0)):
            for d in pd.date_range(pd.Timestamp(start) + pd.Timedelta(days=shift), periods=100 - shift):
                rows.append(dict(well=w, date=d, q=100e3, kind='withdrawal', period=period, hours=24.0))
    days = withdrawal_days(pd.DataFrame(rows))
    last, prev = last_two(days)
    c = cumulative(days, last, prev, {'1': 'A', '3': 'A'}).set_index('well')
    assert c.at['1', 'cum_days'] == 100 and c.at['3', 'cum_days'] == 60
    assert c.at['3', 'cum_change'] == pytest.approx(0)          # поздний старт — не снижение отбора
