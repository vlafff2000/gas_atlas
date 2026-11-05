"""Давление из термобарики ГИС, приведённое к одной глубине (по умолчанию −670 м а.о.).

Только выбор данных и простая арифметика; никакого нового метода: глубина а.о. = альтитуда − MD (как в «Положении и перфорации»),
перепад давления по флюиду — тот же градиент ρ/10 кгс/см² на метр, что в формулах пересчёта давлений
(all_scripts: pxg_core/пересчет_давлений.py, J = (…)·ρ/10).

Правило подсказки (последнее слово за инженером — точки отключаются в таблице исходных замеров, подсказка пересчитывается):
  * замер на глубине приведения (в пределах ``EXACT_M``) берётся как есть;
  * по обе стороны глубины есть замеры — две ближайшие по глубине точки, линейная интерполяция (средний тренд между ними);
    если в интервале заполнения известна плотность жидкости — от ближайшей точки по плотности, линейное значение остаётся в пояснении;
  * замеры только с одной стороны — продолжение тренда по двум ближайшим точкам или от ближайшей по плотности жидкости,
    не дальше ``EXTRAPOLATE_M`` от ближайшего замера;
  * иначе значения нет, причина названа.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .gis_well import _altitude

TARGET_ABS = -670.0           # м а.о.: глубина приведения давлений ПХГ (одна для всех скважин)
EXACT_M = 3.0                 # замер ближе этого к глубине приведения берётся без пересчёта
EXTRAPOLATE_M = 150.0         # дальше от ближайшего замера значение не оценивается
GAP_WARN_M = 250.0            # расстояние между опорными точками больше — «проверить»
LIQUID = ('вода', 'жидкость')
COLUMNS = ['well', 'date', 'pressure', 'method', 'check', 'reason', 'depth1', 'p1', 'depth2', 'p2', 'rho', 'fill']


def _num(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _fmt(v: float) -> str:
    return f'{v:.1f}'.replace('.', ',')


def points_ao(thermo: pd.DataFrame, geo: pd.DataFrame | None, packs: pd.DataFrame | None) -> pd.DataFrame:
    """Точки термобарики с давлением: глубина а.о. (``z_ao``) и её источник. Приоритет — альтитуда проекта (MD → а.о.), иначе а.о. из отчёта.
    Давление ≤ 0 (начало записи у устья) и строки без давления отбрасываются."""
    if thermo is None or thermo.empty or not {'well', 'date', 'depth_m', 'pressure_kgs'} <= set(thermo.columns):
        return pd.DataFrame(columns=['well', 'date', 'md', 'z_ao', 'p', 'how', 'ok', '_point_id'])
    d = thermo.copy()
    d['p'] = pd.to_numeric(d['pressure_kgs'], errors='coerce')
    d['md'] = pd.to_numeric(d['depth_m'], errors='coerce')
    d = d[d.p.gt(0) & d.md.notna() & d.date.notna()].copy()
    report = pd.to_numeric(d['depth_abs_m'], errors='coerce') if 'depth_abs_m' in d else pd.Series(np.nan, index=d.index)
    alt = d['well'].astype(str).map({w: _altitude(w, geo, packs) for w in d['well'].astype(str).unique()})
    mine = alt - d.md
    d['z_ao'] = mine.where(mine.notna(), report)
    d['how'] = np.where(mine.notna(), 'по альтитуде проекта', np.where(report.notna(), 'а.о. из отчёта', 'нет альтитуды'))
    d['ok'] = ~(mine.notna() & report.notna() & ((mine - report).abs() > EXACT_M))       # расхождение альтитуды проекта и отчёта
    d['well'] = d['well'].astype(str)
    return d[d.z_ao.notna()].reset_index(drop=True)


def _density(filling: pd.DataFrame | None, well: str, date, md_target: float | None) -> tuple[float | None, str]:
    """Плотность жидкости (г/см³) и вид заполнения в интервале, где лежит глубина приведения (по MD); плотность — среднее «от» и «до»."""
    if filling is None or filling.empty or md_target is None:
        return None, ''
    f = filling[filling['well'].astype(str).eq(well) & filling['date'].eq(date)]
    if f.empty:
        return None, ''
    lo, hi = pd.to_numeric(f.get('from_m'), errors='coerce'), pd.to_numeric(f.get('to_m'), errors='coerce')
    inside = f[(lo.isna() | hi.isna()) | ((lo <= md_target) & (md_target <= hi))]
    for row in inside.itertuples():
        kind = str(getattr(row, 'fill', '') or '')
        values = [v for v in (_num(getattr(row, 'density_min', None)), _num(getattr(row, 'density_max', None))) if v]
        if values and kind in LIQUID:
            return float(np.mean(values)), kind
    kinds = [str(getattr(r, 'fill', '') or '') for r in inside.itertuples() if getattr(r, 'fill', '')]
    return None, kinds[0] if kinds else ''


def _row(well, date, pressure, method, reason, check='', d1=None, p1=None, d2=None, p2=None, rho=None, fill=''):
    return dict(zip(COLUMNS, [well, date, pressure, method, check, reason, d1, p1, d2, p2, rho, fill]))


def reduce_group(well: str, date, pts: pd.DataFrame, target: float, rho: float | None, fill: str, md_target: float | None) -> dict:
    """Одно давление скважины на дату, приведённое к ``target``. ``pts`` — точки одной скважины и даты (z_ao, p)."""
    where = f'скв. {well}, {pd.Timestamp(date):%d.%m.%Y}'
    pts = pts.sort_values('z_ao').reset_index(drop=True)
    near = (pts.z_ao - target).abs().idxmin()
    if abs(pts.z_ao[near] - target) <= EXACT_M:
        return _row(well, date, float(pts.p[near]), 'замер на глубине приведения',
                    f'{where}: замер {_fmt(pts.md[near])} м MD ({_fmt(pts.z_ao[near])} м а.о.) в пределах {EXACT_M:g} м от {_fmt(target)} м а.о.',
                    d1=pts.z_ao[near], p1=pts.p[near])
    lo = pts[pts.z_ao < target].tail(1)       # ближайшая более глубокая точка (а.о. меньше, т. е. ниже)
    hi = pts[pts.z_ao > target].head(1)       # ближайшая менее глубокая
    liquid = rho is not None and fill in LIQUID
    if len(lo) and len(hi):
        a, b = lo.iloc[0], hi.iloc[0]
        linear = float(a.p + (b.p - a.p) * (target - a.z_ao) / (b.z_ao - a.z_ao))
        mark = '' if b.z_ao - a.z_ao <= GAP_WARN_M else f'опорные точки далеко друг от друга ({_fmt(b.z_ao - a.z_ao)} м)'
        if a.p < b.p:        # давление должно расти с глубиной (глубже = меньше z_ao; a — более глубокая точка)
            mark = (mark + '; ' if mark else '') + 'давление падает с глубиной: проверить замеры'
        span = (f'между {_fmt(a.md)} м MD ({_fmt(a.z_ao)} м а.о., {_fmt(a.p)} кгс/см²) и {_fmt(b.md)} м MD ({_fmt(b.z_ao)} м а.о., {_fmt(b.p)} кгс/см²)')
        if liquid:
            ref = a if abs(a.z_ao - target) <= abs(b.z_ao - target) else b
            value = float(ref.p + rho / 10.0 * (ref.z_ao - target))
            return _row(well, date, value, 'по плотности жидкости',
                        f'{where}: {span}; в интервале {fill}, ρ = {_fmt(rho)} г/см³ — от ближайшего замера по градиенту ρ/10 (линейно было бы {_fmt(linear)})',
                        mark, a.z_ao, a.p, b.z_ao, b.p, rho, fill)
        return _row(well, date, linear, 'интерполяция', f'{where}: {span}, линейный тренд на {_fmt(target)} м а.о.',
                    mark, a.z_ao, a.p, b.z_ao, b.p, rho, fill)
    ref = pts.loc[(pts.z_ao - target).abs().idxmin()]
    gap = abs(ref.z_ao - target)
    if gap > EXTRAPOLATE_M:
        return _row(well, date, None, 'нет значения', f'{where}: ближайший замер ({_fmt(ref.z_ao)} м а.о.) в {_fmt(gap)} м от {_fmt(target)} м а.о., дальше {EXTRAPOLATE_M:g} м не продолжаем',
                    d1=ref.z_ao, p1=ref.p, rho=rho, fill=fill)
    if liquid:
        value = float(ref.p + rho / 10.0 * (ref.z_ao - target))
        return _row(well, date, value, 'по плотности жидкости',
                    f'{where}: замеры только с одной стороны, ближайший {_fmt(ref.md)} м MD ({_fmt(ref.z_ao)} м а.о., {_fmt(ref.p)} кгс/см²); {fill}, ρ = {_fmt(rho)} г/см³ — градиент ρ/10',
                    'продолжение за пределы замеров', ref.z_ao, ref.p, None, None, rho, fill)
    if len(pts) >= 2:
        order = (pts.z_ao - target).abs().sort_values().index[:2]
        a, b = pts.loc[order[0]], pts.loc[order[1]]
        if a.z_ao != b.z_ao:
            value = float(a.p + (b.p - a.p) * (target - a.z_ao) / (b.z_ao - a.z_ao))
            return _row(well, date, value, 'продолжение тренда',
                        f'{where}: замеры только с одной стороны ({_fmt(a.z_ao)} и {_fmt(b.z_ao)} м а.о.), тренд двух ближайших точек продолжен до {_fmt(target)} м а.о.',
                        'продолжение за пределы замеров', a.z_ao, a.p, b.z_ao, b.p, rho, fill)
    return _row(well, date, None, 'нет значения', f'{where}: один замер ({_fmt(ref.z_ao)} м а.о.), плотности жидкости нет — перепад до {_fmt(target)} м а.о. не оценить',
                d1=ref.z_ao, p1=ref.p, rho=rho, fill=fill)


def reduce_pressure(thermo: pd.DataFrame | None, filling: pd.DataFrame | None, geo: pd.DataFrame | None = None,
                    packs: pd.DataFrame | None = None, target: float = TARGET_ABS, wells=None) -> pd.DataFrame:
    """Давление ГИС на глубине приведения: по строке на скважину и дату. Столбцы — ``COLUMNS``; без значения (``pressure`` пусто) — тоже строка с причиной."""
    pts = points_ao(thermo, geo, packs)
    if wells is not None:
        pts = pts[pts.well.isin({str(w) for w in wells})]
    rows = []
    for (well, date), g in pts.groupby(['well', 'date'], sort=True):
        alt = _altitude(well, geo, packs)
        md_target = None if alt is None else alt - target
        rho, fill = _density(filling, well, date, md_target)
        row = reduce_group(well, date, g, target, rho, fill, md_target)
        bad = g[~g.ok]
        if len(bad):
            row['check'] = (row['check'] + '; ' if row['check'] else '') + f'глубина а.о. в отчёте расходится с альтитудой проекта более чем на {EXACT_M:g} м ({len(bad)} точ.)'
        rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)
