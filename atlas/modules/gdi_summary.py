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

from ..contract import Axis, Chart, ChartTable, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Source, Stat, Table
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


CAT_OFF_PROGRAM = 'Вне программы ГДИ'
PERIOD_NEUTRAL, PERIOD_INJ, PERIOD_WD = 'Нейтральный период', 'Закачка', 'Отбор'
SLICE_INJ_BEFORE, SLICE_INJ_AFTER, SLICE_INJ_NONE = 'Закачка: до КРС', 'Закачка: после КРС', 'Закачка: без КРС'
SLICES = (PERIOD_NEUTRAL, SLICE_INJ_BEFORE, SLICE_INJ_AFTER, SLICE_INJ_NONE, PERIOD_WD)
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


def slice_of(period: str, date, rep_well: pd.DataFrame, window_days: int = 365) -> str:
    """Срез для анализа: нейтральный период, отбор, закачка до / после / без КРС (ближайший ремонт скважины не дальше года от ГДИ)."""
    if period != PERIOD_INJ or pd.isna(date):
        return period
    near = rep_well[(rep_well.date - date).abs() <= pd.Timedelta(days=window_days)] if not rep_well.empty else rep_well
    if near.empty:
        return SLICE_INJ_NONE
    nearest = near.iloc[(near.date - date).abs().argmin()]
    return SLICE_INJ_BEFORE if date < nearest.date else SLICE_INJ_AFTER



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
    inside = rows[rows.season.isin(seasons)]
    for well in sorted(inside.well.unique(), key=well_key):
        g = rows[rows.well.eq(well)].sort_values('date', kind='stable')
        mine = g[g.season.isin(seasons)]
        first_in = mine.date.min()
        ok = g[g.reliable & g.q_ref.notna()].drop_duplicates('date', keep='last')
        ok_in = ok[ok.season.isin(seasons)]
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
        last_when = last.date if last is not None else last_date
        period = period_of(last_when, schedule, *season_months)
        slice_name = (period_manual or {}).get(well) or slice_of(period, last_when, rep[rep.well.eq(well)] if not rep.empty else rep)
        out.append({'well': well, 'verdict': verdict, 'change': change, 'slice': slice_name, 'slice_edited': 'вручную' if well in (period_manual or {}) else '',
                    'prev_date': base.date if base is not None else pd.NaT, 'last_date': last.date if last is not None else last_date,
                    'q_prev': base.q_ref if base is not None else np.nan, 'q_last': last.q_ref if last is not None else np.nan,
                    'auto': auto, 'category': manual.get(well, auto), 'edited': 'вручную' if well in manual else '',
                    'krs_year': krs_year or np.nan, 'reason': reason})
    return pd.DataFrame(out)


def repair_year_table(rows: pd.DataFrame, rep: pd.DataFrame, year: int, limit: float) -> pd.DataFrame:
    """Для каждого ремонта года: ГДИ до (последнее надёжное) и после (первое надёжное) и вывод."""
    out = []
    for r in rep[rep.year.eq(year)].sort_values(['well', 'date'], key=lambda c: c.map(well_key) if c.name == 'well' else c).itertuples():
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
    result.charts.append(stacked('gdi-summary-program', 'Выполнение программы ГДИ по причинам', cats, by, PROGRAM_STATUSES, PROGRAM_COLORS, 'Причина'))
    result.tables.append(Table('gdi-summary-program-wells', 'Программа ГДИ: выполнение по скважинам', table, [
        Column('well', 'Скважина'), Column('group', 'ГСП'), Column('stage', 'Этап'), Column('reason_kind', 'Причина'),
        Column('krs_injection', 'КР в сезоне закачки'), Column('status', 'Выполнение'), Column('status_note', 'Причина отметки'), Column('last_date', 'Последнее ГДИ сезона', kind='date'),
        Column('reason', 'Формулировка программы')],
        note='Программа загружается во вкладке «Импорт» (файл Word). Сверка — по сезону программы: есть ли исследование этой скважины в сезоне. '
             'Подсказка: решает инженер.'))


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


def stacked(cid: str, title: str, cats: list[str], by: dict[tuple[str, str], int], stack_names: tuple[str, ...], colors: dict[str, str],
            x_label: str, share: bool = False) -> Chart:
    """Гистограмма-стопка: столбец на категорию, сегмент на вывод; в сегменте число скважин (``share`` — доли от столбца)."""
    chart = Chart(cid, title, Axis(x_label, scale='category', categories=cats),
                  Axis('Доля скважин' if share else 'Скважин', '%' if share else 'ед.', from_zero=True))
    totals = [sum(by.get((c, v), 0) for v in stack_names) for c in cats]
    for v in stack_names:
        n = np.array([by.get((c, v), 0) for c in cats], float)
        y = np.array([x / t * 100 if share and t else x for x, t in zip(n, totals)], float)
        chart.series.append(Series(v, cats, y, 'bar', stack='verdict', color=colors[v], segments=[str(int(x)) if x else '' for x in n],
                                   labels=[f'{int(x)} из {t} скв.' for x, t in zip(n, totals)]))
    chart.table = ChartTable([s.name for s in chart.series], cats, [[str(int(by.get((c, v), 0))) for c in cats] for v in stack_names])
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
    if c.empty:
        return None
    edges = edges or parse_edges('')
    labels = [f'< {_num(edges[0])}'] + [f'{_num(a)}…{_num(b)}' for a, b in zip(edges, edges[1:])] + [f'> {_num(edges[-1])}']
    idx = np.searchsorted(edges, c.to_numpy(float), side='right')
    counts = np.bincount(idx, minlength=len(labels))[:len(labels)].astype(float)
    step = (edges[-1] - edges[0]) / max(len(edges) - 1, 1)
    mids = [edges[0] - step / 2] + [(a + b) / 2 for a, b in zip(edges, edges[1:])] + [edges[-1] + step / 2]
    title = 'Распределение изменения расхода при опорном ΔP² по скважинам сезона' + (f' · {suffix}' if suffix else '')
    chart = Chart(cid, title, Axis('Изменение Q, %', scale='category', categories=labels), Axis('Скважин', 'ед.', from_zero=True))
    colors = [VERDICT_COLORS[VERDICT_DOWN] if m < -limit else VERDICT_COLORS[VERDICT_UP] if m > limit else VERDICT_COLORS[VERDICT_SAME] for m in mids]
    for label, n, col in zip(labels, counts, colors):
        chart.series.append(Series(label, [label], [n], 'bar', stack='hist', color=col, legend=False, segments=[str(int(n)) if n else '']))
    return chart


class GdiSummaryModule(Module):
    spec = ModuleSpec(
        id='gdi_summary',
        title='Справка ГДИ: итоги сезона и ремонты (КРС)',
        group='Исследования скважин',
        description='Сколько скважин улучшили, ухудшили или сохранили отдачу по ГДИ в выбранном сезоне и как это связано с КРС '
                    '(замена фильтра, промывка, год ремонта, давно не исследовались); отдельный разбор скважин, ремонтированных в выбранном году.',
        needs=(GDI,),
        optional=(WORKS, PLAN, PROGRAM),
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
            Param('slice', 'Срез по периоду', 'choice', default='all', section='Ремонты',
                  options=(Option('all', 'Все исследования'), Option(PERIOD_NEUTRAL, PERIOD_NEUTRAL), Option(SLICE_INJ_BEFORE, SLICE_INJ_BEFORE),
                           Option(SLICE_INJ_AFTER, SLICE_INJ_AFTER), Option(SLICE_INJ_NONE, SLICE_INJ_NONE), Option(PERIOD_WD, PERIOD_WD)),
                  help='Период ГДИ берётся из «Расписания периодов» проекта (inj/prod/none); без расписания — по месяцам сезона отбора. '
                       'Закачка до/после КРС — по ближайшему ремонту скважины в пределах года. Подсказка: период правится в «Периоды вручную».'),
            Param('period_manual', 'Периоды вручную', 'text', default='', section='Ремонты',
                  help='Строки «скважина=срез», например «56=Закачка: после КРС». Срез — один из пунктов «Среза по периоду». Главнее расчёта.'),
            Param('done_manual', 'Выполнено вручную', 'text', default='', section='Ремонты',
                  help='Скважины программы ГДИ, по которым исследование пытались провести, но данных нет. Строки «скважина=причина», например '
                       '«56=не удалось провести, обводнение». Считаются выполненными, причина видна в таблице.'),
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
        chosen = params.get('slice') or 'all'
        label = ', '.join(seasons)
        if table.empty:
            result.notes.append(Note(f'В сезоне {label} исследований нет. Выберите другой сезон.', 'warning'))
            return result
        slice_counts = table.slice.value_counts()
        if chosen != 'all':
            table = table[table.slice.eq(chosen)].reset_index(drop=True)
            if table.empty:
                result.notes.append(Note(f'В сезоне {label} исследований со срезом «{chosen}» нет. Выберите «Все исследования» или другой срез.'))
                return result
            label = f'{label} · {chosen}'
        result.notes.append(Note(NOTE))
        counts = table.verdict.value_counts()
        result.summary = [Stat('Скважин в сезоне', str(len(table)), label)] + [
            Stat(v, str(int(counts.get(v, 0)))) for v in VERDICTS]
        cats = sorted(table.category.unique(), key=lambda c: (c.startswith(CAT_NO_REPAIR) or c == CAT_FIRST, c))
        by = {(c, v): int(((table.category == c) & (table.verdict == v)).sum()) for c in cats for v in VERDICTS}
        result.charts += [
            stacked('gdi-summary-by-cat', f'Итоги ГДИ по категориям скважин · {label}', cats, by, VERDICTS, VERDICT_COLORS, 'Категория'),
            grouped('gdi-summary-grouped', f'Что улучшилось, ухудшилось и не изменилось по категориям · {label}', cats, by),
            stacked('gdi-summary-share', f'Доли итогов ГДИ по категориям, % · {label}', cats, by, VERDICTS, VERDICT_COLORS, 'Категория', True)]
        sl = [c for c in SLICES if c in set(table.slice)] + sorted(set(table.slice) - set(SLICES))
        by_sl = {(c, v): int(((table.slice == c) & (table.verdict == v)).sum()) for c in sl for v in VERDICTS}
        result.charts.append(stacked('gdi-summary-slices', f'Итоги ГДИ по периодам · {label}', sl, by_sl, VERDICTS, VERDICT_COLORS, 'Период ГДИ'))
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
            result.charts.append(stacked('gdi-summary-krs-years', f'Итоги ГДИ после КРС по годам ремонта · {label}', ycats, yby,
                                         VERDICTS, VERDICT_COLORS, 'Год КРС'))
        result.tables.append(Table('gdi-summary-wells', 'Скважины сезона: итог ГДИ и категория', table[
            ['well', 'verdict', 'change', 'prev_date', 'last_date', 'q_prev', 'q_last', 'slice', 'slice_edited', 'category', 'edited', 'reason']], [
            Column('well', 'Скважина'), Column('verdict', 'Итог'), Column('change', 'Изменение Q', '%', 1, 'number'),
            Column('prev_date', 'ГДИ до (сравнение)', kind='date'), Column('last_date', 'ГДИ сезона', kind='date'),
            Column('q_prev', 'Q было', UNITS['q_gdi'], 1, 'number'), Column('q_last', 'Q стало', UNITS['q_gdi'], 1, 'number'),
            Column('slice', 'Период ГДИ'), Column('slice_edited', 'Период: правка'),
            Column('category', 'Категория'), Column('edited', 'Правка'), Column('reason', 'Основание категории')]))
        self.repair_block(result, rows, rep, params, seasons, limit)
        program_block(result, rows, program, seasons, parse_manual(params.get('done_manual', '')))
        return result

    @staticmethod
    def latest_season(rows: pd.DataFrame) -> str:
        last = rows.dropna(subset=['date']).sort_values('date').season.iloc[-1] if rows.date.notna().any() else ''
        return str(last)

    @staticmethod
    def repair_block(result: Result, rows: pd.DataFrame, rep: pd.DataFrame, params: dict[str, Any], seasons: list[str], limit: float) -> None:
        year = int(params['repair_year']) or min([int(y) for s in seasons for y in re.findall(r'\d{4}', s)] or [0])
        if rep.empty or not year:
            return
        table = repair_year_table(rows, rep, year, limit)
        if table.empty:
            result.notes.append(Note(f'Ремонтов КРС за {year} г. в данных нет. Укажите другой «Год ремонта».'))
            return
        kinds = sorted(table.kind.unique())
        by = {(k, v): int(((table.kind == k) & (table.verdict == v)).sum()) for k in kinds for v in REPAIR_VERDICTS}
        result.charts.append(stacked('gdi-summary-repair', f'ГДИ после ремонта по видам КРС · {year} г.', kinds, by, REPAIR_VERDICTS,
                                     REPAIR_COLORS, 'Вид ремонта'))
        done = int((~table.verdict.isin([NO_AFTER])).sum())
        result.summary += [Stat(f'Ремонтов КРС за {year} г.', str(len(table)), f'с надёжным ГДИ после: {done}'),
                           Stat('Без ГДИ после ремонта', str(int(table.verdict.eq(NO_AFTER).sum())), 'Кандидаты на исследование')]
        result.tables.append(Table('gdi-summary-repairs', f'Скважины с КРС за {year} г.: ГДИ до и после ремонта', table, [
            Column('well', 'Скважина'), Column('kind', 'Вид ремонта'), Column('work_type', 'Работы по справке'),
            Column('repair_date', 'Дата ремонта', kind='date'), Column('date_note', 'Дата'),
            Column('before', 'ГДИ до', kind='date'), Column('after', 'ГДИ после', kind='date'),
            Column('q_before', 'Q до', UNITS['q_gdi'], 1, 'number'), Column('q_after', 'Q после', UNITS['q_gdi'], 1, 'number'),
            Column('change', 'Изменение Q', '%', 1, 'number'), Column('verdict', 'Вывод'), Column('comment', 'Замечание')],
            note='ГДИ до — последнее надёжное исследование не позже ремонта, после — первое надёжное после него. Если даты ремонта в справке '
                 'нет, берётся 1 июля года: близкие по времени исследования проверьте вручную.'))
