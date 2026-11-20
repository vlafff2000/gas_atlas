"""Проверка критериев оценки на истории («машина времени»): что показали бы улики на 1 января года, в котором скважину потом ремонтировали.

Для каждого года берутся только данные ДО этой даты (сезоны, закончившиеся раньше; ГДИ и замеры забоя раньше; КР прошлых лет), по ним собираются
те же улики, что и в паспорте, скважины ранжируются по сумме уровней улик и сравниваются с фактом: какие скважины реально ушли в КР (без ТР).
Приоритет КР по ревизиям КРУ в проверку не входит: он составлен по нынешним данным, и на прошлую дату его не восстановить.
Только подсказка для подбора порогов: решает инженер.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from atlas import passport_assess, passport_depression
from atlas import well_assess as wa

POINTS = {'strong': 2.0, 'weak': 1.0}
EMPTY_NOTE = 'Нет скважин с данными до начала года: проверять не на чем.'


def _day(value: Any) -> pd.Timestamp | None:
    t = pd.to_datetime(value, errors='coerce', dayfirst=True)
    return None if pd.isna(t) else pd.Timestamp(t).normalize()


def repaired_wells(works: dict[str, list[dict[str, Any]]], year: int) -> set[str]:
    """Скважины, у которых в году был капитальный ремонт (текущий ремонт «ТР» не считается)."""
    return {w for w, rows in works.items() for r in rows if r.get('year') == year and 'ТР' not in str(r.get('type') or '').upper().split()}


def evidence_at(card: dict[str, Any], cut: pd.Timestamp, *, works: list[dict[str, Any]], bottoms: pd.DataFrame | None, filter_bottom_m: float | None,
                pressure: pd.DataFrame | None, limit: float | None) -> list[wa.Evidence]:
    """Улики по скважине так, как они выглядели бы на дату ``cut``: будущие данные не используются."""
    seasons = [s for s in card.get('seasons', []) if (_day(s.get('end')) or cut) < cut]
    done = {str(s['period']) for s in seasons if s['kind'] == 'withdrawal'}
    gdi = [g for g in card.get('gdi', []) if (_day(g.get('date')) or cut) < cut]
    elpro = [r for r in card.get('elpro', []) if str(r['period']) in done]
    daily = card.get('daily', {}).get('withdrawal') or {}
    keep = [i for i, d in enumerate(daily.get('date', [])) if (_day(d) or cut) < cut]          # суточные расходы только до даты проверки
    dep = passport_depression.season_rows(seasons, gdi, pressure, limit, {k: [v[i] for i in keep] for k, v in daily.items()})
    past = [w for w in works if w.get('year') is not None and w['year'] < cut.year]
    bottom_m = bottom_date = row = None
    if bottoms is not None and not bottoms.empty:
        old = bottoms[pd.to_datetime(bottoms['date'], errors='coerce') < cut].sort_values('date')
        if not old.empty:
            row = old.iloc[-1]
            bottom_m, bottom_date = row.get('bottom_m'), row.get('date')
            bottom_m = None if bottom_m is None or pd.isna(bottom_m) else float(bottom_m)
    return passport_assess.collect(bottom_m=bottom_m, bottom_date=bottom_date, bottom_row=row, filter_bottom_m=filter_bottom_m, krs={'works': past, 'priority': None},
                                   seasons=seasons, gdi=gdi, elpro=elpro, today=cut.strftime('%d.%m.%Y'), depression=dep)


def score(evidence: list[wa.Evidence]) -> float:
    return float(sum(POINTS.get(e.level, 0.0) * e.weight for e in evidence))


def check_year(year: int, evidence: dict[str, list[wa.Evidence]], fact: set[str]) -> dict[str, Any]:
    """Метрики за год: ранжируем скважины по сумме улик, берём столько верхних, сколько реально ремонтировали (K)."""
    wells = sorted(evidence)
    positives = {w for w in wells if w in fact}
    ranked = sorted(wells, key=lambda w: (-score(evidence[w]), w))
    k = len(positives)
    top = set(ranked[:k]) if k else set()
    hits = len(top & positives)
    base = k / len(wells) if wells else 0.0
    precision = hits / k if k else None
    flagged = {w for w in wells if any(e.level in POINTS for e in evidence[w])}
    return {'year': year, 'wells': len(wells), 'repaired': k, 'missing': len(fact - set(wells)), 'hits': hits, 'precision': precision,
            'lift': precision / base if precision is not None and base else None, 'flagged': len(flagged), 'flagged_hits': len(flagged & positives)}


def by_mechanism(years: list[dict[str, Any]], evidence: dict[int, dict[str, list[wa.Evidence]]], fact: dict[int, set[str]]) -> list[dict[str, Any]]:
    """Как часто улика механизма была у скважин, которые потом ушли в КР, и у остальных (во всех проверенных годах вместе)."""
    rows = []
    for mech, name in passport_assess.MECHANISMS.items():
        pos = neg = pos_hit = neg_hit = 0
        for year in (y['year'] for y in years):
            for well, items in evidence[year].items():
                hit = any(e.mechanism == mech and e.level in POINTS for e in items)
                if well in fact[year]:
                    pos, pos_hit = pos + 1, pos_hit + hit
                else:
                    neg, neg_hit = neg + 1, neg_hit + hit
        share_pos = pos_hit / pos if pos else None
        share_neg = neg_hit / neg if neg else None
        rows.append({'mechanism': mech, 'name': name, 'repaired_hit': pos_hit, 'repaired': pos, 'other_hit': neg_hit, 'other': neg,
                     'share_repaired': share_pos, 'share_other': share_neg,
                     'lift': share_pos / share_neg if share_pos is not None and share_neg else None})
    return rows


def run(cards: dict[str, dict[str, Any]], works: dict[str, list[dict[str, Any]]], bottoms: dict[str, pd.DataFrame], filters: dict[str, float | None],
        pressure: pd.DataFrame | None, years: list[int]) -> dict[str, Any]:
    """Проверка по всем скважинам и годам. ``cards`` — карточки паспорта (все сезоны), ``works`` — КР по скважинам."""
    evidence: dict[int, dict[str, list[wa.Evidence]]] = {}
    fact: dict[int, set[str]] = {}
    out_years = []
    for year in sorted(years):
        cut = pd.Timestamp(year, 1, 1)
        evidence[year] = {}
        for well, card in cards.items():
            if not any((_day(s.get('end')) or cut) < cut for s in card.get('seasons', [])):
                continue          # до этой даты по скважине нет ни одного сезона
            evidence[year][well] = evidence_at(card, cut, works=works.get(well, []), bottoms=bottoms.get(well), filter_bottom_m=filters.get(well),
                                               pressure=pressure, limit=(card.get('depression') or {}).get('limit'))
        fact[year] = repaired_wells(works, year)
        out_years.append(check_year(year, evidence[year], fact[year]))
    notes = ['Проверка на истории: улики собраны только по данным до 1 января года. Приоритет КР по ревизиям КРУ не входит: он составлен по нынешним данным.']
    if not any(y['wells'] for y in out_years):
        notes.append(EMPTY_NOTE)
    return {'years': out_years, 'mechanisms': by_mechanism(out_years, evidence, fact) if out_years else [], 'notes': notes}


def candidates(cards: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Сводка по фонду: скважины по убыванию суммы улик на сегодня. Берутся строки оценки самих карточек: в них уже учтены приоритет КР по ревизиям,
    решения инженера по механизмам и правки таблицы «механизм → операция»."""
    out = []
    for well, card in cards.items():
        shown = card.get('assess') or []
        main = [r for r in shown if r['level'] in POINTS]
        out.append({'well': well, 'group': card.get('group', ''), 'score': sum(POINTS[r['level']] * r['weight'] for r in main), 'manual': any(r['manual'] for r in shown),
                    'mechanisms': '; '.join(f"{r['name']} ({passport_assess.LEVEL_NAMES[r['level']]})" for r in main),
                    'recommendation': '; '.join(dict.fromkeys(r['recommendation'] for r in main if r['recommendation']))})
    return sorted(out, key=lambda r: (-r['score'], r['well']))
