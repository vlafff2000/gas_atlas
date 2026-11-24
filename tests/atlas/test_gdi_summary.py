"""Справка ГДИ по сезону и ремонтам: вердикты, категории (КРС, перерыв, ручная правка), разбор ремонтов года."""
import numpy as np
import pandas as pd
import pytest

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules.gdi_summary import (GdiSummaryModule, NO_AFTER, parse_manual, repair_class, repair_year_table, repairs,
                                       season_table, study_rows)

G, W = DatasetKind.GDI, DatasetKind.KRS_WORKS
PARAMS = {'seasons': ['2025-2026'], 'threshold': 0.95, 'change': 5.0, 'years': 5.0, 'repair_year': 0, 'manual': ''}


def gdi(well, date, scale=1.0, season=None):
    rows = []
    for q in (45., 90., 140., 190.):
        dp2 = (0.7 * q + 0.012 * q * q) * scale
        rows.append(dict(well=well, date=pd.Timestamp(date), q=q, p_res=75., p_bh=(75. ** 2 - dp2) ** .5, dp2=dp2,
                         a_db=0.7, b_db=0.012, method='Установившиеся отборы', study='',
                         season=season or f'{pd.Timestamp(date).year}-{pd.Timestamp(date).year + 1}', group='ГСП-1'))
    return rows


def frames():
    g = (gdi('1', '2024-12-10') + gdi('1', '2025-12-10', 0.7)              # скв. 1: ΔP² ниже при том же Q → улучшение, после КРС
         + gdi('2', '2024-12-10') + gdi('2', '2025-12-10', 1.4)            # скв. 2: ухудшение, ремонта нет
         + gdi('3', '2017-12-10') + gdi('3', '2025-12-10', 1.0)            # скв. 3: без изменений, перерыв 8 лет
         + gdi('4', '2025-12-10'))                                         # скв. 4: исследований до сезона нет
    works = pd.DataFrame([dict(well='1', year=2025, work_type='Замена фильтра', detail=''),
                          dict(well='5', year=2025, work_type='Колтюбинг без СКО', detail=''),
                          dict(well='6', year=2025, work_type='Колтюбинг с СКО / СКО', detail='')])
    g += gdi('5', '2025-03-01') + gdi('6', '2025-03-01') + gdi('6', '2025-10-01', 0.8)    # 5: после ремонта ГДИ нет; 6: ремонт 01.07 → ГДИ после
    return pd.DataFrame(g), works


def test_repair_class():
    assert repair_class('Замена фильтра') == 'замена фильтра'
    assert repair_class('Колтюбинг без СКО') == 'промывка / СКО'
    assert repair_class('Армирование ПЗП') == 'армирование ПЗП'
    assert repair_class('') == 'прочее'
    assert repair_class('Восстановление герметичности цементного кольца') == 'восстановление герметичности ЦК / изоляция'
    assert repair_class('КР 4.033-ЗР Кислотная обработка под давлением') == 'промывка / СКО'
    assert repair_class('Тип не определён', 'Описание работ: ремонт эксплуатационной колонны, смятие') == 'ремонт колонны'
    assert repair_class('Тип не определён', 'ИС 3.6.3 диагностика') == 'прочее'          # неизвестный вид не пропадает, но и не угадывается


def test_repairs_read_every_kind_from_sprav_and_table():
    """Справка КРС: выполненный ремонт, которого нет в таблице ремонтов (герметичность ЦК), и второй ремонт того же года не теряются."""
    works = pd.DataFrame([dict(well='1', year=2025, work_type='Замена фильтра', detail='Коды работ: КР 1.094 ПА')])
    plan = pd.DataFrame({'well': ['1', '1', '2', '3', '4'], 'year': [2025, 2025, 2025, 2025, 2025], 'kind': ['КР'] * 5,
                         'works': ['КР 1.094-ПА Замена фильтра', 'Ремонтно-изоляционные работы, восстановление герметичности цементного кольца',
                                   'КР 4.033-ЗР Кислотная обработка', 'ИС 3.6.3 диагностика', 'КР 1.094 Замена фильтра'],
                         'codes': ['КР 1.094', 'КР 3.099', 'КР 4.033', 'ИС 3.6.3', 'КР 1.094'],
                         'state': ['Выполнено', 'Выполнено', 'Выполнено', 'Выполнено', 'Не начато'], 'in_table': ['Да'] * 5,
                         'start': pd.to_datetime(['2025-06-01', '2025-09-01', '2025-07-01', '2025-08-01', '2025-08-01']),
                         'end': pd.to_datetime(['2025-06-20', '2025-09-15', '2025-07-10', '2025-08-09', pd.NaT]), 'source': [''] * 5})
    r = repairs(works, plan)
    got = {(x.well, x.kind) for x in r.itertuples()}
    assert got == {('1', 'замена фильтра'), ('1', 'восстановление герметичности ЦК / изоляция'), ('2', 'промывка / СКО'), ('3', 'прочее')}      # 4 — не выполнен
    assert r[r.well.eq('1') & r.kind.str.startswith('восст')].iloc[0].date == pd.Timestamp('2025-09-15')


def test_parse_manual():
    assert parse_manual('56=После КРС: замена фильтра;7 = Без КРС\nбез знака') == {'56': 'После КРС: замена фильтра', '7': 'Без КРС'}


def test_season_verdicts_and_categories():
    g, works = frames()
    rows = study_rows(g, 0.95)
    t = season_table(rows, ['2025-2026'], 5.0, 5.0, repairs(works, None), {}).set_index('well')
    assert t.at['1', 'verdict'] == 'Улучшение' and t.at['1', 'category'] == 'После КРС: замена фильтра'
    assert t.at['2', 'verdict'] == 'Ухудшение' and t.at['2', 'category'] == 'Без КРС'
    assert t.at['3', 'verdict'] == 'Без изменений' and t.at['3', 'category'] == 'ГДИ не делали более 5 лет'
    assert t.at['4', 'verdict'] == 'Недостаточно надёжных' and t.at['4', 'category'] == 'Первое ГДИ'      # пропуск, не нуль
    assert np.isnan(t.at['4', 'change'])


def test_manual_category_overrides_hint():
    g, works = frames()
    t = season_table(study_rows(g, 0.95), ['2025-2026'], 5.0, 5.0, repairs(works, None), {'2': 'После КРС 2023 г.'}).set_index('well')
    assert t.at['2', 'category'] == 'После КРС 2023 г.' and t.at['2', 'edited'] == 'вручную' and t.at['2', 'auto'] == 'Без КРС'


def test_repair_year_before_after():
    g, works = frames()
    rows = study_rows(g, 0.95)
    t = repair_year_table(rows, repairs(works, None), 2025, 5.0).set_index('well')
    assert t.at['5', 'verdict'] == NO_AFTER                    # ремонт 1 июля, ГДИ только в марте
    assert t.at['6', 'verdict'] == 'Улучшение'                 # ГДИ в марте и октябре, ремонт между ними
    assert t.at['1', 'verdict'] in ('Улучшение', 'Недостаточно надёжных', 'Нет ГДИ до ремонта', NO_AFTER)


def test_plan_dates_replace_july_first():
    g, works = frames()
    plan = pd.DataFrame([dict(well='5', year=2025, start=pd.Timestamp('2025-01-10'), end=pd.Timestamp('2025-02-01'), kind='КР')])
    r = repairs(works, plan).set_index('well')
    assert r.at['5', 'date'] == pd.Timestamp('2025-02-01') and bool(r.at['5', 'dated'])
    assert r.at['6', 'date'] == pd.Timestamp('2025-07-01') and not bool(r.at['6', 'dated'])
    t = repair_year_table(study_rows(g, 0.95), r.reset_index(), 2025, 5.0).set_index('well')
    assert t.at['5', 'verdict'] != NO_AFTER                    # ГДИ в марте теперь после ремонта


def test_run_builds_charts_and_tables():
    g, works = frames()
    d = Data({G: g, W: works})
    res = GdiSummaryModule().run(d, PARAMS)
    ids = {c.id for c in res.charts}
    assert {'gdi-summary-by-cat', 'gdi-summary-grouped', 'gdi-summary-share', 'gdi-summary-hist', 'gdi-summary-repair'} <= ids
    assert {t.id for t in res.tables} >= {'gdi-summary-matrix', 'gdi-summary-wells', 'gdi-summary-repairs'}
    stack = next(c for c in res.charts if c.id == 'gdi-summary-by-cat')
    assert sum(float(s.y.sum()) for s in stack.series) == 7          # шесть скважин; у скв. 6 ГДИ и в отбор, и в закачку — две строки (срезы)
    assert next(x for x in res.summary if x.label == 'Скважин в сезоне').value == '6'


def test_run_without_krs_and_empty_season():
    g, _ = frames()
    res = GdiSummaryModule().run(Data({G: g}), PARAMS)
    assert any('КРС' in n.text for n in res.notes) and res.charts
    res = GdiSummaryModule().run(Data({G: g}), {**PARAMS, 'seasons': ['1999-2000']})
    assert not res.charts and res.notes


def test_result_serializes_to_json():
    import json
    g, works = frames()
    res = GdiSummaryModule().run(Data({G: g, W: works}), PARAMS)
    json.dumps(res.to_json(), allow_nan=False, default=str)


def test_program_vs_fact():
    from atlas.modules.gdi_summary import STATUS_DONE, STATUS_NONE, STATUS_WEAK, program_table
    g, _ = frames()
    rows = study_rows(g, 0.95)
    rows.loc[rows.well.eq('3') & rows.season.eq('2025-2026'), 'reliable'] = False       # скв. 3: исследование есть, но ненадёжное
    prog = pd.DataFrame({'well': ['1', '3', '9'], 'group': ['ГСП-1'] * 3, 'season': ['2025-2026'] * 3, 'stage': ['I этап', 'I этап', 'II этап'],
                         'reason': ['план КР'] * 3, 'reason_kind': ['krs_plan', 'krs_plan', 'gap'], 'krs_injection': [True, True, False]})
    t = program_table(rows, prog, ['2025-2026']).set_index('well')
    assert t.status.to_dict() == {'1': STATUS_DONE, '3': STATUS_WEAK, '9': STATUS_NONE}
    assert t.loc['1', 'krs_injection'] == 'да' and t.loc['9', 'krs_injection'] == ''
    r = GdiSummaryModule().run(Data({G: g, DatasetKind.GDI_PROGRAM: prog}), PARAMS)
    assert any(x.id == 'gdi-summary-program-wells' for x in r.tables) and any('Не выполнено по программе' in s.label for s in r.summary)
    empty = GdiSummaryModule().run(Data({G: g}), PARAMS)
    assert any('Программа ГДИ не загружена' in n.text for n in empty.notes)


def test_groups_from_program_and_no_krs_reason():
    from atlas.modules.gdi_summary import CAT_OFF_PROGRAM, CAT_NO_REPAIR, program_groups
    g, works = frames()
    rows = study_rows(g, 0.95)
    prog = pd.DataFrame({'well': ['1', '2'], 'group': ['ГСП-1'] * 2, 'season': ['2025-2026'] * 2, 'stage': ['I этап', 'II этап'],
                         'reason': ['замена фильтра', 'давно'], 'reason_kind': ['filter', 'gap'], 'krs_injection': [False, False]})
    groups = program_groups(prog, ['2025-2026'])
    t = season_table(rows, ['2025-2026'], 5.0, 5.0, repairs(works, None), {}, groups).set_index('well')
    assert t.loc['1', 'category'] == 'После КР: замена фильтра' and 'программа ГДИ 2025-2026: I этап' in t.loc['1', 'reason']
    assert t.loc['3', 'category'] == CAT_OFF_PROGRAM                        # скважины нет в программе
    plain = season_table(rows, ['2025-2026'], 5.0, 5.0, repairs(works, None), {}).set_index('well')
    assert plain.loc['2', 'category'] == CAT_NO_REPAIR and 'в данных КРС по скважине ремонтов нет' in plain.loc['2', 'reason']
    assert plain.loc['1', 'category'].startswith('После КРС')
    r = GdiSummaryModule().run(Data({G: frames()[0], DatasetKind.GDI_PROGRAM: prog}), PARAMS)
    cats = next(t for t in r.tables if t.id == 'gdi-summary-wells').frame.category.unique()
    assert set(cats) <= {'После КР: замена фильтра', 'ГДИ давно не проводились', CAT_OFF_PROGRAM}


def test_periods_slices_and_manual_done():
    from atlas.modules.gdi_summary import PERIOD_INJ, PERIOD_NEUTRAL, PERIOD_WD, STATUS_MANUAL, STATUS_NONE, period_of, program_table
    ts = pd.Timestamp
    assert period_of(ts('2025-12-10'), None) == PERIOD_WD and period_of(ts('2025-07-10'), None) == PERIOD_INJ
    sched = '01.05.2025 inj\n01.11.2025 none\n01.12.2025 prod'
    assert period_of(ts('2025-06-01'), sched) == PERIOD_INJ and period_of(ts('2025-11-15'), sched) == PERIOD_NEUTRAL
    g, works = frames()
    rows = study_rows(g, 0.95)
    t = season_table(rows, ['2025-2026'], 5.0, 5.0, repairs(works, None), {}, period_manual={'2': 'Нейтральный период'}).set_index('well')
    assert t.loc['2', 'slice'] == PERIOD_NEUTRAL and t.loc['2', 'slice_edited'] == 'вручную' and t.loc['1', 'slice'] == PERIOD_WD
    prog = pd.DataFrame({'well': ['9'], 'group': ['ГСП-1'], 'season': ['2025-2026'], 'stage': ['I этап'], 'reason': ['x'], 'reason_kind': ['filter'],
                         'krs_injection': [False]})
    assert program_table(rows, prog, ['2025-2026']).status.tolist() == [STATUS_NONE]
    done = program_table(rows, prog, ['2025-2026'], {'9': 'не удалось провести'})
    assert done.status.tolist() == [STATUS_MANUAL] and done.status_note.tolist() == ['не удалось провести']
    r = GdiSummaryModule().run(Data({G: g}), {**PARAMS, 'slice': [PERIOD_NEUTRAL], 'period_manual': '2=Нейтральный период'})
    assert next(x for x in r.tables if x.id == 'gdi-summary-wells').frame.well.tolist() == ['2']


def test_slices_withdrawal_injection_neutral_per_period_rows():
    """Три среза: сезон отбора, сезон закачки, нейтральные периоды; скважина с ГДИ в разных периодах получает строку в каждом."""
    from atlas.modules.gdi_summary import PERIOD_INJ, PERIOD_NEUTRAL, PERIOD_WD, SLICES, normalize_slice
    assert SLICES == (PERIOD_WD, PERIOD_INJ, PERIOD_NEUTRAL) and normalize_slice('отбор') == PERIOD_WD and normalize_slice('Закачка') == PERIOD_INJ
    g = pd.DataFrame(gdi('1', '2025-03-10', season='2025-2026') + gdi('1', '2025-09-10', 0.7, season='2025-2026') + gdi('1', '2025-12-10', 0.8, season='2025-2026'))
    rows = study_rows(g, 0.95)
    t = season_table(rows, ['2025-2026'], 5.0, 5.0, repairs(None, None), {}).set_index('slice')
    assert set(t.index) == {PERIOD_WD, PERIOD_INJ} and t.loc[PERIOD_INJ, 'last_date'] == pd.Timestamp('2025-09-10')
    assert t.loc[PERIOD_INJ, 'prev_date'] == pd.Timestamp('2025-03-10')            # закачка сравнивается с предыдущим надёжным ГДИ
    only = GdiSummaryModule().run(Data({G: g}), {**PARAMS, 'seasons': ['2025-2026'], 'slice': [PERIOD_INJ]})
    assert next(x for x in only.tables if x.id == 'gdi-summary-wells').frame.slice.unique().tolist() == [PERIOD_INJ]


def test_histogram_coarse_bins_and_per_group_charts():
    from atlas.modules.gdi_summary import change_histogram, parse_edges
    assert parse_edges('') == [-30, -15, -5, 5, 15, 30] and parse_edges('−10; 0 10 abc 10') == [-10, 0, 10] and parse_edges('5') == parse_edges('')
    t = pd.DataFrame({'change': [-40., -10., -2., 0., 3., 12., 50., np.nan], 'category': ['a'] * 8})
    h = change_histogram(t, 5.0)
    assert h.x.categories == ['< -30', '-30…-15', '-15…-5', '-5…5', '5…15', '15…30', '> 30', 'Нет сравнения']
    assert [int(sum(s.y[i] for s in h.series)) for i in range(8)] == [1, 0, 1, 3, 1, 0, 1, 1]   # −2, 0 и 3 в одной корзине «−5…5»; без сравнения — отдельно
    g, works = frames()
    prog = pd.DataFrame({'well': ['1', '2'], 'group': ['ГСП-1'] * 2, 'season': ['2025-2026'] * 2, 'stage': ['I этап'] * 2, 'reason': ['фильтр', 'давно'],
                         'reason_kind': ['filter', 'gap'], 'krs_injection': [False, False]})
    r = GdiSummaryModule().run(Data({G: g, DatasetKind.GDI_PROGRAM: prog}), {**PARAMS, 'hist_by': 'both', 'hist_edges': '-10, 10'})
    ids = [c.id for c in r.charts if c.id.startswith('gdi-summary-hist')]
    assert ids[0] == 'gdi-summary-hist' and len(ids) >= 2 and all('скв.' in c.title for c in r.charts if c.id.startswith('gdi-summary-hist-'))


def test_histograms_use_dot_callouts_with_numbers_in_table():
    """Как в «Авторском надзоре»: узкий сегмент — точки без выноски (режим ядра ``Chart.callouts``), числа — в таблице под графиком."""
    from atlas.modules.gdi_summary import change_histogram, stacked, VERDICTS, VERDICT_COLORS
    t = pd.DataFrame({'change': [-2., 0., 3., 50.]})
    h = change_histogram(t, 5.0)
    assert h.callouts == 'dot' and h.table.cells == [['0', '0', '0', '3', '0', '0', '1']] and h.table.columns[3] == '-5…5'
    c = stacked('x', 'x', ['a'], {('a', VERDICTS[0]): 1}, VERDICTS, VERDICT_COLORS, 'k')
    assert c.callouts == 'dot' and c.table is not None
    g, works = frames()
    r = GdiSummaryModule().run(Data({G: g}), PARAMS)
    with_segments = [ch for ch in r.charts if any(se.segments for se in ch.series)]
    assert with_segments and all(ch.callouts == 'dot' for ch in with_segments)


def test_histogram_total_matches_wells_and_every_chart_exports():
    """Сумма гистограммы = число скважин сезона (скважины без сравнения — отдельный столбец); все графики модуля выгружаются."""
    from atlas.chart_special import figure_file, is_special
    from atlas.modules.gdi_summary import NO_COMPARE
    g, _ = frames()
    r = GdiSummaryModule().run(Data({G: g}), {**PARAMS, 'hist_by': 'both'})
    table = next(x for x in r.tables if x.id == 'gdi-summary-wells').frame
    h = next(c for c in r.charts if c.id == 'gdi-summary-hist')
    assert int(sum(sum(s.y) for s in h.series)) == len(table) and f'{len(table)} скв.' in h.title
    assert int(sum(float(v) for v in h.table.cells[0])) == len(table)
    assert (NO_COMPARE in h.x.categories) == bool(table.change.isna().any())
    for ch in r.charts:
        if is_special(ch):
            assert figure_file(ch, 'png', 60)[:4] == b'\x89PNG', ch.id


def test_season_matrix_wells_by_seasons_with_krs_and_plan():
    """Скважина × сезон: надёжное, ненадёжное, плановое не выполнено, ремонт в год начала сезона; график общим ядром (HeatMap)."""
    from atlas.chart_special import figure_file
    from atlas.modules.gdi_summary import MATRIX_NONE, MATRIX_OK, MATRIX_PLAN, MATRIX_WEAK, season_matrix
    ts = pd.Timestamp
    rows = pd.DataFrame({'well': ['1', '1', '2'], 'date': [ts('2024-12-01'), ts('2025-12-01'), ts('2025-12-05')], 'season': ['2024-2025', '2025-2026', '2025-2026'],
                         'reliable': [True, True, False], 'q_ref': [100., 90., 50.]})
    prog = pd.DataFrame({'well': ['3', '2'], 'season': ['2025-2026'] * 2})
    rep = pd.DataFrame({'well': ['1'], 'year': [2025], 'date': [ts('2025-07-01')]})
    wells, seasons, values, texts = season_matrix(rows, prog, rep, {'3': 'не удалось'})
    cell = lambda w, s: (values[wells.index(w)][seasons.index(s)], texts[wells.index(w)][seasons.index(s)])
    assert wells == ['1', '2', '3'] and seasons == ['2024-2025', '2025-2026']
    assert cell('1', '2024-2025') == (MATRIX_OK, '✓') and cell('1', '2025-2026') == (MATRIX_OK, '✓ +КРС')
    assert cell('2', '2025-2026') == (MATRIX_WEAK, '!') and cell('2', '2024-2025') == (None, '')
    assert cell('3', '2025-2026')[0] == MATRIX_OK and season_matrix(rows, prog, rep)[2][2][1] == float(MATRIX_PLAN)
    g, _ = frames()
    r = GdiSummaryModule().run(Data({G: g}), PARAMS)
    ch = next(c for c in r.charts if c.id == 'gdi-summary-season-matrix')
    assert ch.heat is not None and any(t.id == 'gdi-summary-season-matrix-table' for t in r.tables)
    assert figure_file(ch, 'png', 60)[:4] == b'\x89PNG'


def test_repair_path_before_after_next_withdrawal():
    """Путь после КРС: до ремонта → первое надёжное после вне отбора → первое надёжное следующего отбора; ненадёжные не входят."""
    from atlas.chart_special import figure_file  # noqa: F401
    from atlas.modules.gdi_summary import repair_path_chart, repair_path_table
    ts = pd.Timestamp
    rows = pd.DataFrame({'well': ['1'] * 5, 'season': ['x'] * 5, 'q_ref': [100., 120., 999., 110., 80.],
                         'date': [ts('2025-03-01'), ts('2025-09-01'), ts('2025-10-01'), ts('2025-12-10'), ts('2026-02-01')],
                         'reliable': [True, True, False, True, True]})
    rep = pd.DataFrame({'well': ['1'], 'year': [2025], 'kind': ['КРС'], 'date': [ts('2025-07-01')], 'dated': [False]})
    t = repair_path_table(rows, rep, 2025)
    assert t.q_before.tolist() == [100.] and t.q_after.tolist() == [120.] and t.q_next.tolist() == [110.]
    ch = repair_path_chart(t, 2025)
    assert ch.series[0].y.tolist() == [100., 120., 110.] and ch.x.categories == ['До КРС', 'После КРС', 'Следующий отбор']
    assert repair_path_chart(t.iloc[0:0], 2025) is None


def test_repair_effect_box_by_kind_with_well_numbers():
    from atlas.chart_special import figure_file  # noqa: F401
    from atlas.modules.gdi_summary import repair_effect_chart
    t = pd.DataFrame({'well': ['3', '1', '2', '4'], 'kind': ['A', 'A', 'A', 'B'], 'change': [-10., 10., 30., np.nan]})
    ch = repair_effect_chart(t, 2025)
    assert ch.x.categories == ['A'] and ch.series[0].kind == 'box' and ch.series[0].y == [[-10., 0., 10., 20., 30.]]
    assert ch.table.cells == [['3'], ['+10.0']] and ch.table.wells[0] == [['1', '2', '3']]
    assert repair_effect_chart(t[t.kind.eq('B')], 2025) is None


def test_age_table_candidates_after_repair():
    from atlas.modules.gdi_summary import AGE_NONE, CAND_NONE, CAND_REPAIR, age_table
    ts = pd.Timestamp
    rows = pd.DataFrame({'well': ['1', '1', '2', '3'], 'date': [ts('2020-01-01'), ts('2024-01-01'), ts('2025-12-01'), ts('2025-12-01')],
                         'season': ['x'] * 4, 'reliable': [True, True, True, False], 'q_ref': [1., 1., 1., 1.]})
    rep = pd.DataFrame({'well': ['1', '2'], 'year': [2025, 2024], 'kind': ['КРС', 'КРС'], 'date': [ts('2025-07-01'), ts('2024-07-01')]})
    t = age_table(rows, rep).set_index('well')
    assert t.loc['1', 'candidate'] == CAND_REPAIR and t.loc['1', 'age_bin'] == '1–2 года' and t.loc['1', 'repair_year'] == 2025
    assert t.loc['2', 'candidate'] == CAND_NONE and t.loc['3', 'age_bin'] == AGE_NONE
    r = GdiSummaryModule().run(Data({G: frames()[0]}), PARAMS)
    assert any(c.id == 'gdi-summary-age' for c in r.charts) and any(x.id == 'gdi-summary-age-table' for x in r.tables)


def test_well_card_all_studies_with_repairs():
    from atlas.chart_special import figure_file  # noqa: F401
    from atlas.modules.gdi_summary import repairs, study_rows, well_card_chart, well_card_table
    g, works = frames()
    rows = study_rows(g, 0.95)
    card = well_card_table(g, rows, '1', 0.95)
    assert len(card) == 2 and card.date.is_monotonic_increasing and card.a.notna().all() and card.b.notna().all()
    ch = well_card_chart(card, repairs(works, None), '1')
    assert [s.name for s in ch.series[:3]] == ['Q при опорном ΔP²', 'a', 'b'] and ch.y2 is not None and ch.y3 is not None
    assert len(ch.events) == 1 and ch.events[0].kind == 'repair' and ch.events[0].well == '1'
    r = GdiSummaryModule().run(Data({G: g, DatasetKind.KRS_WORKS: works}), {**PARAMS, 'card_well': '№ 1'})
    assert any(c.id == 'gdi-summary-well-card' for c in r.charts) and any(t.id == 'gdi-summary-well-card-table' for t in r.tables)
    r2 = GdiSummaryModule().run(Data({G: g}), {**PARAMS, 'card_well': '99'})
    assert any('99' in n.text for n in r2.notes)


def test_program_coverage_by_group_and_month():
    from atlas.modules.gdi_summary import STATUS_DONE, STATUS_NONE, coverage_by_month
    ts = pd.Timestamp
    t = pd.DataFrame({'well': ['1', '2', '3', '4'], 'group': ['ГСП-1', 'ГСП-1', 'ГСП-2', 'ГСП-2'],
                      'status': [STATUS_DONE, STATUS_DONE, STATUS_DONE, STATUS_NONE],
                      'last_date': [ts('2025-10-05'), ts('2025-10-20'), ts('2025-12-01'), pd.NaT]})
    labels, n, share = coverage_by_month(t)
    assert labels == ['окт 2025', 'ноя 2025', 'дек 2025'] and n == [2, 0, 1] and share == [50.0, 50.0, 75.0]
    g, _ = frames()
    prog = pd.DataFrame({'well': ['1', '2', '9'], 'group': ['ГСП-1', 'ГСП-1', 'ГСП-2'], 'season': ['2025-2026'] * 3, 'stage': ['I этап'] * 3,
                         'reason': ['x'] * 3, 'reason_kind': ['filter'] * 3, 'krs_injection': [False] * 3})
    r = GdiSummaryModule().run(Data({G: g, DatasetKind.GDI_PROGRAM: prog}), PARAMS)
    ids = [c.id for c in r.charts]
    assert 'gdi-summary-program-groups' in ids and 'gdi-summary-program-months' in ids


def test_model_compare_top_and_empty_state():
    from atlas.modules.gdi_summary import EMPTY_MODEL, model_compare, study_rows
    g, _ = frames()
    rows = study_rows(g, 0.95)
    day = pd.Timestamp('2025-12-10')
    model = pd.DataFrame({'well': ['1', '2'], 'date': [day + pd.Timedelta(days=1), day], 'model': ['m', 'm'], 'wbp': [75., 75.], 'wbhp': [60., 40.], 'wgpr': [100., 90.]})
    t = model_compare(g, rows, model, ['2025-2026'])
    assert t.well.tolist() == ['1', '2'] and t.dp2_diff.abs().is_monotonic_decreasing      # по убыванию |ΔP²|
    one = g[(g.well == '1') & (g.date == day) & (g.q == 190.)].iloc[0]
    assert abs(t.set_index('well').loc['1', 'dp_gdi'] - (one.p_res - one.p_bh)) < 1e-9 and t.dp2_diff.notna().all()
    assert model_compare(g, rows, None, ['2025-2026']).empty
    r = GdiSummaryModule().run(Data({G: g}), PARAMS)
    assert any(n.text == EMPTY_MODEL for n in r.notes)
    r = GdiSummaryModule().run(Data({G: g, DatasetKind.MODEL: model}), PARAMS)
    assert any(c.id == 'gdi-summary-model' for c in r.charts) and any(t.id == 'gdi-summary-model-table' for t in r.tables)


def test_id_pairs_before_after_colors_and_manual_override():
    from atlas.modules.gdi_summary import krs_pairs, parse_pairs, repairs, study_rows
    ts = pd.Timestamp
    g, works = frames()
    rows = study_rows(g, 0.95)
    rep = repairs(works, None)
    auto = {x['well']: (x['before'], x['after']) for x in krs_pairs(rows, rep, {2025})}
    assert auto['1'] == (ts('2024-12-10'), ts('2025-12-10')) and auto['6'] == (ts('2025-03-01'), ts('2025-10-01')) and '5' not in auto
    manual = parse_pairs('1=10.12.2024; 10.12.2025\n7=bad')
    assert manual == {'1': (ts('2024-12-10'), ts('2025-12-10'))}
    hand = krs_pairs(rows, rep, {2025}, {'1': (ts('2024-12-10'), ts('2024-12-10'))})
    assert [(x['before'], x['after'], x['year']) for x in hand if x['well'] == '1'] == [(ts('2024-12-10'), ts('2024-12-10'), 0)]
    r = GdiSummaryModule().run(Data({G: g, W: works, DatasetKind.KRS_WORKS: works}), {**PARAMS, 'id_charts': 'yes', 'id_pairs': ''})
    ch = next(c for c in r.charts if c.id == 'gdi-summary-id-1-2025')
    points = [s for s in ch.series if s.kind == 'points']
    assert [s.name for s in points] == ['до КРС · 10.12.2024', 'после КРС · 10.12.2025'] and [s.color for s in points] == ['#d62728', '#2ca02c']
    assert not any(c.id.startswith('gdi-summary-id') for c in GdiSummaryModule().run(Data({G: g, W: works}), PARAMS).charts)


def test_engine_gdi_chart_pair_two_studies_red_green():
    """Выгрузка раздела «ГДИ»: две даты пары — красный «до КРС», зелёный «после КРС»; остальные исследования не рисуются."""
    from atlas.engine.modules import charts
    g, _ = frames()
    g = pd.concat([g, pd.DataFrame(gdi('1', '2023-12-10'))], ignore_index=True)
    ts = pd.Timestamp
    fig = charts.gdi_chart(g[g.well == '1'], '1', 0.95, pair=(ts('2024-12-10'), ts('2025-12-10')))
    dots = [t for t in fig.data if t.mode == 'markers']
    assert [t.name.split(' · Уст')[0] for t in dots] == ['до КРС · 10.12.2024', 'после КРС · 10.12.2025'] and [t.marker.color for t in dots] == ['#d62728', '#2ca02c']
    assert not any('2023' in (t.name or '') for t in fig.data)


def test_export_gdi_section_krs_pairs_plan():
    """Выгрузка раздела «ГДИ» с ИД до и после КРС: один график на скважину пары, красный и зелёный; без пар — прежний набор."""
    from atlas.engine.core import reporting
    g, works = frames()
    settings = {'r2_threshold': 0.95, 'season_start': 11, 'season_end': 4}
    cfg = {'wells': ['1', '2'], 'n': 3, 'orientation': 'standard'}
    base = reporting.plan({'gdi': g}, {}, settings, {'modules': ['gdi'], 'wells': ['1', '2'], 'raw': False, 'gdi': cfg}, {'gdi': g})
    paired = reporting.plan({'gdi': g}, {}, settings, {'modules': ['gdi'], 'wells': ['1', '2'], 'raw': False,
                                                       'gdi': {**cfg, 'krs_pairs': [{'well': '1', 'before': '2024-12-10', 'after': '2025-12-10', 'year': 2025}]}}, {'gdi': g})
    assert [j.name for j in base.jobs] == ['ГДИ · 1', 'ГДИ · 2']
    assert [j.name for j in paired.jobs] == ['ГДИ · 1 · КРС 2025 · до и после КРС']
    fig = paired.jobs[0].factory()
    assert sorted(t.marker.color for t in fig.data if t.mode == 'markers') == ['#2ca02c', '#d62728']
    from atlas.api_export import krs_pairs_cfg
    data = Data({G: g, DatasetKind.KRS_WORKS: works})
    data.settings = settings
    got = krs_pairs_cfg(data, ['1', '6'], '', ['2025-2026'])
    assert [(x['well'], x['before'], x['after'], x['year']) for x in got] == [('1', '2024-12-10', '2025-12-10', 2025), ('6', '2025-03-01', '2025-10-01', 2025)]
    assert [x['before'] for x in krs_pairs_cfg(data, ['1'], '1=01.01.2024; 02.02.2025', [])] == ['2024-01-01']


def test_export_krs_pairs_only_selected_seasons_and_every_repair():
    """Выгрузка ИД до/после КРС: только ремонты выбранных сезонов, по графику на каждый ремонт (не только первый), только их скважины."""
    from atlas.api_export import krs_pairs_cfg
    g, works = frames()
    g = pd.concat([g, pd.DataFrame(gdi('1', '2023-12-10', 1.2) + gdi('7', '2023-12-10') + gdi('7', '2024-12-10', 0.9))], ignore_index=True)
    works = pd.concat([works, pd.DataFrame([dict(well='1', year=2024, work_type='Промывка', detail=''), dict(well='7', year=2024, work_type='Замена фильтра', detail='')])],
                      ignore_index=True)
    data = Data({G: g, DatasetKind.KRS_WORKS: works})
    data.settings = {'r2_threshold': 0.95, 'season_start': 11, 'season_end': 4}
    only_2025 = krs_pairs_cfg(data, [], '', ['2025-2026'])
    assert {x['well'] for x in only_2025} == {'1', '6'} and {x['year'] for x in only_2025} == {2025}
    both = krs_pairs_cfg(data, [], '', ['2024-2025', '2025-2026'])
    assert [(x['well'], x['year']) for x in both if x['well'] == '1'] == [('1', 2024), ('1', 2025)]
    assert [(x['well'], x['year']) for x in krs_pairs_cfg(data, [], '', ['2024-2025'])] == [('1', 2024), ('7', 2024)]


def test_repair_follow_up_analysis_effect_and_next_withdrawal():
    """Анализ ГДИ до/после КРС: эффект после КРС и в следующем отборе, есть ли ГДИ в отборе, вывод-подсказка; несколько лет ремонтов."""
    from atlas.modules.gdi_summary import FOLLOW_AFTER, FOLLOW_BOTH, FOLLOW_NEXT, follow_up, repair_path_table
    nan = float('nan')
    assert follow_up(20, 10, 5) == 'эффект ремонта подтверждён в следующем отборе' and follow_up(20, -10, 5) == 'эффект после КРС не сохранился в следующем отборе'
    assert follow_up(nan, 10, 5).startswith('после КРС не исследована') and follow_up(20, nan, 5).startswith('в следующем отборе не исследована')
    assert follow_up(nan, nan, 5).startswith('нет ГДИ после ремонта')
    ts = pd.Timestamp
    rows = pd.DataFrame({'well': ['1'] * 4 + ['2'] * 2, 'season': ['x'] * 6, 'q_ref': [100., 120., 110., 90., 100., 105.],
                         'date': [ts('2025-03-01'), ts('2025-09-01'), ts('2025-12-10'), ts('2027-12-10'), ts('2025-03-01'), ts('2025-09-01')],
                         'reliable': [True] * 6})
    rep = pd.DataFrame({'well': ['1', '2', '1'], 'year': [2025, 2025, 2027], 'kind': ['КРС'] * 3, 'date': [ts('2025-07-01'), ts('2025-07-01'), ts('2027-07-01')], 'dated': [False] * 3})
    t = repair_path_table(rows, rep, {2025, 2027}).set_index(['well', 'year'])
    assert t.loc[('1', 2025), 'follow'] == FOLLOW_BOTH and round(t.loc[('1', 2025), 'change_after']) == 20 and round(t.loc[('1', 2025), 'change_next']) == 10
    assert t.loc[('1', 2025), 'conclusion'] == 'эффект ремонта подтверждён в следующем отборе'
    assert t.loc[('2', 2025), 'follow'] == FOLLOW_AFTER and t.loc[('1', 2027), 'follow'] == FOLLOW_NEXT      # скв. 1 после ремонта 2027 г.: только следующий отбор
    g, works = frames()
    r = GdiSummaryModule().run(Data({G: g, W: works}), {**PARAMS, 'seasons': ['2025-2026'], 'repair_year': 0})
    assert any(c.id == 'gdi-summary-follow' for c in r.charts) and any(x.label == 'ГДИ в следующем отборе' for x in r.summary)


def test_export_krs_pairs_by_repair_year_and_period():
    """Выгрузка ИД до/после КРС: годы ремонтов задаются явно (подпись сезона ГДИ лета не обязана совпасть с годом ремонта), период ГДИ после ремонта — как в справке."""
    from atlas.api_export import krs_pairs_cfg
    g = pd.DataFrame(gdi('1', '2025-12-10') + gdi('1', '2026-09-10', 0.8, season='2025-2026'))     # лето 2026 подписано сезоном отбора
    works = pd.DataFrame([dict(well='1', year=2026, work_type='Замена фильтра', detail='')])
    data = Data({G: g, DatasetKind.KRS_WORKS: works})
    data.settings = {'r2_threshold': 0.95, 'season_start': 11, 'season_end': 4}
    assert krs_pairs_cfg(data, [], '', ['2025-2026']) == []                                         # по подписи сезона ремонт 2026 не находится
    got = krs_pairs_cfg(data, [], '', ['2025-2026'], ['2026'])
    assert [(x['well'], x['year']) for x in got] == [('1', 2026)]
    assert krs_pairs_cfg(data, [], '', [], ['2026'], ['Сезон закачки']) == got
    assert krs_pairs_cfg(data, [], '', [], ['2026'], ['Сезон отбора']) == []


def test_single_study_chart_keeps_legend_with_date():
    """ИД с одним исследованием: легенда включена явно (plotly прячет её при единственной записи), подпись — с датой."""
    from atlas.engine.modules import charts
    fig = charts.gdi_chart(pd.DataFrame(gdi('1', '2025-12-10')), '1')
    assert fig.layout.showlegend is True
    assert [t.name for t in fig.data if t.showlegend is not False] == ['10.12.2025 · Установившиеся отборы']


def test_id_charts_come_first_when_enabled():
    """Включённые ИД до/после КРС стоят первыми среди графиков справки (иначе при постраничном показе они уходят на 2–3-ю страницу)."""
    g, works = frames()
    r = GdiSummaryModule().run(Data({G: g, W: works, DatasetKind.KRS_WORKS: works}), {**PARAMS, 'id_charts': 'yes', 'id_pairs': ''})
    ids = [i for i, c in enumerate(r.charts) if c.id.startswith('gdi-summary-id-')]
    assert ids and ids == list(range(len(ids)))
