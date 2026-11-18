"""Справка по результатам ГДИ за сезон и по скважинам с ремонтом (КРС): таблицы и гистограммы.

Математику ГДИ не трогаем: расход при опорном ΔP² и надёжность исследования — ``gdi._productivity_rows`` (``gdi_history`` 5.8).
Здесь только выбор данных, сопоставление с ремонтами КРС (``krs_works``: тип и год; даты — из справки ``krs_plan``, если есть) и
представление. Категории скважин — подсказка с видимой причиной, инженер правит их вручную (параметр «Категории вручную»).
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from atlas.engine.modules import gdi as legacy
from atlas.engine.core import krs_plan_file_import
from atlas.engine.modules import seasons as season_rules

from ..contract import Axis, Chart, ChartTable, Column, Data, Module, ModuleSpec, Note, Event, Option, Param, Result, Series, Source, Stat, Table
from ..domain import UNITS, DatasetKind
from .gdi import VERDICT_DOWN, VERDICT_FEW, VERDICT_SAME, VERDICT_UP, _productivity_rows, well_key

GDI, WORKS, PLAN, PROGRAM = DatasetKind.GDI, DatasetKind.KRS_WORKS, DatasetKind.KRS_PLAN, DatasetKind.GDI_PROGRAM
VERDICTS = (VERDICT_UP, VERDICT_SAME, VERDICT_DOWN, VERDICT_FEW)
VERDICT_COLORS = {VERDICT_UP: '#2e9d57', VERDICT_SAME: '#8c96a3', VERDICT_DOWN: '#d64545', VERDICT_FEW: '#d9c26a'}
NO_AFTER, NO_BEFORE = 'ГДИ после ремонта не проводили', 'Нет ГДИ до ремонта'
REPAIR_VERDICTS = (VERDICT_UP, VERDICT_SAME, VERDICT_DOWN, VERDICT_FEW, NO_BEFORE, NO_AFTER)
REPAIR_COLORS = {**VERDICT_COLORS, NO_BEFORE: '#b88fd1', NO_AFTER: '#4f6d8f'}
CAT_NO_REPAIR, CAT_FIRST = 'Без КРС', 'Первое ГДИ'
SECTION = 'Выбор данных'
NOTE = ('Справка по надёжным исследованиям (R² не ниже порога, не менее трёх разных расходов, a и b не отрицательны). Расход '
        'сравнивается при одном опорном ΔP² скважины: последнее надёжное исследование сезона против последнего надёжного до сезона. '
        'Категории — подсказка по данным КРС и срокам ГДИ с видимой причиной; решает инженер: исправьте категорию в параметре '
        '«Категории вручную», и она встанет в таблицы и гистограммы.')
EMPTY_PROGRAM = 'Программа ГДИ не загружена: загрузите файл программы (Word) во вкладке «Импорт», тогда здесь появится выполнение по скважинам.'
EMPTY_KRS = 'Данных КРС в проекте нет, категории по ремонтам не определены: импортируйте КРС_для_Атласа.xlsx во вкладке «Импорт».'


def repair_class(work_type) -> str:
    """Вид ремонта из строки справки: замена фильтра, армирование, промывка/СКО/колтюбинг, прочее."""
    t = str(work_type or '').lower()
    if 'фильтр' in t:
        return 'замена фильтра'
    if 'армир' in t:
        return 'армирование ПЗП'
    if any(k in t for k in ('колтюбинг', 'ско', 'промыв')):
        return 'промывка / СКО'
    return 'прочее'


def normalize_slice(value: str) -> str:
    """Срез из ручной правки: «отбор», «Сезон отбора», «закачка», «нейтральный» → один из ``SLICES``; незнакомое остаётся как есть."""
    v = str(value).strip()
    return next((name for name in SLICES if name.lower() == v.lower()), SLICE_ALIASES.get(v.lower().split()[0] if v.split() else '', v))


def parse_manual(text: str) -> dict[str, str]:
    """Строки «скважина=категория» (перенос строки или «;»); пустая категория — правка снята."""
    out = {}
    for line in re.split(r'[\n;]+', str(text or '')):
        if '=' in line:
            well, cat = (s.strip() for s in line.split('=', 1))
            if well and cat:
                out[well] = cat
    return out


def repairs(works: pd.DataFrame | None, plan: pd.DataFrame | None) -> pd.DataFrame:
    """Ремонты: well, year, kind (вид), work_type, date (по справке КРС «дата окончания»/«начала», иначе 1 июля года)."""
    cols = ['well', 'year', 'kind', 'work_type', 'date', 'dated']
    if works is None or works.empty or 'year' not in works:
        return pd.DataFrame(columns=cols)
    w = works.dropna(subset=['year']).copy()
    w['well'], w['year'] = w.well.astype(str), w.year.astype(int)
    w['work_type'] = w.get('work_type', pd.Series('', index=w.index)).fillna('').astype(str)
    w['kind'] = w.work_type.map(repair_class)
    w['date'] = pd.to_datetime(w.year.astype(str) + '-07-01')
    w['dated'] = False
    plan = krs_plan_file_import.actual(plan)          # даты ремонта — только фактические (справка), не плановые
    if plan is not None and not plan.empty and {'well', 'year', 'start'} <= set(plan.columns):
        p = plan.copy()
        if 'kind' in p:
            p = p[p['kind'].ne('ТР')]
        p['well'], p['year'] = p.well.astype(str), pd.to_numeric(p.year, errors='coerce')
        stop = pd.to_datetime(p['end'], errors='coerce') if 'end' in p else pd.Series(pd.NaT, index=p.index)
        p['when'] = stop.fillna(pd.to_datetime(p['start'], errors='coerce'))
        by = p.dropna(subset=['when', 'year']).groupby(['well', p.year.astype('Int64')]).when.max()
        for i, r in w.iterrows():
            hit = by.get((r.well, r.year))
            if hit is not None and pd.notna(hit):
                w.at[i, 'date'], w.at[i, 'dated'] = hit, True
    return w[cols].reset_index(drop=True)


def study_rows(gdi: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Все исследования с расходом при опорном ΔP² и надёжностью: well, date, season, reliable, q_ref (``_productivity_rows``)."""
    if gdi is None or gdi.empty:
        return pd.DataFrame(columns=['well', 'date', 'season', 'reliable', 'q_ref'])
    d = legacy.prepare(gdi)
    d['season'] = d.season.fillna('').astype(str)
    studies = legacy.analyze(d, threshold)
    keys = d[legacy.KEYS + ['season']].drop_duplicates(legacy.KEYS)
    studies = studies.merge(keys, on=legacy.KEYS, how='left')
    rows = _productivity_rows(d, studies, threshold)
    rows = rows.merge(keys, on=legacy.KEYS, how='left')
    rows['well'] = rows.well.astype(str)
    rows['reliable'] = rows.reliable.eq('да')
    return rows


def verdict_of(before: float, after: float, limit: float) -> tuple[str, float]:
    if not (before and np.isfinite(before) and np.isfinite(after)):
        return VERDICT_FEW, np.nan
    change = (after / before - 1) * 100
    return (VERDICT_UP if change > limit else VERDICT_DOWN if change < -limit else VERDICT_SAME), change


NO_COMPARE = 'Нет сравнения'
CAT_OFF_PROGRAM = 'Вне программы ГДИ'
PERIOD_NEUTRAL, PERIOD_INJ, PERIOD_WD = 'Нейтральный период', 'Сезон закачки', 'Сезон отбора'
SLICES = (PERIOD_WD, PERIOD_INJ, PERIOD_NEUTRAL)          # отбор — основной срез; закачка и нейтральные периоды вместе — ГДИ после КРС
SLICE_ALIASES = {'отбор': PERIOD_WD, 'закачка': PERIOD_INJ, 'нейтральный': PERIOD_NEUTRAL}
_KIND_NAMES = {'injection': PERIOD_INJ, 'withdrawal': PERIOD_WD, 'none': PERIOD_NEUTRAL}


def period_of(date, schedule: str | None, start: int = 11, end: int = 4) -> str:
    """Период, в который проведено ГДИ: по расписанию периодов проекта (inj / prod / none); без расписания — по месяцам сезона отбора
    (с ``start`` по ``end``), остальное закачка; нейтральных периодов без расписания нет. Подсказка, период скважины правится вручную."""
    if pd.isna(date):
        return ''
    if schedule and str(schedule).strip():
        try:
            phases = sorted(season_rules.parse_schedule(schedule)[0])
        except ValueError:
            phases = []
        mine = [k for d, k in phases if pd.Timestamp(d) <= date]
        if mine:
            return _KIND_NAMES.get(mine[-1], PERIOD_NEUTRAL)
    m = date.month
    return PERIOD_WD if (m >= start or m <= end if start > end else start <= m <= end) else PERIOD_INJ



def program_groups(program: pd.DataFrame | None, seasons: list[str]) -> dict[str, tuple[str, str]]:
    """Скважина → (группа плана ГДИ, формулировка программы). Сезоны программы сверяются с выбранными; нет совпадений — вся программа.
    Несколько причин у скважины — берётся первая по порядку программы (ремонт раньше, чем «давно не проводились»)."""
    if program is None or program.empty:
        return {}
    p = program.assign(well=program.well.astype(str))
    wanted = {_season_key(x) for x in seasons}
    keep = p[p.season.map(_season_key).isin(wanted)]
    p = keep if len(keep) else p
    out: dict[str, tuple[str, str]] = {}
    for r in p.itertuples():
        out.setdefault(r.well, (PROGRAM_REASONS.get(r.reason_kind, r.reason or 'Другое'), f'программа ГДИ {r.season}: {r.stage}, {r.reason}'))
    return out


def season_table(rows: pd.DataFrame, seasons: list[str], limit: float, years: float, rep: pd.DataFrame,
                 manual: dict[str, str], groups: dict[str, tuple[str, str]] | None = None,
                 schedule: str | None = None, season_months: tuple[int, int] = (11, 4), period_manual: dict[str, str] | None = None) -> pd.DataFrame:
    """По скважине сезона: вердикт, изменение Q, даты сравнения, категория (авто и итоговая) и причина."""
    out = []
    if rows.empty:
        return pd.DataFrame()
    inside = rows[rows.season.isin(seasons)].copy()
    forced = {w: normalize_slice(v) for w, v in (period_manual or {}).items()}
    inside['slice'] = [forced.get(w) or period_of(d, schedule, *season_months) for w, d in zip(inside.well, inside.date)]
    pairs = sorted(inside[['well', 'slice']].drop_duplicates().itertuples(index=False), key=lambda r: (well_key(r.well), SLICES.index(r.slice) if r.slice in SLICES else 9))
    for well, slice_name in pairs:
        g = rows[rows.well.eq(well)].sort_values('date', kind='stable')
        part = inside[inside.well.eq(well) & inside['slice'].eq(slice_name)]
        mine = g[g.date.isin(part.date) & g.season.isin(seasons)]          # ГДИ скважины в этом периоде выбранных сезонов
        first_in = mine.date.min()
        ok = g[g.reliable & g.q_ref.notna()].drop_duplicates('date', keep='last')
        ok_in = ok[ok.date.isin(mine.date)]
        last = ok_in.iloc[-1] if len(ok_in) else None
        base = ok[ok.date < first_in]
        base = base.iloc[-1] if len(base) else (ok_in.iloc[0] if len(ok_in) > 1 else None)
        verdict, change = (verdict_of(base.q_ref, last.q_ref, limit) if last is not None and base is not None and base.date < last.date
                           else (VERDICT_FEW, np.nan))
        earlier = g[g.date < first_in]
        prev_any = earlier.date.max() if len(earlier) else pd.NaT
        gap = (first_in - prev_any).days / 365.25 if pd.notna(prev_any) else np.nan
        last_date = mine.date.max()
        low = base.date if (base is not None and base.date < first_in) else (prev_any if pd.notna(prev_any) else first_in - pd.Timedelta(days=365))
        mine_rep = rep[rep.well.eq(well) & rep.date.gt(low) & rep.date.le(last_date + pd.Timedelta(days=1))] if not rep.empty else rep
        if len(mine_rep):
            latest = mine_rep.sort_values('date').iloc[-1]
            auto = f'После КРС: {latest.kind}'
            reason = '; '.join(f'{r.work_type or "тип не указан"}, {r.year} г.' for r in mine_rep.itertuples())
            krs_year = int(latest.year)
        elif pd.notna(gap) and gap > years:
            auto, reason, krs_year = f'ГДИ не делали более {years:g} лет', f'предыдущее исследование {prev_any:%d.%m.%Y}, перерыв {gap:.1f} г.', 0
        elif pd.isna(gap):
            auto, reason, krs_year = CAT_FIRST, 'исследований до сезона нет', 0
        else:
            before = rep[rep.well.eq(well)] if not rep.empty else rep
            note = (f'; в данных КРС по скважине {len(before)} ремонтов, последний {int(before.year.max())} г., вне окна сравниваемых ГДИ'
                    if len(before) else '; в данных КРС по скважине ремонтов нет')
            auto, reason, krs_year = CAT_NO_REPAIR, 'ремонтов между сравниваемыми ГДИ нет' + note, 0
        if groups is not None:
            plan_cat, plan_reason = groups.get(well, (CAT_OFF_PROGRAM, 'скважины нет в загруженной программе ГДИ'))
            others = f'; данные КРС: {auto.lower()} ({reason})' if len(mine_rep) else ''
            auto, reason = plan_cat, plan_reason + others
        out.append({'well': well, 'verdict': verdict, 'change': change, 'slice': slice_name, 'slice_edited': 'вручную' if well in (period_manual or {}) else '',
                    'prev_date': base.date if base is not None else pd.NaT, 'last_date': last.date if last is not None else last_date,
                    'q_prev': base.q_ref if base is not None else np.nan, 'q_last': last.q_ref if last is not None else np.nan,
                    'auto': auto, 'category': manual.get(well, auto), 'edited': 'вручную' if well in manual else '',
                    'krs_year': krs_year or np.nan, 'reason': reason})
    return pd.DataFrame(out)


def _years_of(x) -> set[int]:
    return {int(x)} if isinstance(x, (int, np.integer)) else {int(v) for v in x}


def _years_label(x) -> str:
    return ', '.join(str(v) for v in sorted(_years_of(x))) + ' г.'


def repair_effect_chart(table: pd.DataFrame, year) -> Chart | None:
    """Эффект ремонта по видам КРС: ящик с усами по изменению Q при опорном ΔP² (до → после). Под графиком число скважин, медиана и номера скважин.
    Только скважины с надёжными ГДИ до и после; остальные видны в таблице ремонтов."""
    t = table[table.change.notna()] if not table.empty else table
    if t.empty:
        return None
    kinds = sorted(t.kind.unique())
    stats, cells, wells = [], [[], []], []
    for k in kinds:
        v = t[t.kind.eq(k)].change.to_numpy(float)
        q1, med, q3 = np.percentile(v, [25, 50, 75])
        stats.append([float(v.min()), float(q1), float(med), float(q3), float(v.max())])
        cells[0].append(str(len(v)))
        cells[1].append(f'{med:+.1f}')
        wells.append(sorted(t[t.kind.eq(k)].well.astype(str), key=well_key))
    chart = Chart('gdi-summary-repair-effect', f'Эффект ремонта по видам КРС · {_years_label(year)}: изменение Q при опорном ΔP², %',
                  Axis('Вид ремонта', scale='category', categories=kinds), Axis('Изменение Q', '%'))
    chart.series.append(Series('Изменение Q после ремонта', kinds, stats, 'box', color=VERDICT_COLORS[VERDICT_SAME]))
    chart.table = ChartTable(['Скважин', 'Медиана, %'], kinds, cells, swatches=False, wells=[wells, [[] for _ in kinds]])
    return chart


PATH_STEPS = ('До КРС', 'После КРС', 'Следующий отбор')


NEXT_WINDOW_DAYS = 548        # «следующий отбор» — первое надёжное ГДИ периода отбора не позже 18 месяцев после ремонта

FOLLOW_BOTH, FOLLOW_AFTER, FOLLOW_NEXT, FOLLOW_NONE = ('ГДИ после КРС и в следующем отборе', 'только после КРС', 'только в следующем отборе', 'нет ГДИ после ремонта')
FOLLOW_COLORS = {FOLLOW_BOTH: '#2e9d57', FOLLOW_AFTER: '#6aa7e0', FOLLOW_NEXT: '#e0a030', FOLLOW_NONE: '#c0504d'}


def follow_up(change_after: float, change_next: float, limit: float) -> str:
    """Подсказка-вывод по эффекту ремонта: после КРС и в следующем отборе (изменение Q к ГДИ до ремонта, порог ``limit``, %)."""
    a, n = (None if not np.isfinite(v) else (1 if v > limit else -1 if v < -limit else 0) for v in (change_after, change_next))
    if a is None and n is None:
        return 'нет ГДИ после ремонта: кандидат на исследование'
    if n is None:
        return 'в следующем отборе не исследована: кандидат на исследование' + ('' if a is None else f'; после КРС {"улучшение" if a > 0 else "ухудшение" if a < 0 else "без изменений"}')
    if a is None:
        return f'после КРС не исследована; в следующем отборе {"улучшение" if n > 0 else "ухудшение" if n < 0 else "без изменений"} к ГДИ до ремонта'
    if a > 0 and n > 0:
        return 'эффект ремонта подтверждён в следующем отборе'
    if a > 0 and n <= 0:
        return 'эффект после КРС не сохранился в следующем отборе'
    if a <= 0 and n > 0:
        return 'эффект проявился только в следующем отборе'
    return 'эффекта нет' if n == 0 and a == 0 else ('ухудшение после КРС и в следующем отборе' if n < 0 and a < 0 else 'без устойчивого эффекта')


def repair_path_table(rows: pd.DataFrame, rep: pd.DataFrame, year, schedule: str | None = None, start: int = 11, end: int = 4,
                      limit: float = 5.0) -> pd.DataFrame:
    """Путь скважины после каждого ремонта выбранных лет: Q при опорном ΔP² до КРС → первое надёжное ГДИ после КРС вне отбора (закачка/нейтральный период) →
    первое надёжное ГДИ следующего периода отбора. Даты ремонта — только фактические (справка КРС) или 1 июля года. Изменения — к ГДИ до ремонта, %."""
    out = []
    for r in rep[rep.year.isin(_years_of(year))].sort_values(['well', 'date'], key=lambda c: c.map(well_key) if c.name == 'well' else c).itertuples():
        ok = rows[rows.well.eq(r.well) & rows.reliable & rows.q_ref.notna()].drop_duplicates('date', keep='last').sort_values('date')
        before, later = ok[ok.date <= r.date], ok[ok.date > r.date]
        kinds = later.date.map(lambda d: period_of(d, schedule, start, end)) if len(later) else pd.Series(dtype=str)
        after, nxt = later[kinds.ne(PERIOD_WD).to_numpy()] if len(later) else later, later[kinds.eq(PERIOD_WD).to_numpy()] if len(later) else later
        nxt = nxt[nxt.date <= r.date + pd.Timedelta(days=NEXT_WINDOW_DAYS)]
        b, a, n = (x.iloc[0 if x is not before else -1] if len(x) else None for x in (before, after, nxt))
        qb = b.q_ref if b is not None else np.nan
        ca = (a.q_ref / qb - 1) * 100 if a is not None and qb else np.nan
        cn = (n.q_ref / qb - 1) * 100 if n is not None and qb else np.nan
        stage = (FOLLOW_BOTH if a is not None and n is not None else FOLLOW_AFTER if a is not None else FOLLOW_NEXT if n is not None else FOLLOW_NONE)
        out.append({'well': r.well, 'kind': r.kind, 'year': int(r.year), 'repair_date': r.date, 'date_note': '' if r.dated else 'только год (1 июля)',
                    'date_before': b.date if b is not None else pd.NaT, 'q_before': qb,
                    'date_after': a.date if a is not None else pd.NaT, 'q_after': a.q_ref if a is not None else np.nan, 'change_after': ca,
                    'date_next': n.date if n is not None else pd.NaT, 'q_next': n.q_ref if n is not None else np.nan, 'change_next': cn,
                    'follow': stage, 'conclusion': follow_up(ca, cn, limit) if b is not None else 'нет надёжного ГДИ до ремонта: сравнить нельзя'})
    return pd.DataFrame(out)


def repair_path_chart(table: pd.DataFrame, year) -> Chart | None:
    """Линия на скважину: до КРС → после КРС → следующий отбор (категории общей оси ядра, пропуск — разрыв линии)."""
    if table.empty or not table[['q_before', 'q_after', 'q_next']].notna().any(axis=None):
        return None
    chart = Chart('gdi-summary-repair-path', f'Q при опорном ΔP² после КРС {_years_label(year)}: до ремонта, после, в следующий отбор',
                  Axis('Исследование', scale='category', categories=list(PATH_STEPS)), Axis('Q при опорном ΔP²', UNITS['q_gdi']))
    for r in table.itertuples():
        y = np.array([r.q_before, r.q_after, r.q_next], float)
        if np.isfinite(y).sum():
            chart.series.append(Series(f'№ {r.well} · {r.kind}', list(PATH_STEPS), y, 'line', markers=True))
    return chart


def repair_year_table(rows: pd.DataFrame, rep: pd.DataFrame, year, limit: float) -> pd.DataFrame:
    """Для каждого ремонта года: ГДИ до (последнее надёжное) и после (первое надёжное) и вывод."""
    out = []
    for r in rep[rep.year.isin(_years_of(year))].sort_values(['well', 'date'], key=lambda c: c.map(well_key) if c.name == 'well' else c).itertuples():
        ok = rows[rows.well.eq(r.well) & rows.reliable & rows.q_ref.notna()].drop_duplicates('date', keep='last').sort_values('date')
        before, after = ok[ok.date <= r.date], ok[ok.date > r.date]
        b, a = (before.iloc[-1] if len(before) else None), (after.iloc[0] if len(after) else None)
        if a is None:
            studied = rows[rows.well.eq(r.well) & rows.date.gt(r.date)]
            verdict, change = NO_AFTER, np.nan
            comment = 'есть исследования после ремонта, но ненадёжные' if len(studied) else ''
        elif b is None:
            verdict, change, comment = NO_BEFORE, np.nan, ''
        else:
            verdict, change = verdict_of(b.q_ref, a.q_ref, limit)
            comment = ''
        out.append({'well': r.well, 'kind': r.kind, 'work_type': r.work_type, 'repair_date': r.date,
                    'date_note': '' if r.dated else 'только год (1 июля)', 'before': b.date if b is not None else pd.NaT,
                    'after': a.date if a is not None else pd.NaT, 'q_before': b.q_ref if b is not None else np.nan,
                    'q_after': a.q_ref if a is not None else np.nan, 'change': change, 'verdict': verdict, 'comment': comment})
    return pd.DataFrame(out)


STATUS_DONE, STATUS_WEAK, STATUS_NONE = 'выполнено', 'выполнено, но ненадёжное', 'не выполнено'
STATUS_MANUAL = 'выполнено (отмечено вручную)'
PROGRAM_STATUSES = (STATUS_DONE, STATUS_WEAK, STATUS_MANUAL, STATUS_NONE)
PROGRAM_COLORS = {STATUS_DONE: '#2e8b57', STATUS_WEAK: '#e0a030', STATUS_MANUAL: '#3f7fbf', STATUS_NONE: '#c0504d'}
PROGRAM_REASONS = {'filter': 'После КР: замена фильтра', 'coil': 'После КР: промывка и СКО', 'krs_plan': 'КР в сезоне закачки',
                   'gap': 'ГДИ давно не проводились', 'other': 'Другое'}


def _season_key(value) -> str:
    return '-'.join(re.findall(r'\d{4}', str(value)))


def program_table(rows: pd.DataFrame, program: pd.DataFrame | None, seasons: list[str], done_manual: dict[str, str] | None = None) -> pd.DataFrame:
    """Программа ГДИ против факта: по скважине программы — есть ли исследование в сезоне программы и надёжное ли оно.
    Сезон программы пуст или не совпал ни с одним выбранным — берутся строки программы всех сезонов выбранных (сверка по полю «Сезон ГДИ»)."""
    cols = ['well', 'group', 'season', 'stage', 'reason_kind', 'reason', 'status', 'status_note', 'last_date', 'krs_injection']
    if program is None or program.empty:
        return pd.DataFrame(columns=cols)
    p = program.copy()
    p['well'] = p.well.astype(str)
    wanted = {_season_key(x) for x in seasons}
    keep = p[p.season.map(_season_key).isin(wanted)]
    p = keep if len(keep) else p
    out = []
    for r in p.itertuples():
        mine = rows[rows.well.eq(r.well) & rows.season.map(_season_key).eq(_season_key(r.season))] if not rows.empty else rows
        if mine.empty:
            status, last = STATUS_NONE, pd.NaT
        else:
            last = mine.date.max()
            status = STATUS_DONE if (mine.reliable & mine.q_ref.notna()).any() else STATUS_WEAK
        note = ''
        if r.well in (done_manual or {}) and status == STATUS_NONE:
            status, note = STATUS_MANUAL, done_manual[r.well] or 'причина не указана'
        elif r.well in (done_manual or {}):
            note = 'отмечено вручную: ' + (done_manual[r.well] or 'причина не указана')
        out.append({'well': r.well, 'group': r.group, 'season': r.season, 'stage': r.stage, 'reason_kind': PROGRAM_REASONS.get(r.reason_kind, r.reason),
                    'reason': r.reason, 'status': status, 'status_note': note, 'last_date': last, 'krs_injection': 'да' if r.krs_injection else ''})
    return pd.DataFrame(out, columns=cols).sort_values(['stage', 'reason_kind', 'well'], key=lambda c: c.map(well_key) if c.name == 'well' else c).reset_index(drop=True)


def program_block(result: Result, rows: pd.DataFrame, program: pd.DataFrame | None, seasons: list[str],
                  done_manual: dict[str, str] | None = None) -> None:
    """Выполнение годовой программы ГДИ: сводка, гистограмма по причинам, таблица скважин (загрузка — вкладка «Импорт», «Программа ГДИ»)."""
    if program is None or program.empty:
        result.notes.append(Note(EMPTY_PROGRAM))
        return
    table = program_table(rows, program, seasons, done_manual)
    if table.empty:
        return
    done = int(table.status.eq(STATUS_DONE).sum())
    result.summary += [Stat('В программе ГДИ', str(len(table)), f'выполнено: {done + int(table.status.eq(STATUS_MANUAL).sum())}'),
                       Stat('Не выполнено по программе', str(int(table.status.eq(STATUS_NONE).sum())), 'Кандидаты на исследование')]
    cats = list(dict.fromkeys(table.reason_kind))
    by = {(c, v): int(((table.reason_kind == c) & (table.status == v)).sum()) for c in cats for v in PROGRAM_STATUSES}
    coverage_block(result, table)
    result.charts.append(stacked('gdi-summary-program', 'Выполнение программы ГДИ по причинам', cats, by, PROGRAM_STATUSES, PROGRAM_COLORS, 'Причина',
                                   wells=members(table, 'reason_kind', cats, PROGRAM_STATUSES, 'status')))
    result.tables.append(Table('gdi-summary-program-wells', 'Программа ГДИ: выполнение по скважинам', table, [
        Column('well', 'Скважина'), Column('group', 'ГСП'), Column('stage', 'Этап'), Column('reason_kind', 'Причина'),
        Column('krs_injection', 'КР в сезоне закачки'), Column('status', 'Выполнение'), Column('status_note', 'Причина отметки'), Column('last_date', 'Последнее ГДИ сезона', kind='date'),
        Column('reason', 'Формулировка программы')],
        note='Программа загружается во вкладке «Импорт» (файл Word). Сверка — по сезону программы: есть ли исследование этой скважины в сезоне. '
             'Подсказка: решает инженер.'))


MATRIX_NONE, MATRIX_PLAN, MATRIX_WEAK, MATRIX_OK = 0, 1, 2, 3


def season_start_year(season) -> int | None:
    m = re.search(r'(\d{4})', str(season))
    return int(m.group(1)) if m else None


def season_matrix(rows: pd.DataFrame, program: pd.DataFrame | None, rep: pd.DataFrame, done_manual: dict[str, str] | None = None
                  ) -> tuple[list[str], list[str], list[list[float | None]], list[list[str]]]:
    """Скважина × сезон: надёжное ГДИ, только ненадёжное, плановое не выполнено, нет данных; «+КРС» — ремонт в год начала сезона (лето перед сезоном).
    Сезоны и скважины — все, что есть в данных ГДИ и в программе; ненадёжные видны (последнее слово за инженером), плановые даты КР не используются."""
    keyed = rows.assign(sk=rows.season.map(_season_key)) if not rows.empty else rows
    planned = {}
    if program is not None and not program.empty:
        p = program.assign(well=program.well.astype(str), sk=program.season.map(_season_key))
        planned = {(r.well, r.sk): r for r in p.itertuples()}
    seasons = sorted({k for k in (list(keyed.sk) if not rows.empty else []) + [k for _, k in planned] if k})
    wells = sorted({w for w in (list(rows.well) if not rows.empty else []) + [w for w, _ in planned]}, key=well_key)
    manual = done_manual or {}
    values: list[list[float | None]] = []
    texts: list[list[str]] = []
    for w in wells:
        vrow, trow = [], []
        for sk in seasons:
            mine = keyed[keyed.well.eq(w) & keyed.sk.eq(sk)] if not rows.empty else rows
            year = season_start_year(sk)
            fixed = bool(len(rep) and year is not None and (rep.well.eq(w) & rep.year.eq(year)).any())
            if len(mine):
                ok = (mine.reliable & mine.q_ref.notna()).any()
                v, t = (MATRIX_OK, '✓') if ok else (MATRIX_WEAK, '!')
            elif (w, sk) in planned:
                v, t = (MATRIX_OK, '✓ вручную') if w in manual else (MATRIX_PLAN, 'план')
            else:
                v, t = None, ''
            if fixed:
                v, t = (v if v is not None else MATRIX_NONE), (t + ' +КРС').strip()
            vrow.append(None if v is None else float(v))
            trow.append(t)
        values.append(vrow)
        texts.append(trow)
    return wells, seasons, values, texts


def matrix_block(result: Result, rows: pd.DataFrame, program: pd.DataFrame | None, rep: pd.DataFrame, done_manual: dict[str, str] | None = None) -> None:
    """Тепловая карта «скважина × сезон» общим ядром графиков (HeatMap) и таблица с теми же числами."""
    from .an_charts import heat_chart
    wells, seasons, values, texts = season_matrix(rows, program, rep, done_manual)
    if not wells or not seasons:
        return
    chart = heat_chart('gdi-summary-season-matrix', 'Скважина × сезон: ГДИ выполнено, ненадёжное, не выполнено по плану, был КРС',
                       [f'№ {w}' for w in wells], seasons, values, texts, '0 КРС без ГДИ · 1 план не выполнен · 2 ненадёжное · 3 надёжное', float(MATRIX_OK), '')
    result.charts.append(chart)
    names = {MATRIX_NONE: 'КРС, ГДИ нет', MATRIX_PLAN: 'план не выполнен', MATRIX_WEAK: 'ненадёжное', MATRIX_OK: 'надёжное'}
    frame = pd.DataFrame([{'well': w, **{sk: (names.get(int(v), '') if v is not None else '') + (' +КРС' if t.endswith('КРС') and v is not None and v > MATRIX_NONE else '')
                                          for sk, v, t in zip(seasons, vr, tr)}} for w, vr, tr in zip(wells, values, texts)])
    result.tables.append(Table('gdi-summary-season-matrix-table', 'Скважина × сезон: состояние ГДИ', frame,
                               [Column('well', 'Скважина')] + [Column(sk, sk) for sk in seasons],
                               note='«+КРС» — ремонт по справке КРС в год начала сезона. Ненадёжные исследования в расчёты не входят, но показаны: решает инженер.'))


MONTHS_RU = ('янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек')


def coverage_by_month(table: pd.DataFrame) -> tuple[list[str], list[int], list[float]]:
    """Охват программы по месяцам: сколько скважин программы исследовано в месяц (по последнему ГДИ сезона) и накопленная доля от программы, %."""
    done = table[table.last_date.notna() & table.status.isin([STATUS_DONE, STATUS_WEAK])]
    if done.empty or table.empty:
        return [], [], []
    months = pd.period_range(done.last_date.min(), done.last_date.max(), freq='M')
    counts = done.last_date.dt.to_period('M').value_counts()
    labels = [f'{MONTHS_RU[m.month - 1]} {m.year}' for m in months]
    n = [int(counts.get(m, 0)) for m in months]
    share = list(np.cumsum(n) / len(table) * 100)
    return labels, n, share


def coverage_block(result: Result, table: pd.DataFrame) -> None:
    """Охват программы ГДИ по ГСП (стопка по статусу, номера скважин под графиком) и по месяцам (столбцы + накопленная доля)."""
    tab = table.assign(group=table.group.fillna('').astype(str).replace('', 'без ГСП'))
    groups = sorted(tab.group.unique(), key=lambda g: (g == 'без ГСП', g))
    by = {(g, v): int((tab.group.eq(g) & tab.status.eq(v)).sum()) for g in groups for v in PROGRAM_STATUSES}
    result.charts.append(stacked('gdi-summary-program-groups', 'Охват программы ГДИ по ГСП', groups, by, PROGRAM_STATUSES, PROGRAM_COLORS, 'ГСП',
                                 wells=members(tab, 'group', groups, PROGRAM_STATUSES, by='status')))
    labels, n, share = coverage_by_month(table)
    if labels:
        chart = Chart('gdi-summary-program-months', 'Охват программы ГДИ по месяцам: исследовано в месяц и накопленная доля программы',
                      Axis('Месяц', scale='category', categories=labels), Axis('Скважин', 'ед.', from_zero=True),
                      y2=Axis('Накопленная доля программы', '%', from_zero=True, maximum=100))
        chart.series += [Series('Исследовано в месяц', labels, np.array(n, float), 'bar', color='#2e9d57'),
                         Series('Накопленная доля программы', labels, np.array(share, float), 'line', markers=True, color='#111827', axis='y2')]
        result.charts.append(chart)


def count_matrix(frame: pd.DataFrame, rows_key: str, cols: tuple[str, ...], col_key: str = 'verdict') -> pd.DataFrame:
    """Таблица «категория × вывод»: число скважин и их список."""
    items = []
    for cat, g in frame.groupby(rows_key, sort=False):
        item = {'category': cat, 'total': len(g)}
        for v in cols:
            wells = sorted(g[g[col_key].eq(v)].well, key=well_key)
            item[v], item[f'{v}|wells'] = len(wells), ', '.join(wells)
        items.append(item)
    return pd.DataFrame(items)


def members(table: pd.DataFrame, column: str, cats: list[str], names: tuple[str, ...], by: str = 'verdict') -> dict[tuple[str, str], list[str]]:
    """Номера скважин на пересечении «категория × вывод» (для ячеек таблицы под графиком: числа или номера по выбору инженера)."""
    return {(c, v): sorted(table[table[column].eq(c) & table[by].eq(v)].well.astype(str), key=well_key) for c in cats for v in names}


def stacked(cid: str, title: str, cats: list[str], by: dict[tuple[str, str], int], stack_names: tuple[str, ...], colors: dict[str, str],
            x_label: str, share: bool = False, wells: dict[tuple[str, str], list[str]] | None = None) -> Chart:
    """Гистограмма-стопка: столбец на категорию, сегмент на вывод; в сегменте число скважин (``share`` — доли от столбца)."""
    chart = Chart(cid, title, Axis(x_label, scale='category', categories=cats),
                  Axis('Доля скважин' if share else 'Скважин', '%' if share else 'ед.', from_zero=True))
    totals = [sum(by.get((c, v), 0) for v in stack_names) for c in cats]
    for v in stack_names:
        n = np.array([by.get((c, v), 0) for c in cats], float)
        y = np.array([x / t * 100 if share and t else x for x, t in zip(n, totals)], float)
        chart.series.append(Series(v, cats, y, 'bar', stack='verdict', color=colors[v], segments=[str(int(x)) if x else '' for x in n],
                                   labels=[f'{int(x)} из {t} скв.' for x, t in zip(n, totals)]))
    chart.table = ChartTable([s.name for s in chart.series], cats, [[str(int(by.get((c, v), 0))) for c in cats] for v in stack_names],
                             wells=[[(wells or {}).get((c, v), []) for c in cats] for v in stack_names] if wells else [])
    chart.callouts = 'dot'          # как в «Авторском надзоре»: узкий сегмент — точки по числу без выноски, числа в таблице под графиком
    return chart


def grouped(cid: str, title: str, cats: list[str], by: dict[tuple[str, str], int]) -> Chart:
    """Столбцы рядом: по группе вывода — ряд, по категории — позиция (взгляд «что именно улучшилось»)."""
    chart = Chart(cid, title, Axis('Категория', scale='category', categories=cats), Axis('Скважин', 'ед.', from_zero=True))
    for v in VERDICTS[:3]:
        chart.series.append(Series(v, cats, np.array([by.get((c, v), 0) for c in cats], float), 'bar', color=VERDICT_COLORS[v]))
    return chart


DEFAULT_EDGES = '-30, -15, -5, 5, 15, 30'


def parse_edges(text) -> list[float]:
    """Границы корзин «-30, -15, -5, 5, 15, 30»; пусто — по умолчанию. Не числа и повторы отбрасываются, порядок по возрастанию."""
    vals = []
    for part in re.split(r'[;\s]+', str(text or DEFAULT_EDGES).replace(',', ' ')):
        try:
            vals.append(float(part.replace('\u2212', '-')))
        except ValueError:
            continue
    edges = sorted(set(vals))
    return edges if len(edges) >= 2 else parse_edges(DEFAULT_EDGES)


def _num(v: float) -> str:
    return f'{v:g}'


def change_histogram(table: pd.DataFrame, limit: float, edges: list[float] | None = None, cid: str = 'gdi-summary-hist',
                     suffix: str = '') -> Chart | None:
    """Распределение изменения Q по скважинам: корзины между заданными границами (по умолчанию укрупнённые, «−5…5» одной корзиной), края — «меньше» и «больше».
    ``suffix`` — группа плана ГДИ в заголовке; цвет корзины по порогу изменения."""
    c = table.change.dropna()
    nocmp = int(table.change.isna().sum())          # скважины без сравнения (одно надёжное ГДИ): видны отдельным столбцом, итог сходится с другими графиками
    if c.empty and not nocmp:
        return None
    edges = edges or parse_edges('')
    labels = [f'< {_num(edges[0])}'] + [f'{_num(a)}…{_num(b)}' for a, b in zip(edges, edges[1:])] + [f'> {_num(edges[-1])}']
    idx = np.searchsorted(edges, c.to_numpy(float), side='right')
    named = 'well' in table
    in_bin = [sorted(table.loc[c.index[idx == k], 'well'].astype(str), key=well_key) for k in range(len(labels))] if named else []
    counts = np.bincount(idx, minlength=len(labels))[:len(labels)].astype(float)
    step = (edges[-1] - edges[0]) / max(len(edges) - 1, 1)
    mids = [edges[0] - step / 2] + [(a + b) / 2 for a, b in zip(edges, edges[1:])] + [edges[-1] + step / 2]
    kinds = [VERDICT_DOWN if m < -limit else VERDICT_UP if m > limit else VERDICT_SAME for m in mids]
    if nocmp:
        labels, counts, kinds = labels + [NO_COMPARE], np.append(counts, float(nocmp)), kinds + [VERDICT_FEW]
        if named:
            in_bin.append(sorted(table.loc[table.change.isna(), 'well'].astype(str), key=well_key))
    title = (f'Распределение изменения расхода при опорном ΔP² по скважинам сезона · {len(table)} скв.'
             + (f' · {suffix}' if suffix else ''))
    chart = Chart(cid, title, Axis('Изменение Q, %', scale='category', categories=labels), Axis('Скважин', 'ед.', from_zero=True))
    for kind in dict.fromkeys(kinds):        # по серии на цвет: в каждой — все корзины (так график и выгружается)
        own = np.array([n if k == kind else 0.0 for n, k in zip(counts, kinds)])
        chart.series.append(Series(kind, labels, own, 'bar', stack='hist', color=VERDICT_COLORS[kind],
                                   segments=[str(int(n)) if n else '' for n in own]))
    chart.table = ChartTable(['Скважин'], labels, [[str(int(n)) for n in counts]], wells=[in_bin] if named else [], swatches=False)
    chart.callouts = 'dot'          # узкий столбец — точки по числу без выноски, числа в таблице под графиком
    return chart


AGE_BINS = ((1, 'до 1 года'), (2, '1–2 года'), (3, '2–3 года'), (5, '3–5 лет'), (np.inf, 'больше 5 лет'))
AGE_NONE = 'надёжного ГДИ нет'
CAND_REPAIR, CAND_NONE = 'ремонт после последнего ГДИ', 'ремонта после ГДИ нет'


def age_table(rows: pd.DataFrame, rep: pd.DataFrame, program: pd.DataFrame | None = None, seasons: list[str] | None = None,
              today=None) -> pd.DataFrame:
    """Давность последнего надёжного ГДИ скважины (от даты ``today``, по умолчанию — последнее ГДИ в данных) и ремонт после него.
    Кандидат на исследование — ремонт по справке КРС (фактическая дата) позже последнего надёжного ГДИ; подсказка, решает инженер."""
    if rows.empty:
        return pd.DataFrame()
    now = pd.Timestamp(today) if today is not None else rows.date.max()
    inprog = set()
    if program is not None and not program.empty:
        wanted = {_season_key(x) for x in (seasons or [])}
        p = program[program.season.map(_season_key).isin(wanted)] if wanted else program
        inprog = set(p.well.astype(str))
    out = []
    for w in sorted(rows.well.unique(), key=well_key):
        ok = rows[rows.well.eq(w) & rows.reliable & rows.q_ref.notna()]
        last = ok.date.max() if len(ok) else pd.NaT
        mine = rep[rep.well.eq(w)] if not rep.empty else rep
        after = mine[mine.date.gt(last)] if pd.notna(last) and len(mine) else mine.iloc[0:0]
        if pd.isna(last):
            age, label = np.nan, AGE_NONE
        else:
            age = (now - last).days / 365.25
            label = next(name for lim, name in AGE_BINS if age < lim)
        rep_row = after.sort_values('date').iloc[-1] if len(after) else None
        out.append({'well': w, 'last_date': last, 'age': age, 'age_bin': label,
                    'candidate': CAND_REPAIR if rep_row is not None else CAND_NONE,
                    'repair_kind': rep_row.kind if rep_row is not None else '', 'repair_year': int(rep_row.year) if rep_row is not None else np.nan,
                    'in_program': 'да' if w in inprog else ''})
    return pd.DataFrame(out)


def age_block(result: Result, rows: pd.DataFrame, rep: pd.DataFrame, program: pd.DataFrame | None, seasons: list[str]) -> None:
    table = age_table(rows, rep, program, seasons)
    if table.empty:
        return
    cats = [name for _, name in AGE_BINS] + [AGE_NONE]
    cats = [c for c in cats if c in set(table.age_bin)]
    names = (CAND_REPAIR, CAND_NONE)
    by = {(c, v): int((table.age_bin.eq(c) & table.candidate.eq(v)).sum()) for c in cats for v in names}
    colors = {CAND_REPAIR: '#d64545', CAND_NONE: '#8c96a3'}
    result.charts.append(stacked('gdi-summary-age', 'Давность последнего надёжного ГДИ и ремонт после него', cats, by, names, colors, 'Давность ГДИ',
                                 wells=members(table, 'age_bin', cats, names, by='candidate')))
    cand = table[table.candidate.eq(CAND_REPAIR)]
    result.summary.append(Stat('Ремонт после последнего ГДИ', str(len(cand)), 'Кандидаты на исследование'))
    result.tables.append(Table('gdi-summary-age-table', 'Давность ГДИ и кандидаты на исследование после ремонта', table, [
        Column('well', 'Скважина'), Column('last_date', 'Последнее надёжное ГДИ', kind='date'), Column('age', 'Давность', 'лет', 1, 'number'),
        Column('age_bin', 'Интервал'), Column('candidate', 'Кандидат'), Column('repair_kind', 'Вид ремонта'),
        Column('repair_year', 'Год ремонта', kind='number', decimals=0), Column('in_program', 'В программе ГДИ')],
        note='Давность — от последнего ГДИ в данных. Ненадёжные исследования не считаются «последним», но скважина остаётся в таблице. '
             'Даты ремонта — фактические (справка КРС); кандидат — подсказка, решает инженер.'))


def well_card_table(gdi: pd.DataFrame, rows: pd.DataFrame, well: str, threshold: float) -> pd.DataFrame:
    """Все исследования скважины по сезонам: дата, сезон, Q при опорном ΔP², a, b (МПа²/(тыс. м³/сут) и т. д. — как в расчёте), надёжность."""
    cols = ['date', 'season', 'q_ref', 'a', 'b', 'reliable']
    mine = rows[rows.well.eq(well)] if not rows.empty else rows
    if mine.empty:
        return pd.DataFrame(columns=cols)
    d = legacy.prepare(gdi)
    studies = legacy.analyze(d[d.well.astype(str).eq(well)], threshold)
    studies['well'] = studies.well.astype(str)
    coef = studies.groupby('date')[['a', 'b']].last().reset_index() if len(studies) else pd.DataFrame(columns=['date', 'a', 'b'])
    t = mine.sort_values('date', kind='stable').drop_duplicates('date', keep='last').merge(coef, on='date', how='left')
    t['reliable'] = t.reliable.map({True: 'да', False: 'нет'})
    return t[cols].reset_index(drop=True)


def well_card_chart(card: pd.DataFrame, rep: pd.DataFrame, well: str) -> Chart | None:
    """Карточка скважины: Q при опорном ΔP², a и b по всем ГДИ по датам; ремонты — вертикальными линиями (фактические даты справки КРС)."""
    ok = card[card.reliable.eq('да')]
    if ok.empty:
        return None
    chart = Chart('gdi-summary-well-card', f'Скважина № {well}: все ГДИ по сезонам, Q при опорном ΔP², коэффициенты a и b',
                  Axis('Дата ГДИ', scale='time'), Axis('Q при опорном ΔP²', UNITS['q_gdi']), y2=Axis('a', color='#2563eb'), y3=Axis('b', color='#d97706'))
    x = list(ok.date)
    chart.series += [Series('Q при опорном ΔP²', x, list(ok.q_ref), 'line', markers=True, color='#111827'),
                     Series('a', x, list(ok.a), 'line', markers=True, color='#2563eb', axis='y2'),
                     Series('b', x, list(ok.b), 'line', markers=True, color='#d97706', axis='y3')]
    weak = card[card.reliable.eq('нет') & card.q_ref.notna()]
    if len(weak):
        chart.series.append(Series('Q ненадёжных ГДИ', list(weak.date), list(weak.q_ref), 'points', color='#9ca3af', hollow=True))
    for r in (rep[rep.well.eq(well)] if not rep.empty else rep).itertuples():
        chart.events.append(Event(r.date, f'КРС {int(r.year)}: {r.work_type or r.kind}' + ('' if r.dated else ' (только год)'), 'repair', well))
    return chart


MODEL = DatasetKind.MODEL
EMPTY_MODEL = ('Сравнение с моделью: модели не выбраны или в них нет давлений скважин (векторы WBP и WBHP). Источники моделей задаются в настройках проекта '
               'так же, как для конструктора графиков; ничего не выдумываем.')
MODEL_WINDOW_DAYS = 3


def model_compare(gdi: pd.DataFrame, rows: pd.DataFrame, model: pd.DataFrame | None, seasons: list[str], top: int = 15) -> pd.DataFrame:
    """Расхождение модели и ГДИ по депрессии и ΔP² на дату надёжного исследования сезона (точка с максимальным Q), в процентах к ГДИ.
    Модель — векторы скважин (WBP − WBHP) на ближайшую дату не дальше ``MODEL_WINDOW_DAYS`` суток. Сортировка по |ΔP²|; решает инженер."""
    cols = ['well', 'date', 'model', 'q_gdi', 'dp_gdi', 'dp_model', 'dp_diff', 'dp2_gdi', 'dp2_model', 'dp2_diff', 'q_model']
    if model is None or model.empty or not {'wbp', 'wbhp'} <= set(model.columns) or gdi is None or gdi.empty:
        return pd.DataFrame(columns=cols)
    ok = rows[rows.reliable & rows.season.isin(seasons)][['well', 'date']].drop_duplicates()
    g = gdi.assign(well=gdi.well.astype(str))
    m = model.assign(well=model.well.astype(str)).dropna(subset=['wbp', 'wbhp'])
    out = []
    for r in ok.itertuples():
        pts = g[g.well.eq(r.well) & g.date.eq(r.date) & g.q.gt(0) & g.p_res.notna() & g.p_bh.notna()]
        if pts.empty:
            continue
        pt = pts.sort_values('q').iloc[-1]
        dp, dp2 = float(pt.p_res - pt.p_bh), float(pt.p_res ** 2 - pt.p_bh ** 2)
        mine = m[m.well.eq(r.well)]
        for name, mm in mine.groupby('model'):
            near = (mm.date - r.date).abs()
            if near.min() > pd.Timedelta(days=MODEL_WINDOW_DAYS):
                continue
            row = mm.loc[near.idxmin()]
            dpm, dp2m = float(row.wbp - row.wbhp), float(row.wbp ** 2 - row.wbhp ** 2)
            out.append({'well': r.well, 'date': r.date, 'model': str(name), 'q_gdi': float(pt.q), 'dp_gdi': dp, 'dp_model': dpm,
                        'dp_diff': (dpm / dp - 1) * 100 if dp else np.nan, 'dp2_gdi': dp2, 'dp2_model': dp2m,
                        'dp2_diff': (dp2m / dp2 - 1) * 100 if dp2 else np.nan,
                        'q_model': float(row['wgpr']) if 'wgpr' in row and pd.notna(row['wgpr']) else np.nan})
    t = pd.DataFrame(out, columns=cols)
    if t.empty:
        return t
    return t.reindex(t.dp2_diff.abs().sort_values(ascending=False, kind='stable').index).head(int(top)).reset_index(drop=True)


def model_block(result: Result, gdi: pd.DataFrame, rows: pd.DataFrame, model: pd.DataFrame | None, seasons: list[str], top: int) -> None:
    t = model_compare(gdi, rows, model, seasons, top)
    if t.empty:
        result.notes.append(Note(EMPTY_MODEL))
        return
    labels = [f'№ {r.well} · {r.date:%d.%m.%Y}' + (f' · {r.model}' if t.model.nunique() > 1 else '') for r in t.itertuples()]
    chart = Chart('gdi-summary-model', f'Расхождение модели и ГДИ: топ-{len(t)} по ΔP² (модель к ГДИ, %)',
                  Axis('Скважина и дата ГДИ', scale='category', categories=labels), Axis('Расхождение', '%'))
    chart.series += [Series('Депрессия ΔP', labels, t.dp_diff.to_numpy(float), 'bar', color='#2563eb'),
                     Series('ΔP²', labels, t.dp2_diff.to_numpy(float), 'bar', color='#d97706')]
    result.charts.append(chart)
    result.tables.append(Table('gdi-summary-model-table', 'Сравнение модели и ГДИ: наибольшие расхождения', t, [
        Column('well', 'Скважина'), Column('date', 'Дата ГДИ', kind='date'), Column('model', 'Модель'),
        Column('q_gdi', 'Q ГДИ', UNITS['q_gdi'], 1, 'number'), Column('q_model', 'Q модели', UNITS['q_gdi'], 1, 'number'),
        Column('dp_gdi', 'ΔP ГДИ', 'кгс/см²', 1, 'number'), Column('dp_model', 'ΔP модели', 'кгс/см²', 1, 'number'), Column('dp_diff', 'Расхождение ΔP', '%', 1, 'number'),
        Column('dp2_gdi', 'ΔP² ГДИ', kind='number', decimals=0), Column('dp2_model', 'ΔP² модели', kind='number', decimals=0), Column('dp2_diff', 'Расхождение ΔP²', '%', 1, 'number')],
        note='ГДИ — точка с максимальным Q надёжного исследования; модель — ближайшая дата не дальше 3 суток. Расхождение — подсказка, решает инженер.'))


def parse_pairs(text) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Ручной выбор пар: строки «скважина=ДД.ММ.ГГГГ; ДД.ММ.ГГГГ» (до КРС; после КРС). Главнее подсказки; ошибочные строки пропускаются."""
    out = {}
    pairs = (line.split('=', 1) for line in str(text or '').splitlines() if '=' in line)
    for well, value in ((a.strip(), b) for a, b in pairs):
        dates = [pd.to_datetime(x, dayfirst=True, errors='coerce') for x in re.split(r'[;,\s]+', value.strip()) if x]
        if len(dates) == 2 and all(pd.notna(d) for d in dates):
            out[well] = (dates[0].normalize(), dates[1].normalize())
    return out


def season_years(seasons) -> set[int]:
    """Годы ремонтов выбранных сезонов: год начала сезона («2025-2026» и сезон закачки «2025» → 2025, лето перед сезоном)."""
    return {int(m.group(1)) for sn in seasons or [] if (m := re.search(r'(\d{4})', str(sn)))}


def krs_pairs(rows: pd.DataFrame, rep: pd.DataFrame, years: set[int] | None = None, manual: dict | None = None,
              wells: list[str] | None = None) -> list[dict[str, Any]]:
    """Пары исследований для ИД, по одной на каждый ремонт: последнее надёжное ГДИ до ремонта и первое надёжное после него.
    ``years`` — только ремонты этих лет (пусто или None — все); ``wells`` — только эти скважины. Ручная пара скважины заменяет её подсказки.
    Ненадёжные в подсказку не попадают; решает инженер. Запись: {'well', 'before', 'after', 'year'} (год ремонта; у ручной пары — 0)."""
    out: list[dict[str, Any]] = []
    if not rep.empty and not rows.empty:
        r = rep[rep.year.isin(years)] if years else rep
        for repair in r.sort_values(['date', 'well']).itertuples():
            ok = rows[rows.well.eq(repair.well) & rows.reliable & rows.q_ref.notna()].drop_duplicates('date').sort_values('date')
            before, after = ok[ok.date <= repair.date], ok[ok.date > repair.date]
            if len(before) and len(after):
                item = {'well': repair.well, 'before': before.date.iloc[-1], 'after': after.date.iloc[0], 'year': int(repair.year)}
                if item not in out:
                    out.append(item)
    hand = manual or {}
    out = [x for x in out if x['well'] not in hand] + [{'well': w, 'before': v[0], 'after': v[1], 'year': 0} for w, v in hand.items()]
    if wells:
        out = [x for x in out if x['well'] in set(wells)]
    return sorted(out, key=lambda x: (well_key(x['well']), x['year']))


def pair_name(item: dict[str, Any]) -> str:
    return f"{item['well']} · КРС {item['year']}" if item.get('year') else f"{item['well']} · пара вручную"


def id_pair_charts(gdi: pd.DataFrame, data_raw: pd.DataFrame, pairs: list[dict[str, Any]], params: dict[str, Any]) -> list[Chart]:
    """ИД двух исследований на каждую пару: общий построитель ИД раздела «ГДИ» (красный — до КРС, зелёный — после КРС)."""
    from .gdi import GdiModule
    charts = []
    curves = params.get('id_curves', ['calc', 'db'])
    g = legacy.prepare(gdi)
    raw = legacy.prepare(data_raw) if data_raw is not None else g
    for item in pairs:
        well, pair = item['well'], (item['before'], item['after'])
        pts = g[g.well.astype(str).eq(well) & (g.date.isin(pair))]
        if pts.empty:
            continue
        studies = legacy.analyze(pts, float(params['threshold']))
        chart = GdiModule.chart(pts, studies, raw[raw.well.astype(str).eq(well)], well,
                                {'orientation': params.get('id_orientation', 'standard'), 'curves': 'calc' in curves, 'db_curves': 'db' in curves, 'crosshair': True,
                                 'show_excluded': False, 'pair': pair})
        tag = f"-{item['year']}" if item['year'] else ''
        chart.id = f'gdi-summary-id-{well}{tag}'
        chart.title = f'Скважина № {well}: ИД до КРС ({pair[0]:%d.%m.%Y}) и после КРС ({pair[1]:%d.%m.%Y})' + (f" · ремонт {item['year']} г." if item['year'] else '')
        charts.append(chart)
    return charts


class GdiSummaryModule(Module):
    spec = ModuleSpec(
        id='gdi_summary',
        title='Справка ГДИ: итоги сезона и ремонты (КРС)',
        group='Исследования скважин',
        description='Сколько скважин улучшили, ухудшили или сохранили отдачу по ГДИ в выбранном сезоне и как это связано с КРС '
                    '(замена фильтра, промывка, год ремонта, давно не исследовались); отдельный разбор скважин, ремонтированных в выбранном году.',
        needs=(GDI,),
        optional=(WORKS, PLAN, PROGRAM, MODEL),
        order=36,
        params=(
            Param('seasons', 'Сезон ГДИ', 'multi', default=[], source=Source(GDI, 'season'), section=SECTION,
                  help='Сезоны из исходного файла ГДИ. Пусто — последний сезон. Несколько — скважины всех выбранных.'),
            Param('threshold', 'Порог R²', 'number', default=0.95, minimum=0.0, maximum=1.0, step=0.01, setting='r2_threshold',
                  section=SECTION, help='Общая настройка проекта: в справку попадают только надёжные исследования.'),
            Param('change', 'Порог изменения', 'number', default=5.0, minimum=0, maximum=50, step=0.5, unit='%', section=SECTION,
                  help='Изменение расхода при опорном ΔP² меньше порога — «без изменений».',
                  formula='изменение = (Q последнего надёжного ГДИ сезона − Q предыдущего надёжного) / Q предыдущего × 100%',
                  example='Q было 180, стало 153: −15% — при пороге 5% это ухудшение.'),
            Param('years', 'Давно не исследовались, лет', 'number', default=5.0, minimum=1, maximum=30, step=1, unit='лет', section=SECTION,
                  help='Перерыв между предыдущим ГДИ и первым ГДИ сезона больше срока — категория «ГДИ не делали более N лет».'),
            Param('repair_year', 'Год ремонта (КРС)', 'number', default=0, minimum=0, maximum=2100, step=1, section='Ремонты',
                  help='Для разбора скважин с КРС. 0 — первый год выбранного сезона (лето перед сезоном). Данные КРС берутся из справки КРС '
                       '(импорт КРС_для_Атласа.xlsx); даты — из листа «План КР», иначе только год (условно 1 июля).'),
            Param('group_by', 'Группы справки', 'choice', default='auto', section='Ремонты',
                  options=(Option('auto', 'Авто: по программе ГДИ, если загружена'), Option('program', 'По программе ГДИ'),
                           Option('krs', 'По данным КРС и срокам ГДИ')),
                  help='Программа ГДИ: замена фильтра, промывка и СКО, план КР на год, давно не проводились. Категория — подсказка, правится вручную.'),
            Param('hist_edges', 'Границы корзин гистограммы, %', 'text', default=DEFAULT_EDGES, section='Графики',
                  help='Границы через запятую, например «-30, -15, -5, 5, 15, 30»: корзины между ними, по краям «меньше» и «больше». '
                       'Чем меньше границ, тем крупнее группы (по умолчанию «−5…5» одной корзиной).'),
            Param('hist_by', 'Гистограмма по группам плана', 'choice', default='all', section='Графики',
                  options=(Option('all', 'Одна на все скважины'), Option('groups', 'Отдельная на каждую группу'), Option('both', 'Общая и по группам')),
                  help='Группы — категории справки (по программе ГДИ: замена фильтра, промывка и СКО, КР в сезоне закачки и др.).'),
            Param('slice', 'Периоды ГДИ', 'multi', default=[], section='Ремонты', empty='все',
                  options=tuple(Option(x, x) for x in SLICES),
                  help='Сезон отбора — основной срез; «Сезон закачки» и «Нейтральный период» вместе — ГДИ после КРС. Выберите сезон отбора и, если нужно, '
                       'сезон закачки в «Сезон ГДИ»: покажутся ГДИ нейтральных периодов и закачки. Период берётся из «Расписания периодов» проекта '
                       '(inj/prod/none), без него — по месяцам сезона отбора. Подсказка: правится в «Периоды вручную».'),
            Param('period_manual', 'Периоды вручную', 'text', default='', section='Ремонты',
                  help='Строки «скважина=срез», например «56=Сезон закачки». Срез — один из пунктов «Периоды ГДИ». Главнее расчёта.'),
            Param('done_manual', 'Выполнено вручную', 'text', default='', section='Ремонты',
                  help='Скважины программы ГДИ, по которым исследование пытались провести, но данных нет. Строки «скважина=причина», например '
                       '«56=не удалось провести, обводнение». Считаются выполненными, причина видна в таблице.'),
            Param('card_well', 'Карточка скважины', 'text', default='', section='Ремонты',
                  help='Номер скважины: все её ГДИ по датам (Q при опорном ΔP², a, b), ремонты КРС вертикальными линиями, таблица исследований с надёжностью. Пусто — без карточки.'),
            Param('model_top', 'Сравнение с моделью: сколько скважин', 'number', default=15, minimum=0, maximum=100, step=1, section='Графики',
                  help='Топ расхождений депрессии и ΔP² между ГДИ и моделью (выбранные модели проекта). 0 — не сравнивать.'),
            Param('id_charts', 'ИД до и после КРС', 'choice', default='no', section='Ремонты',
                  options=(Option('no', 'Не строить'), Option('yes', 'Построить: по скважине два исследования')),
                  help='Индикаторные диаграммы двух исследований: «до КРС» красным и «после КРС» зелёным. Подсказка пары — последнее надёжное ГДИ до ремонта '
                       'и первое надёжное после (ремонты «Года ремонта»); правится в «Парах ИД вручную».'),
            Param('id_curves', 'Кривые на ИД', 'multi', default=['calc', 'db'], section='Ремонты', empty='без кривых',
                  options=(Option('calc', 'Расчётные (по замерам)'), Option('db', 'По коэффициентам БД')),
                  help='Какие кривые рисовать на ИД до и после КРС. Чтобы убрать кривые по БД, снимите «По коэффициентам БД»: останутся только точки и расчётные кривые.'),
            Param('id_pairs', 'Пары ИД вручную', 'text', default='', section='Ремонты',
                  help='Строки «скважина=ДД.ММ.ГГГГ; ДД.ММ.ГГГГ» — дата ГДИ до КРС и после. Главнее подсказки; ненадёжное исследование тоже можно выбрать.'),
            Param('manual', 'Категории вручную', 'text', default='', section='Ремонты',
                  help='Строки «скважина=категория», например «56=После КРС: замена фильтра». Исправляет подсказку программы; '
                       'в таблице видно, где категория правлена вручную.'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        rows = study_rows(data[GDI], float(params['threshold']))
        if rows.empty:
            result.notes.append(Note('Исследований ГДИ в проекте нет.', 'warning'))
            return result
        seasons = [str(s) for s in params['seasons']] or [self.latest_season(rows)]
        limit, years = float(params['change']), float(params['years'])
        works = data.get(WORKS)
        rep = repairs(works, data.get(PLAN))
        if works is None or works.empty:
            result.notes.append(Note(EMPTY_KRS))
        program = data.get(PROGRAM)
        mode = params.get('group_by') or 'auto'
        groups = program_groups(program, seasons) if mode == 'program' or (mode == 'auto' and program is not None and not program.empty) else None
        cfg = getattr(data, 'settings', {}) or {}
        table = season_table(rows, seasons, limit, years, rep, parse_manual(params['manual']), groups, cfg.get('season_schedule'),
                             (int(cfg.get('season_start', 11)), int(cfg.get('season_end', 4))), parse_manual(params.get('period_manual', '')))
        chosen = [normalize_slice(x) for x in (params.get('slice') or []) if x != 'all']
        label = ', '.join(seasons)
        if table.empty:
            result.notes.append(Note(f'В сезоне {label} исследований нет. Выберите другой сезон.', 'warning'))
            return result
        if chosen:
            table = table[table.slice.isin(chosen)].reset_index(drop=True)
            if table.empty:
                result.notes.append(Note(f'В сезоне {label} исследований в периодах «{", ".join(chosen)}» нет. Снимите выбор периодов или выберите другой сезон.'))
                return result
            label = f'{label} · {", ".join(chosen)}'
        result.notes.append(Note(NOTE))
        few = int(table.change.isna().sum())
        if few:
            result.notes.append(Note(f'{few} из {len(table)} скв. без сравнения (нужны два надёжных ГДИ с разными датами): на графиках они в столбце «{VERDICT_FEW}» '
                                     f'и «{NO_COMPARE}», причина — в таблице скважин (даты и Q). Ненадёжные исследования в расчёт изменения не входят.'))
        counts = table.verdict.value_counts()
        result.summary = [Stat('Скважин в сезоне', str(table.well.nunique()), label + (f' · срезов «скважина × период»: {len(table)}' if table.well.nunique() != len(table) else ''))] + [
            Stat(v, str(int(counts.get(v, 0)))) for v in VERDICTS]
        cats = sorted(table.category.unique(), key=lambda c: (c.startswith(CAT_NO_REPAIR) or c == CAT_FIRST, c))
        by = {(c, v): int(((table.category == c) & (table.verdict == v)).sum()) for c in cats for v in VERDICTS}
        result.charts += [
            stacked('gdi-summary-by-cat', f'Итоги ГДИ по категориям скважин · {label}', cats, by, VERDICTS, VERDICT_COLORS, 'Категория',
                    wells=members(table, 'category', cats, VERDICTS)),
            grouped('gdi-summary-grouped', f'Что улучшилось, ухудшилось и не изменилось по категориям · {label}', cats, by),
            stacked('gdi-summary-share', f'Доли итогов ГДИ по категориям, % · {label}', cats, by, VERDICTS, VERDICT_COLORS, 'Категория', True)]
        sl = [c for c in SLICES if c in set(table.slice)] + sorted(set(table.slice) - set(SLICES))
        by_sl = {(c, v): int(((table.slice == c) & (table.verdict == v)).sum()) for c in sl for v in VERDICTS}
        result.charts.append(stacked('gdi-summary-slices', f'Итоги ГДИ по периодам · {label}', sl, by_sl, VERDICTS, VERDICT_COLORS, 'Период ГДИ',
                                         wells=members(table, 'slice', sl, VERDICTS)))
        edges, hist_by = parse_edges(params.get('hist_edges')), params.get('hist_by') or 'all'
        if hist_by in ('all', 'both'):
            hist = change_histogram(table, limit, edges)
            if hist is not None:
                result.charts.append(hist)
        if hist_by in ('groups', 'both'):
            for n, cat in enumerate(sorted(table.category.unique(), key=lambda x: (x.startswith(CAT_NO_REPAIR), x))):
                part = change_histogram(table[table.category.eq(cat)], limit, edges, f'gdi-summary-hist-{n}', f'{cat} ({int(table.category.eq(cat).sum())} скв.)')
                if part is not None:
                    result.charts.append(part)
        matrix = count_matrix(table, 'category', VERDICTS)
        mcols = [Column('category', 'Категория'), Column('total', 'Всего скважин', kind='number', decimals=0)]
        for v in VERDICTS:
            mcols += [Column(v, v, kind='number', decimals=0), Column(f'{v}|wells', f'{v}: скважины')]
        result.tables.append(Table('gdi-summary-matrix', 'Справка: итог ГДИ × категория скважин', matrix, mcols,
                                   note='Категория — подсказка: основание в таблице скважин ниже, правится вручную.'))
        years_tab = table[table.krs_year.notna()].assign(krs_label=lambda d: d.krs_year.astype(int).astype(str) + ' г.')
        if not years_tab.empty:
            ycats = sorted(years_tab.krs_label.unique())
            yby = {(c, v): int(((years_tab.krs_label == c) & (years_tab.verdict == v)).sum()) for c in ycats for v in VERDICTS}
            result.charts.append(stacked('gdi-summary-krs-years', f'Итоги ГДИ после КРС по годам ремонта · {label} · {len(years_tab)} из {len(table)} скв.', ycats, yby,
                                         VERDICTS, VERDICT_COLORS, 'Год КРС', wells=members(years_tab, 'krs_label', ycats, VERDICTS)))
        result.tables.append(Table('gdi-summary-wells', 'Скважины сезона: итог ГДИ и категория', table[
            ['well', 'verdict', 'change', 'prev_date', 'last_date', 'q_prev', 'q_last', 'slice', 'slice_edited', 'category', 'edited', 'reason']], [
            Column('well', 'Скважина'), Column('verdict', 'Итог'), Column('change', 'Изменение Q', '%', 1, 'number'),
            Column('prev_date', 'ГДИ до (сравнение)', kind='date'), Column('last_date', 'ГДИ сезона', kind='date'),
            Column('q_prev', 'Q было', UNITS['q_gdi'], 1, 'number'), Column('q_last', 'Q стало', UNITS['q_gdi'], 1, 'number'),
            Column('slice', 'Период ГДИ'), Column('slice_edited', 'Период: правка'),
            Column('category', 'Категория'), Column('edited', 'Правка'), Column('reason', 'Основание категории')]))
        self.repair_block(result, data, rows, rep, params, seasons, limit)
        program_block(result, rows, program, seasons, parse_manual(params.get('done_manual', '')))
        card_well = str(params.get('card_well') or '').strip().lstrip('№ ').strip()
        if card_well:
            card = well_card_table(data[GDI], rows, card_well, float(params['threshold']))
            if card.empty:
                result.notes.append(Note(f'Для карточки: по скважине {card_well} исследований ГДИ нет.'))
            else:
                chart = well_card_chart(card, rep, card_well)
                if chart is not None:
                    result.charts.append(chart)
                result.tables.append(Table('gdi-summary-well-card-table', f'Скважина № {card_well}: все исследования', card, [
                    Column('date', 'Дата ГДИ', kind='date'), Column('season', 'Сезон'), Column('q_ref', 'Q при опорном ΔP²', UNITS['q_gdi'], 1, 'number'),
                    Column('a', 'a', kind='number', decimals=4), Column('b', 'b', kind='number', decimals=6), Column('reliable', 'Надёжное')],
                    note='Ненадёжные исследования на линиях не показаны (серые точки Q), но видны здесь: решает инженер.'))
        if int(params.get('model_top', 15) or 0) > 0:
            model_block(result, data[GDI], rows, data.get(MODEL), seasons, int(params.get('model_top', 15)))
        if (params.get('id_charts') or 'no') == 'yes':
            year = int(params.get('repair_year') or 0)
            years = {year} if year else season_years(seasons)           # ремонты выбранных сезонов (лето перед сезоном), а не все ремонты скважин
            pairs = krs_pairs(rows, rep, years, parse_pairs(params.get('id_pairs')))
            charts = id_pair_charts(data[GDI], data.raw.get(GDI), pairs, params) if pairs else []
            result.charts += charts
            if not charts:
                result.notes.append(Note(f'ИД до и после КРС: для ремонтов {', '.join(map(str, sorted(years)))} г. нет скважин с надёжным ГДИ до и после. Укажите пары вручную.'))
        age_block(result, rows, rep, program, seasons)
        matrix_block(result, rows, program, rep, parse_manual(params.get('done_manual', '')))
        return result

    @staticmethod
    def latest_season(rows: pd.DataFrame) -> str:
        last = rows.dropna(subset=['date']).sort_values('date').season.iloc[-1] if rows.date.notna().any() else ''
        return str(last)

    @staticmethod
    def repair_block(result: Result, data: Data, rows: pd.DataFrame, rep: pd.DataFrame, params: dict[str, Any], seasons: list[str], limit: float) -> None:
        year = int(params['repair_year'])
        years = {year} if year else (season_years(seasons) or set())      # ремонты выбранных сезонов (лето перед сезоном)
        if rep.empty or not years:
            return
        label = _years_label(years)
        table = repair_year_table(rows, rep, years, limit)
        if table.empty:
            result.notes.append(Note(f'Ремонтов КРС за {label} в данных нет. Выберите другие сезоны или «Год ремонта».'))
            return
        kinds = sorted(table.kind.unique())
        by = {(k, v): int(((table.kind == k) & (table.verdict == v)).sum()) for k in kinds for v in REPAIR_VERDICTS}
        result.charts.append(stacked('gdi-summary-repair', f'ГДИ после ремонта по видам КРС · {label}', kinds, by, REPAIR_VERDICTS,
                                     REPAIR_COLORS, 'Вид ремонта', wells=members(table, 'kind', kinds, REPAIR_VERDICTS)))
        effect = repair_effect_chart(table, years)
        if effect is not None:
            result.charts.append(effect)
        cfg = getattr(data, 'settings', None) or {}
        path = repair_path_table(rows, rep, years, cfg.get('season_schedule'), int(cfg.get('season_start', 11)), int(cfg.get('season_end', 4)), limit)
        pc = repair_path_chart(path, years)
        if pc is not None:
            result.charts.append(pc)
        if not path.empty:
            followed = [FOLLOW_BOTH, FOLLOW_AFTER, FOLLOW_NEXT, FOLLOW_NONE]
            fk = sorted(path.kind.unique())
            fby = {(k, v): int(((path.kind == k) & (path.follow == v)).sum()) for k in fk for v in followed}
            result.charts.append(stacked('gdi-summary-follow', f'Есть ли ГДИ после КРС и в следующем отборе · {label}', fk, fby, tuple(followed), FOLLOW_COLORS, 'Вид ремонта',
                                         wells=members(path, 'kind', fk, tuple(followed), by='follow')))
            nx = int(path.date_next.notna().sum())
            result.summary += [Stat('ГДИ в следующем отборе', f'{nx} из {len(path)}', 'Ремонты выбранных сезонов, надёжное ГДИ периода отбора'),
                               Stat('Эффект подтверждён в отборе', str(int(path.conclusion.str.startswith('эффект ремонта подтверждён').sum())), 'Улучшение после КРС и в следующем отборе'),
                               Stat('Эффект не сохранился', str(int(path.conclusion.str.startswith('эффект после КРС не сохранился').sum())), 'Улучшение после КРС, в отборе нет')]
            result.tables.append(Table('gdi-summary-repair-path', f'Анализ ГДИ до и после КРС {label}: эффект и следующий отбор', path, [
                Column('well', 'Скважина'), Column('kind', 'Вид ремонта'), Column('year', 'Год ремонта', kind='number', decimals=0),
                Column('repair_date', 'Дата ремонта', kind='date'), Column('date_note', 'Дата'),
                Column('date_before', 'ГДИ до', kind='date'), Column('q_before', 'Q до', UNITS['q_gdi'], 1, 'number'),
                Column('date_after', 'ГДИ после КРС', kind='date'), Column('q_after', 'Q после', UNITS['q_gdi'], 1, 'number'), Column('change_after', 'Изм. после КРС', '%', 1, 'number'),
                Column('date_next', 'ГДИ следующего отбора', kind='date'), Column('q_next', 'Q в отбор', UNITS['q_gdi'], 1, 'number'), Column('change_next', 'Изм. в отбор', '%', 1, 'number'),
                Column('follow', 'Исследования после ремонта'), Column('conclusion', 'Вывод (подсказка)')],
                note='Изменения — к последнему надёжному ГДИ до ремонта при опорном ΔP². «Следующий отбор» — первое надёжное ГДИ периода отбора не позже '
                     '18 месяцев после ремонта. Ненадёжные не входят; даты ремонта — фактические (справка КРС), без даты — 1 июля года. Вывод — подсказка, решает инженер.'))
        done = int((~table.verdict.isin([NO_AFTER])).sum())
        result.summary += [Stat(f'Ремонтов КРС за {label}', str(len(table)), f'с надёжным ГДИ после: {done}'),
                           Stat('Без ГДИ после ремонта', str(int(table.verdict.eq(NO_AFTER).sum())), 'Кандидаты на исследование')]
        result.tables.append(Table('gdi-summary-repairs', f'Скважины с КРС за {label}: ГДИ до и после ремонта', table, [
            Column('well', 'Скважина'), Column('kind', 'Вид ремонта'), Column('work_type', 'Работы по справке'),
            Column('repair_date', 'Дата ремонта', kind='date'), Column('date_note', 'Дата'),
            Column('before', 'ГДИ до', kind='date'), Column('after', 'ГДИ после', kind='date'),
            Column('q_before', 'Q до', UNITS['q_gdi'], 1, 'number'), Column('q_after', 'Q после', UNITS['q_gdi'], 1, 'number'),
            Column('change', 'Изменение Q', '%', 1, 'number'), Column('verdict', 'Вывод'), Column('comment', 'Замечание')],
            note='ГДИ до — последнее надёжное исследование не позже ремонта, после — первое надёжное после него. Если даты ремонта в справке '
                 'нет, берётся 1 июля года: близкие по времени исследования проверьте вручную.'))
