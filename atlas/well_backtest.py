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


def repaired_wells(works: dict[str, list[dict[str, Any]]], year: int, horizon: int = 1) -> set[str]:
    """Скважины, у которых в году проверки или в ``horizon - 1`` следующих был капитальный ремонт (текущий ремонт «ТР» не считается)."""
    return {w for w, rows in works.items() for r in rows
            if r.get('year') is not None and year <= r['year'] < year + max(1, horizon) and 'ТР' not in str(r.get('type') or '').upper().split()}


PERF_DROP = -10.0           # падение среднего расхода сезона отбора, %, начиная с которого продуктивность считается реально упавшей


def _season_rate(card: dict[str, Any], pick) -> tuple[pd.Timestamp, float] | None:
    rows = [(d, float(s['mean_rate'])) for s in card.get('seasons', []) if s.get('kind') == 'withdrawal' and s.get('mean_rate') is not None
            for d in [_day(s.get('end'))] if d is not None]
    rows = pick(sorted(rows))
    return rows[0] if rows else None


def perf_change(card: dict[str, Any], cut: pd.Timestamp) -> dict[str, float] | None:
    """Реальное изменение продуктивности: средний расход первого сезона отбора после даты против последнего до неё, %.
    Индикатор для проверки отметки (на расход влияют режим и давление), не замер продуктивности: решает инженер."""
    prev = _season_rate(card, lambda r: [x for x in r if x[0] < cut][-1:])
    nxt = _season_rate(card, lambda r: [x for x in r if cut <= x[0] < cut + pd.Timedelta(days=500)][:1])
    if not prev or not nxt or prev[1] <= 0:
        return None
    return {'prev': prev[1], 'next': nxt[1], 'change': (nxt[1] / prev[1] - 1) * 100}


def perf_last(card: dict[str, Any]) -> float | None:
    """Изменение среднего расхода двух последних сезонов отбора, % (для сводки по фонду на сегодня)."""
    rows = sorted((d, float(s['mean_rate'])) for s in card.get('seasons', []) if s.get('kind') == 'withdrawal' and s.get('mean_rate') is not None
                  for d in [_day(s.get('end'))] if d is not None)
    return (rows[-1][1] / rows[-2][1] - 1) * 100 if len(rows) >= 2 and rows[-2][1] > 0 else None


def last_kr(card: dict[str, Any]) -> int | None:
    """Год последнего капитального ремонта (текущий ремонт «ТР» не считается)."""
    years = [w['year'] for w in (card.get('krs') or {}).get('works', []) if w.get('year') is not None and 'ТР' not in str(w.get('type') or '').upper().split()]
    return max(years) if years else None


def filter_at(value: Any, cut: pd.Timestamp) -> float | None:
    """Низ фильтра/перфорации на дату: число (одна конструкция) или список (дата, низ) — берётся последняя конструкция до даты."""
    if not isinstance(value, list):
        return value
    old = [low for d, low in value if d < cut]
    return old[-1] if old else None


def evidence_at(card: dict[str, Any], cut: pd.Timestamp, *, works: list[dict[str, Any]], bottoms: pd.DataFrame | None, filter_bottom_m: float | None,
                pressure: pd.DataFrame | None, limit: float | None, features: dict[str, Any] | None = None,
                dep_min_dates: float = passport_assess.DEP_STRONG_DATES) -> list[wa.Evidence]:
    """Улики по скважине так, как они выглядели бы на дату ``cut``: будущие данные не используются.

    ``features`` (если дан) заполняется сырыми значениями для перебора порогов: депрессии на датах замеров Рпл последнего сезона с предельной
    депрессией скважины и показатели ЭЛПРО последнего сезона (доля суток с КРУ ≥ 90 %, изменение расхода на 1 % КРУ)."""
    seasons = [s for s in card.get('seasons', []) if (_day(s.get('end')) or cut) < cut]
    done = {str(s['period']) for s in seasons if s['kind'] == 'withdrawal'}
    gdi = [g for g in card.get('gdi', []) if (_day(g.get('date')) or cut) < cut]
    elpro = [r for r in card.get('elpro', []) if str(r['period']) in done]
    daily = card.get('daily', {}).get('withdrawal') or {}
    keep = [i for i, d in enumerate(daily.get('date', [])) if (_day(d) or cut) < cut]          # суточные расходы только до даты проверки
    dep = passport_depression.season_rows(seasons, gdi, pressure, limit, {k: [v[i] for i in keep] for k, v in daily.items()})
    if features is not None:
        last_dep = next((r for r in reversed(dep) if r.get('points')), None)
        if last_dep:
            features['dep'] = {'limit': limit, 'deps': [p['dep'] for p in last_dep['points']]}
        last_el = next((r for r in reversed(elpro) if r.get('verdict') in ('норма', 'внимание')), None)
        if last_el:
            features['elpro'] = {'high_share': last_el.get('high_share'), 'eff_change': last_el.get('eff_change')}
    past = [w for w in works if w.get('year') is not None and w['year'] < cut.year]
    bottom_m = bottom_date = row = None
    if bottoms is not None and not bottoms.empty:
        old = bottoms[pd.to_datetime(bottoms['date'], errors='coerce') < cut].sort_values('date')
        if not old.empty:
            row = old.iloc[-1]
            bottom_m, bottom_date = row.get('bottom_m'), row.get('date')
            bottom_m = None if bottom_m is None or pd.isna(bottom_m) else float(bottom_m)
    return passport_assess.collect(bottom_m=bottom_m, bottom_date=bottom_date, bottom_row=row, filter_bottom_m=filter_bottom_m, krs={'works': past, 'priority': passport_assess.sand_priority_at((card.get('krs', {}).get('priority') or {}).get('sand'), works, cut.year)},
                                   seasons=seasons, gdi=gdi, elpro=elpro, today=cut.strftime('%d.%m.%Y'), depression=dep, dep_min_dates=dep_min_dates)


def score(evidence: list[wa.Evidence], weights: dict[str, float] | None = None) -> float:
    """Сумма баллов улик; ``weights`` (применённые инженером) — множители механизмов и ``weak``, баллы слабой улики."""
    w = weights or {}
    return float(sum((w.get('weak', 1.0) if e.level == 'weak' else POINTS.get(e.level, 0.0)) * w.get(e.mechanism, 1.0) * e.weight for e in evidence))


def check_year(year: int, evidence: dict[str, list[wa.Evidence]], fact: set[str], weights: dict[str, float] | None = None) -> dict[str, Any]:
    """Метрики за год: ранжируем скважины по сумме улик, берём столько верхних, сколько реально ремонтировали (K)."""
    wells = sorted(evidence)
    positives = {w for w in wells if w in fact}
    ranked = sorted(wells, key=lambda w: (-score(evidence[w], weights), w))
    k = len(positives)
    top = set(ranked[:k]) if k else set()
    hits = len(top & positives)
    base = k / len(wells) if wells else 0.0
    precision = hits / k if k else None
    flagged = {w for w in wells if any(e.level in POINTS for e in evidence[w])}
    return {'year': year, 'wells': len(wells), 'repaired': k, 'missing': len(fact - set(wells)), 'hits': hits, 'precision': precision,
            'lift': precision / base if precision is not None and base else None, 'flagged': len(flagged), 'flagged_hits': len(flagged & positives)}


def by_mechanism(years: list[dict[str, Any]], evidence: dict[int, dict[str, list[wa.Evidence]]], fact: dict[int, set[str]]) -> list[dict[str, Any]]:
    """Как часто улика механизма была у скважин, которые потом ушли в КР, и у остальных; считаются скважино-годы (скважина в проверяемом году), все годы вместе."""
    rows = []
    for mech, name in passport_assess.MECHANISMS.items():
        pos = neg = pos_hit = neg_hit = pos_strong = neg_strong = 0
        for year in (y['year'] for y in years):
            for well, items in evidence[year].items():
                hit = any(e.mechanism == mech and e.level in POINTS for e in items)
                strong = any(e.mechanism == mech and e.level == 'strong' for e in items)
                if well in fact[year]:
                    pos, pos_hit, pos_strong = pos + 1, pos_hit + hit, pos_strong + strong
                else:
                    neg, neg_hit, neg_strong = neg + 1, neg_hit + hit, neg_strong + strong
        share_pos = pos_hit / pos if pos else None
        share_neg = neg_hit / neg if neg else None
        rows.append({'mechanism': mech, 'name': name, 'repaired_hit': pos_hit, 'repaired': pos, 'other_hit': neg_hit, 'other': neg,
                     'share_repaired': share_pos, 'share_other': share_neg,
                     'lift': share_pos / share_neg if share_pos is not None and share_neg else None,
                     'strong_repaired': pos_strong / pos if pos else None, 'strong_other': neg_strong / neg if neg else None,
                     'strong_lift': (pos_strong / pos) / (neg_strong / neg) if pos and neg and neg_strong else None})
    return rows


def run(cards: dict[str, dict[str, Any]], works: dict[str, list[dict[str, Any]]], bottoms: dict[str, pd.DataFrame], filters: dict[str, float | None],
        pressure: pd.DataFrame | None, years: list[int], thresholds: dict[str, float] | None = None, weights: dict[str, float] | None = None,
        keep: dict[str, Any] | None = None, horizon: int = 1) -> dict[str, Any]:
    """Проверка по всем скважинам и годам. ``cards`` — карточки паспорта (все сезоны), ``works`` — КР по скважинам, ``thresholds`` — применённые пороги."""
    th = {**passport_assess.thresholds_of(None), **(thresholds or {})}
    feats: dict[int, dict[str, dict[str, Any]]] = {}
    evidence: dict[int, dict[str, list[wa.Evidence]]] = {}
    fact: dict[int, set[str]] = {}
    out_years = []
    for year in sorted(years):
        cut = pd.Timestamp(year, 1, 1)
        evidence[year], feats[year] = {}, {}
        for well, card in cards.items():
            if not any((_day(s.get('end')) or cut) < cut for s in card.get('seasons', [])):
                continue          # до этой даты по скважине нет ни одного сезона
            feats[year][well] = {'perf': perf_change(card, cut)}
            evidence[year][well] = evidence_at(card, cut, works=works.get(well, []), bottoms=bottoms.get(well), filter_bottom_m=filter_at(filters.get(well), cut),
                                               pressure=pressure, limit=(card.get('depression') or {}).get('limit'), features=feats[year][well],
                                               dep_min_dates=th['dep_min_dates'])
        fact[year] = repaired_wells(works, year, horizon)
        out_years.append(check_year(year, evidence[year], fact[year], weights))
    notes = [f'Проверка на истории: улики собраны только по данным до 1 января года; ремонт считается, если он был в течение {horizon} календарных лет, начиная с года проверки; конструкция берётся на дату; приоритет КР по ревизиям КРУ восстановлен на дату по сезонам с песком и ремонтам.']
    if not any(y['wells'] for y in out_years):
        notes.append(EMPTY_NOTE)
    if keep is not None:
        keep.update(feats=feats, evidence=evidence, fact=fact, thresholds=th)
    return {'years': out_years, 'mechanisms': by_mechanism(out_years, evidence, fact) if out_years else [], 'notes': notes, 'horizon': horizon,
            'sweep': sweep(feats, fact, th), 'thresholds': th}


DEP_DATES = (1, 2, 3, 5, 8)                    # порог: сколько дат замера Рпл выше предела делают улику
DEP_FACTORS = (0.6, 0.8, 1.0, 1.2, 1.5)         # предел депрессии, умноженный на этот коэффициент
EL_SHARE = (20.0, 30.0, 40.0, 50.0, 60.0, 70.0)   # доля суток сезона с КРУ ≥ 90 %, при которой сезон помечается
EL_DROP = (-10.0, -15.0, -20.0, -30.0, -40.0)     # падение расхода на 1 % КРУ к прошлому сезону, %
TARGET = (0.05, 0.10)                           # только справочно: в выборе и порядке наборов не участвует
STABLE = 0.8                                    # перекрытие с соседними наборами, с которого набор считается устойчивым


def _grid_row(mechanism: str, label: str, params: dict[str, float], flags: list[tuple[bool, bool]], current: bool) -> dict[str, Any]:
    """Метрики одного набора порогов: ``flags`` — (сработало, ушла в КР) по скважино-годам, где данных по механизму достаточно."""
    n = len(flags)
    rep = sum(1 for _, r in flags if r)
    oth = n - rep
    hit_rep = sum(1 for h, r in flags if h and r)
    hit_oth = sum(1 for h, r in flags if h and not r)
    flagged = hit_rep + hit_oth
    share_rep, share_oth = (hit_rep / rep if rep else None), (hit_oth / oth if oth else None)
    return {'mechanism': mechanism, 'label': label, 'params': params, 'current': current, 'n': n, 'flagged': flagged, 'share_all': flagged / n if n else None,
            'share_repaired': share_rep, 'share_other': share_oth, 'lift': share_rep / share_oth if share_rep is not None and share_oth else None,
            'precision': hit_rep / flagged if flagged else None, 'in_target': bool(n and TARGET[0] <= flagged / n <= TARGET[1])}


def sweep(feats: dict[int, dict[str, dict[str, Any]]], fact: dict[int, set[str]], current: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """Перебор порогов депрессии и ЭЛПРО на истории: насколько устойчив набор отмеченных и как механизм отличает ушедших в КР.

    Только таблица для инженера: пороги никуда не применяются сами, применяет их инженер кнопкой."""
    dep_units = [(f['dep'], w in fact[y]) for y, wells in feats.items() for w, f in wells.items() if f.get('dep') and f['dep'].get('limit')]
    el_units = [(f['elpro'], w in fact[y]) for y, wells in feats.items() for w, f in wells.items()
                if f.get('elpro') and f['elpro'].get('high_share') is not None]
    dep_rows, dep_pos = [], {}
    for k in DEP_DATES:
        for factor in DEP_FACTORS:
            flags = [(sum(d > factor * u['limit'] for d in u['deps']) >= k, rep) for u, rep in dep_units]
            dep_pos[len(dep_rows)] = (DEP_DATES.index(k), DEP_FACTORS.index(factor), _mask(flags))
            dep_rows.append(_grid_row('depression', f'от {k} дат выше предела × {factor:g}', {'dep_min_dates': float(k), 'dep_factor': factor}, flags,
                                      k == current['dep_min_dates'] and factor == 1.0))
    el_rows, el_pos = [], {}
    for share in EL_SHARE:
        for drop in EL_DROP:
            flags = [(u['high_share'] >= share or (u.get('eff_change') is not None and u['eff_change'] <= drop), rep) for u, rep in el_units]
            el_pos[len(el_rows)] = (EL_SHARE.index(share), EL_DROP.index(drop), _mask(flags))
            el_rows.append(_grid_row('throttle', f'КРУ ≥ 90 % в {share:g} % суток или расход на 1 % КРУ {drop:g} %', {'elpro_high_share': share, 'elpro_drop': drop},
                                     flags, share == current['elpro_high_share'] and drop == current['elpro_drop']))
    _stability(dep_rows, dep_pos)
    _stability(el_rows, el_pos)
    return {'depression': _pick(dep_rows), 'throttle': _pick(el_rows)}


def _mask(flags: list[tuple[bool, bool]]) -> int:
    return int(''.join('1' if h else '0' for h, _ in flags) or '0', 2)


def _stability(rows: list[dict[str, Any]], pos: dict[int, tuple[int, int, int]]) -> None:
    """Устойчивость набора: перекрытие отмеченных скважино-лет с соседними по сетке порогами (шаг одного порога). 1 — набор не меняется."""
    at = {(a, b): (i, m) for i, (a, b, m) in pos.items()}
    for i, (a, b, m) in pos.items():
        near = [at[k][1] for k in ((a - 1, b), (a + 1, b), (a, b - 1), (a, b + 1)) if k in at]
        vals = [1.0 if not (m | n) else (m & n).bit_count() / (m | n).bit_count() for n in near]
        rows[i]['stability'] = sum(vals) / len(vals) if vals else None
        rows[i]['stable'] = rows[i]['stability'] is not None and rows[i]['stability'] >= STABLE


def _pick(rows: list[dict[str, Any]], top: int = 6) -> list[dict[str, Any]]:
    """Что показать: устойчивые к сдвигу порога наборы по убыванию «во сколько раз чаще у ушедших в КР» и обязательно текущий набор.
    Доля срабатывания (5–10 %) в выборе не участвует. Историю КР учитываем как слабую проверку: план ремонтов ограничен ресурсами."""
    good = sorted((r for r in rows if r['n'] and r['flagged']), key=lambda r: (not r.get('stable'), -(r['lift'] or 0), r['label']))[:top]
    return good + [r for r in rows if r['current'] and r not in good]


def _points(level: str, weights: dict[str, float] | None) -> float:
    return (weights or {}).get('weak', 1.0) if level == 'weak' else POINTS.get(level, 0.0)


def candidates(cards: dict[str, dict[str, Any]], weights: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Сводка по фонду: скважины по убыванию суммы улик на сегодня. Берутся строки оценки самих карточек: в них уже учтены приоритет КР по ревизиям,
    решения инженера по механизмам и правки таблицы «механизм → операция»."""
    out = []
    for well, card in cards.items():
        shown = card.get('assess') or []
        main = [r for r in shown if r['level'] in POINTS]
        kr, perf = last_kr(card), perf_last(card)
        out.append({'well': well, 'group': card.get('group', ''), 'last_kr': kr, 'perf': perf, 'score': sum(_points(r['level'], weights) * r['weight'] * (weights or {}).get(r.get('mechanism'), 1.0) for r in main), 'manual': any(r['manual'] for r in shown),
                    'mechanisms': '; '.join(f"{r['name']} ({passport_assess.LEVEL_NAMES[r['level']]})" for r in main),
                    'recommendation': '; '.join(dict.fromkeys(r['recommendation'] for r in main if r['recommendation']))})
    return sorted(out, key=lambda r: (-r['score'], r['well']))
