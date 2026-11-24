"""Ремонты КРС скважин и их группа: общее ядро для «Справки ГДИ» и других модулей с ГДИ по скважинам.

Читаются ВСЕ виды ремонтов (``krs_works`` и выполненные ремонты справки КР ``krs_plan``); основные группы — замена ППФ, промывка / СКО, армирование ПЗП,
остальное — «прочий ремонт» (в базе виды остаются как есть). Группа скважины при ГДИ — группа последнего ремонта до даты исследования.
"""
from __future__ import annotations

import pandas as pd

from atlas.engine.core import krs_kinds, krs_plan_file_import


CLASS_OF = {krs_kinds.FILTER: 'замена фильтра', krs_kinds.ARM: 'армирование ПЗП', krs_kinds.CT: 'промывка / СКО', krs_kinds.CTS: 'промывка / СКО',
            krs_kinds.ISOL: 'восстановление герметичности ЦК / изоляция', krs_kinds.COLUMN: 'ремонт колонны', krs_kinds.PLUG: 'ликвидация пробки',
            krs_kinds.KILL: 'глушение скважины'}


def repair_classes(work_type, detail='') -> list[str]:
    """ВСЕ виды работ ремонта (классы как у ``repair_class``): главный первым, остальные следом; «Виды работ» из книги ремонтов читаются из ``detail``."""
    main = krs_kinds.of_text(work_type)
    kinds = krs_kinds.all_of(detail, f'{work_type} {detail}', main if main != krs_kinds.OTHER else '')
    return [CLASS_OF.get(k, 'прочее') for k in kinds]


NO_REPAIR_GROUP = 'без КРС'


def repair_group(kinds: str) -> str:
    """Группа ремонта по видам работ: основные — замена ППФ, промывка / СКО, армирование ПЗП; остальное — прочий ремонт (в базе остаётся как есть)."""
    have = set(str(kinds or '').split('; '))
    for name, group in (('замена фильтра', 'замена ППФ'), ('промывка / СКО', 'промывка / СКО'), ('армирование ПЗП', 'армирование ПЗП')):
        if name in have:
            return group
    return 'прочий ремонт'


def repair_class(work_type, detail='') -> str:
    """Вид ремонта из строки справки (по названию и кодам работ): замена фильтра, армирование, промывка/СКО/колтюбинг, герметичность ЦК и изоляция,
    ремонт колонны, ликвидация пробки, глушение; неузнанное — «прочее» (строка не теряется, работы видны в таблице)."""
    kind = krs_kinds.of_text(work_type)
    if kind == krs_kinds.OTHER:          # в таблице ремонтов тип не указан или не узнан: смотрим коды и описание работ
        kind = krs_kinds.of_codes(detail, detail)
    return CLASS_OF.get(kind, 'прочее')


def repairs(works: pd.DataFrame | None, plan: pd.DataFrame | None) -> pd.DataFrame:
    """Ремонты: well, year, kind (вид), work_type, date (по справке КРС «дата окончания»/«начала», иначе 1 июля года).
    Источники: таблица ремонтов ``krs_works`` и выполненные ремонты справки ``krs_plan`` (в справке есть ремонты, которых в таблице нет, и второй ремонт года)."""
    cols = ['well', 'year', 'kind', 'kinds', 'group', 'work_type', 'date', 'dated']
    if works is not None and not works.empty and 'year' in works:
        w = works.dropna(subset=['year']).copy()
        w['well'], w['year'] = w.well.astype(str), w.year.astype(int)
        w['work_type'] = w.get('work_type', pd.Series('', index=w.index)).fillna('').astype(str)
        codes = w['detail'].fillna('').astype(str) if 'detail' in w else pd.Series('', index=w.index)
        w['kind'] = [repair_class(t, c) for t, c in zip(w.work_type, codes)]
        w['kinds'] = ['; '.join(dict.fromkeys(repair_classes(t, c))) for t, c in zip(w.work_type, codes)]
        w['date'] = pd.to_datetime(w.year.astype(str) + '-07-01')
        w['dated'] = False
    else:
        w = pd.DataFrame(columns=cols)
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
        w = pd.concat([w, _plan_only(p, w)], ignore_index=True) if len(p) else w
    w['group'] = [repair_group(k) for k in w.kinds]
    return w[cols].reset_index(drop=True)


def _plan_only(plan: pd.DataFrame, have: pd.DataFrame) -> pd.DataFrame:
    """Выполненные ремонты справки, которых нет в таблице ремонтов: той же скважины и года нет ремонта того же вида. Дата — фактическая из справки."""
    cols = ['well', 'year', 'kind', 'kinds', 'work_type', 'date', 'dated']
    state = plan['state'].fillna('') if 'state' in plan else pd.Series('', index=plan.index)
    table = plan['in_table'].fillna('') if 'in_table' in plan else pd.Series('', index=plan.index)
    d = plan[state.eq('Выполнено') & table.ne('Нет') & plan.year.notna() & plan.when.notna()]
    known = {(r.well, r.year, r.kind) for r in have.itertuples()}
    rows = []
    for r in d.itertuples():
        text = str(getattr(r, 'works', '') or '')
        kind = repair_class(text, f"{getattr(r, 'codes', '')} {text}")
        kinds = '; '.join(dict.fromkeys(repair_classes(text, f"{getattr(r, 'codes', '')} {text}")))
        key = (r.well, int(r.year), kind)
        if key in known and kind != 'прочее':
            continue
        known.add(key)
        rows.append({'well': r.well, 'year': int(r.year), 'kind': kind, 'kinds': kinds, 'work_type': text or str(getattr(r, 'codes', '') or ''), 'date': r.when, 'dated': True})
    return pd.DataFrame(rows, columns=cols)


def with_group(frame: pd.DataFrame, rep: pd.DataFrame | None, date_col: str = 'date', well_col: str = 'well') -> pd.Series:
    """Группа по ремонту для каждой строки (скважина + дата ГДИ): последний ремонт скважины до даты (включая день ГДИ), иначе «без КРС»."""
    if frame.empty:
        return pd.Series(dtype=str)
    if rep is None or rep.empty:
        return pd.Series(NO_REPAIR_GROUP, index=frame.index)
    by = {w: g.sort_values('date') for w, g in rep.groupby('well')}
    out = []
    for w, d in zip(frame[well_col].astype(str), pd.to_datetime(frame[date_col])):
        g = by.get(w)
        done = g[g.date.le(d + pd.Timedelta(days=1))] if g is not None and pd.notna(d) else None
        out.append(done.iloc[-1].group if done is not None and len(done) else NO_REPAIR_GROUP)
    return pd.Series(out, index=frame.index)
