"""Фонды скважин проекта: эксплуатационная, наблюдательная, геофизическая, контрольная.

Решение за инженером: ``settings['well_funds']`` = {скважина: фонд}. Автоопределение — только подсказка с видимой причиной,
ручной выбор важнее. Сводка лежит в проекте Атласа, «Карты» и другие программы читают её оттуда.

Подсказка: скважина в группах или с расходами — эксплуатационная; вне групп с перфорацией или замерами давления — наблюдательная
(есть связь с пластом); вне групп, только ГИС и без перфораций — геофизическая.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

import pandas as pd

from .contract import ParamError

KEY = 'well_funds'
FUNDS = (('production', 'Эксплуатационная'), ('observation', 'Наблюдательная'),
         ('geophysical', 'Геофизическая'), ('control', 'Контрольная'))
LABEL = dict(FUNDS)
AUTO = 'auto'


def norm(well: Any) -> str:
    """«31», 31, «31.0» — одна скважина."""
    text = str(well).strip()
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def _wells(frame: pd.DataFrame | None, column: str = 'well') -> set[str]:
    if frame is None or frame.empty or column not in frame:
        return set()
    return {norm(w) for w in frame[column].dropna().unique() if str(w).strip()}


def hint(in_groups: bool, gis: bool, pressure: bool, perforated: bool) -> tuple[str, str]:
    """(фонд, причина) по признакам скважины; пустой фонд — подсказки нет."""
    if in_groups:
        return 'production', 'есть в группах или в расходах'
    if perforated:
        return 'observation', 'вне групп, перфорация есть'
    if pressure:
        return 'observation', 'вне групп, есть замеры давления (связь с пластом)'
    if gis:
        return 'geophysical', 'вне групп, есть только ГИС: перфораций и замеров давления нет'
    return '', 'нет признаков: выберите фонд вручную'


def manual_of(settings: Mapping[str, Any]) -> dict[str, str]:
    saved = settings.get(KEY) or {}
    return {norm(w): str(f) for w, f in saved.items() if str(f) in LABEL}


def table(frames: Mapping[str, pd.DataFrame], groups: Mapping[str, str], settings: Mapping[str, Any]) -> list[dict]:
    """Строки таблицы фондов: скважина, группа, итоговый фонд, подсказка с причиной, признак ручного выбора."""
    prod = _wells(frames.get('production'))
    gis = _wells(frames.get('gis_packs')) | _wells(frames.get('gis_observations'))
    press = _wells(frames.get('pressure_match')) | _wells(frames.get('response'))
    geo = frames.get('well_geo')
    perf: set[str] = set()
    known_geo = _wells(geo)
    if geo is not None and not geo.empty and {'perf_top', 'perf_bottom'} <= set(geo.columns):
        both = geo[geo.perf_top.notna() & geo.perf_bottom.notna()]
        perf = _wells(both)
    grouped = {norm(w): str(g) for w, g in groups.items() if str(g or '').strip() and str(g) != 'Без группы'}
    manual = manual_of(settings)
    names = prod | gis | press | known_geo | set(grouped) | set(manual)
    rows = []
    for w in names:
        fund, why = hint(w in prod or w in grouped, w in gis, w in press, w in perf)
        mine = manual.get(w, '')
        sources = [n for n, s in (('расходы', prod), ('ГИС', gis), ('давления', press), ('перфорация', perf), ('координаты', known_geo)) if w in s]
        rows.append({'well': w, 'group': grouped.get(w, ''), 'fund': mine or fund, 'hint': fund, 'reason': why,
                     'manual': bool(mine), 'sources': sources})
    rows.sort(key=lambda r: (not r['well'].isdigit(), int(r['well']) if r['well'].isdigit() else 0, r['well']))
    return rows


def with_funds(settings: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """Настройки с ручными фондами: ``auto`` или пустое значение снимает выбор. Пустое множество изменений — ошибка."""
    if not isinstance(changes, Mapping) or not changes:
        raise ParamError('Нет изменений для сохранения')
    saved = manual_of(settings)
    for well, fund in changes.items():
        fund = str(fund or '').strip()
        if fund in ('', AUTO):
            saved.pop(norm(well), None)
        elif fund in LABEL:
            saved[norm(well)] = fund
        else:
            raise ParamError('Фонд должен быть одним из: ' + ', '.join(LABEL.values()) + ' (или «авто»).')
    return {**settings, KEY: saved}


def fund_of(settings: Mapping[str, Any], well: Any) -> str:
    """Ручной фонд скважины или пустая строка (читают другие программы)."""
    return manual_of(settings).get(norm(well), '')


def wells_of(settings: Mapping[str, Any], fund: str) -> list[str]:
    return sorted(w for w, f in manual_of(settings).items() if f == fund)
