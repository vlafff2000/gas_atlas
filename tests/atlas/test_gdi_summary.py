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
    assert sum(float(s.y.sum()) for s in stack.series) == 6          # скважин в сезоне 2025-2026 — все шесть


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
