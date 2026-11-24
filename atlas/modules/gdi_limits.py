"""Справка ГДИ: предельные депрессии и расходы — «технологическая карта» по скважинам и группам.

Для каждой скважины: предел депрессии (вручную; иначе по типу забоя из конструкции — подсказка с видимым источником), расход по самому свежему
надёжному ГДИ при этом пределе и его падение при снижении Рпл с шагом (по умолчанию 10 кгс/см²). Математика — ``atlas.limit_flow``;
здесь только выбор данных и представление. Примечания: песок/разрушения КРУ по ревизиям (``krs_priority``), давность ГДИ, оценка вне диапазона ГДИ.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from atlas import limit_flow as lf, passport_depression
from atlas.engine.core.config import natural_key
from atlas.engine.modules import well_analysis

from ..contract import CellStyle, Column, Data, Module, ModuleSpec, Note, Param, Result, Stat, Table
from ..domain import DatasetKind
from .gdi import well_key

GDI, CONSTRUCTION, PRIORITY = DatasetKind.GDI, DatasetKind.CONSTRUCTION, DatasetKind.KRS_PRIORITY
SECTION = 'Выбор данных'
BAND = ('EAF1FB', 'FFFFFF')
NOTE = ('Предельный расход — максимальный расход при депрессии не выше предела: Рпл² − (Рпл − dP)² = a·q + b·q², давления абсолютные. '
        'При падении Рпл доступный перепад давлений уменьшается, поэтому расход при той же депрессии снижается — это и показано по столбцам. '
        'Коэффициенты a и b — из самого свежего надёжного ГДИ и приняты неизменными. Предел — подсказка: источник виден, значение правится '
        'в параметре «Пределы вручную». Без ГДИ или без предела расход не считается.')


def latest_studies(gdi: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """По каждой скважине — самое свежее надёжное ГДИ: well, date, a, b, p_res, q_observed; нет надёжного — скважина без строки."""
    if gdi is None or gdi.empty:
        return pd.DataFrame(columns=['well', 'date', 'a', 'b', 'p_res', 'q_observed'])
    h = well_analysis.gdi_history(gdi, threshold)
    h = h[h.reliable & h.a.notna() & h.b.notna()].copy()
    h['well'] = h.well.astype(str)
    h['date'] = pd.to_datetime(h.date)
    return h.sort_values('date').groupby('well', as_index=False).tail(1)[['well', 'date', 'a', 'b', 'p_res', 'q_observed']].reset_index(drop=True)


def sand_note(priority: pd.DataFrame | None, well: str) -> str:
    """Примечание по ревизиям КРУ: сезоны с песком (разрушение — сигнал ограничить депрессию)."""
    if priority is None or priority.empty or 'sand' not in priority:
        return ''
    from atlas import passport_tiles
    mine = priority[priority.well.astype(str).eq(well)]
    seasons = sorted({s for v in mine.sand for s in passport_tiles.sand_seasons(v)})
    return f'КРУ: песок в ревизиях {", ".join(seasons)} — ограничить депрессию' if seasons else ''


def auto_start(p_res: pd.Series, step: float) -> float:
    """Верх сетки Рпл: медиана Рпл последних ГДИ, округлённая вверх до шага."""
    p = p_res.dropna()
    return math.ceil(float(p.median()) / step) * step if len(p) else 0.0


def build_rows(studies: pd.DataFrame, wells: list[str], mapping: dict, limits: dict[str, float], types: list[dict], manual_type: dict,
               kinds: dict[str, set], grid: list[float], priority: pd.DataFrame | None, today: pd.Timestamp, old_years: float) -> list[dict[str, Any]]:
    by_well = studies.set_index('well')
    rows = []
    for w in wells:
        key = passport_depression.well_type(kinds.get(w, set()), types, manual_type.get(w))
        t_name = next((t['name'] for t in types if t['key'] == key), '')
        dp, source = lf.pick_limit(w, limits, next((t['limit'] for t in types if t['key'] == key), None), t_name)
        row: dict[str, Any] = {'group': (mapping.get(w) or {}).get('group') or 'Без группы', 'well': w, 'type': t_name or '—', 'dp': dp, 'source': source,
                               'date': pd.NaT, 'p_gdi': None, 'q_gdi': None, 'q_obs': None, 'drop': None}
        notes = []
        if w in by_well.index:
            s = by_well.loc[w]
            f = lf.flow_row(float(s.a), float(s.b), dp, grid, s.p_res if pd.notna(s.p_res) else None, s.q_observed if pd.notna(s.q_observed) else None) if dp else None
            row.update(date=s.date, p_gdi=None if pd.isna(s.p_res) else float(s.p_res), q_obs=None if pd.isna(s.q_observed) else float(s.q_observed))
            if f:
                row['q_gdi'] = f['q_gdi']
                vals = [f[p] for p in grid]
                row.update({lf_key(p): f[p] for p in grid})
                if len(vals) > 1 and vals[0] and vals[-1] is not None:
                    row['drop'] = (vals[-1] / vals[0] - 1) * 100
                if f['rough']:
                    notes.append(f'при Рпл {", ".join(f"{p:g}" for p in f["rough"])} расход выше Qmax ГДИ ({s.q_observed:g}): оценка грубая')
            elif not dp:
                notes.append('предел депрессии не задан — расход не считается')
            if (today - s.date).days > old_years * 365.25:
                notes.append(f'ГДИ старше {old_years:g} лет')
        else:
            notes.append('нет надёжного ГДИ')
        sand = sand_note(priority, w)
        if sand:
            notes.insert(0, sand)
        row['note'] = '; '.join(notes)
        rows.append(row)
    return rows


def lf_key(p: float) -> str:
    return f'q_{p:g}'


class GdiLimitsModule(Module):
    spec = ModuleSpec(
        id='gdi_limits',
        title='Справка ГДИ: предельные депрессии и расходы',
        group='Исследования скважин',
        description='По каждой скважине и группе: предельная депрессия, максимальный расход по свежему ГДИ при этом пределе и как он падает '
                    'при снижении пластового давления; в примечаниях — песок и разрушения КРУ по ревизиям.',
        needs=(GDI,),
        optional=(CONSTRUCTION, PRIORITY),
        order=37,
        params=(
            Param('threshold', 'Порог R²', 'number', default=0.95, minimum=0.0, maximum=1.0, step=0.01, setting='r2_threshold', section=SECTION,
                  help='Общая настройка проекта: расход считается по самому свежему надёжному ГДИ.'),
            Param('p_start', 'Рпл сверху сетки, кгс/см²', 'number', default=0, minimum=0, maximum=1000, step=1, section=SECTION,
                  help='Абсолютное давление. 0 — автоматически: медиана Рпл последних ГДИ, округлённая вверх до шага.'),
            Param('p_step', 'Шаг по Рпл, кгс/см²', 'number', default=10, minimum=1, maximum=100, step=1, section=SECTION),
            Param('p_count', 'Число значений Рпл', 'number', default=6, minimum=1, maximum=15, step=1, section=SECTION,
                  help='Столбцов расхода: от верха сетки вниз с заданным шагом (сезон отбора — падение Рпл).'),
            Param('limits', 'Пределы вручную, кгс/см²', 'text', default='', section='Пределы депрессии',
                  help='Строки «скважина=значение», например «523=0,73». Главнее авто-подсказки по конструкции '
                       '(расширка и перфорация — пределы из паспорта скважины); например, из ГДИ на вынос песка.'),
            Param('old_years', 'ГДИ старше, лет', 'number', default=3.0, minimum=0.5, maximum=30, step=0.5, section='Пределы депрессии',
                  help='В примечании отмечается, что ГДИ, по которому считан расход, давнее этого срока.'),
        ),
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        gdi = data[GDI]
        studies = latest_studies(gdi, float(params['threshold']))
        wells = sorted({str(w) for w in gdi.well}, key=well_key) if gdi is not None and not gdi.empty else []
        if not wells:
            result.notes.append(Note('Исследований ГДИ в проекте нет.', 'warning'))
            return result
        step = float(params['p_step'] or 10)
        start = float(params['p_start'] or 0) or auto_start(studies.p_res, step)
        grid = lf.pressure_grid(start, step, int(params['p_count'] or 6))
        if not grid:
            result.notes.append(Note('Нет давлений для сетки: в ГДИ нет Рпл. Задайте «Рпл сверху сетки».', 'warning'))
            return result
        cfg = getattr(data, 'settings', None) or {}
        from atlas.passport_card import classify
        cons = data.get(CONSTRUCTION)
        kinds = ({str(w): {classify(str(e)) for e in g.element} for w, g in cons.groupby('well')}
                 if cons is not None and not cons.empty else {})
        rows = build_rows(studies, wells, getattr(data, 'mapping', {}) or {}, lf.parse_limits(params['limits']), passport_depression.types_of(cfg),
                          cfg.get('well_depression_type') or {}, kinds, grid, data.get(PRIORITY), pd.Timestamp.today().normalize(), float(params['old_years']))
        rows.sort(key=lambda r: (natural_key(r['group']), well_key(r['well'])))
        frame = pd.DataFrame(rows)
        for p in grid:
            if lf_key(p) not in frame:
                frame[lf_key(p)] = np.nan
        keys = ['group', 'well', 'type', 'dp', 'source', 'date', 'p_gdi', 'q_gdi'] + [lf_key(p) for p in grid] + ['drop', 'q_obs', 'note']
        frame = frame[keys]
        cols = [Column('group', 'Группа'), Column('well', 'Скважина'), Column('type', 'Тип забоя'),
                Column('dp', 'Предел депрессии', 'кгс/см²', 2, 'number'), Column('source', 'Источник предела'),
                Column('date', 'ГДИ', kind='date'), Column('p_gdi', 'Рпл ГДИ', 'кгс/см²', 1, 'number'),
                Column('q_gdi', 'Q при пределе (Рпл ГДИ)', 'тыс. м³/сут', 0, 'number')]
        cols += [Column(lf_key(p), f'{p:g}', '', 0, 'number') for p in grid]
        cols += [Column('drop', f'Изменение Q по сетке', '%', 0, 'number'), Column('q_obs', 'Qmax ГДИ', 'тыс. м³/сут', 0, 'number'), Column('note', 'Примечание')]
        static = 8
        groups = list(frame.group)
        styles, band = [], 0
        for i, g in enumerate(groups):
            if i == 0 or g != groups[i - 1]:
                band, styles = band + 1, styles + [CellStyle([i], border='top')]
            styles.append(CellStyle([i], fill=BAND[band % 2]))
        styles.append(CellStyle(list(range(len(frame))), columns=[lf_key(grid[0])], border='left'))
        result.tables.append(Table('gdi-limits-map', 'Технологическая карта: предельная депрессия и расход', frame, cols, note=NOTE,
                                   header=[[('', static), (f'Предельный расход при Рпл, кгс/см² (тыс. м³/сут)', len(grid)), ('', 3)]], styles=styles))
        done = int(frame[lf_key(grid[0])].notna().sum())
        result.summary = [Stat('Скважин', str(len(frame)), f'групп: {frame.group.nunique()}'), Stat('Расход посчитан', str(done), 'есть надёжное ГДИ и предел депрессии'),
                          Stat('Без предела', str(int(frame.dp.isna().sum())), 'задайте вручную или загрузите конструкцию'),
                          Stat('Без надёжного ГДИ', str(int(frame.date.isna().sum())))]
        return result
