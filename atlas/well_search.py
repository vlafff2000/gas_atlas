"""Автоматический перебор критериев вывода скважины в КРС на истории КР.

Один запуск прогоняет сетку вариантов: пороги депрессии (число дат выше предела × коэффициент предела), пороги ЭЛПРО, множители весов
механизмов и вес слабых улик. Каждый вариант оценивается так же, как проверка на истории: скважины года ранжируются по сумме улик, берётся
столько верхних, сколько ремонтировали (K). Защита от подгонки: подбор по ранним годам, проверка по последнему году, который в подборе не участвует.
Только таблица для инженера: ничего не применяется само."""
from __future__ import annotations

import itertools
from typing import Any, Callable

from atlas import passport_assess, well_assess as wa

DEP_DATES = (1, 2, 3, 5)
DEP_FACTORS = (0.8, 1.0, 1.2, 1.5)
EL_SHARE = (20.0, 30.0, 40.0, 50.0, 70.0)
EL_DROP = (-10.0, -15.0, -20.0, -30.0)
WEAK = (0.5, 1.0)                                  # во сколько баллов оценивается слабая улика (сильная = 2)
MULTS = ({}, {'bottom_fill': 0.0}, {'bottom_fill': 2.0}, {'sand': 0.0}, {'sand': 2.0}, {'gdi_old': 0.0}, {'gdi_old': 0.5}, {'gdi_old': 2.0})
TARGET = (0.05, 0.10)
FIXED = ('bottom_fill', 'sand', 'gdi_old')          # механизмы, чьи улики берутся из проверки на истории как есть
NAMES = passport_assess.MECHANISMS


def prepare(feats: dict[int, dict[str, dict[str, Any]]], evidence: dict[int, dict[str, list[wa.Evidence]]], fact: dict[int, set[str]]) -> dict[int, list[dict[str, Any]]]:
    """По скважино-годам: уровни неизменяемых механизмов и сырые показатели депрессии и ЭЛПРО."""
    out: dict[int, list[dict[str, Any]]] = {}
    for year, wells in evidence.items():
        rows = []
        for well, items in wells.items():
            lv = {m: max((2 if e.level == 'strong' else 1 if e.level == 'weak' else 0 for e in items if e.mechanism == m), default=0) for m in FIXED}
            f = feats.get(year, {}).get(well, {})
            dep = f.get('dep') if f.get('dep') and f['dep'].get('limit') else None
            el = f.get('elpro') if f.get('elpro') and f['elpro'].get('high_share') is not None else None
            rows.append({'rep': well in fact[year], 'lv': lv, 'dep': dep, 'el': el})
        out[year] = rows
    return out


def _dep_level(dep: dict[str, Any] | None, k: int, factor: float) -> int:
    if not dep:
        return 0
    lim = dep['limit'] * factor
    over = sum(d > lim for d in dep['deps'])
    return 2 if over >= k else 1 if over >= 1 or max(dep['deps'], default=0) >= 0.9 * lim else 0


def _el_level(el: dict[str, Any] | None, share: float, drop: float) -> int:
    return 2 if el and (el['high_share'] >= share or (el.get('eff_change') is not None and el['eff_change'] <= drop)) else 0


def _year_metrics(scores: list[float], reps: list[bool]) -> tuple[float | None, float | None]:
    """Точность в верхних K (при равных баллах — ожидание по случайному порядку) и во сколько раз лучше случайного."""
    n, k = len(scores), sum(reps)
    if not n or not k:
        return None, None
    order = sorted(range(n), key=lambda i: -scores[i])
    cut = scores[order[k - 1]]
    above = [i for i in range(n) if scores[i] > cut]
    tier = [i for i in range(n) if scores[i] == cut]
    need = k - len(above)
    hits = sum(reps[i] for i in above) + need * (sum(reps[i] for i in tier) / len(tier))
    precision = hits / k
    return precision, precision / (k / n)


def describe(v: dict[str, Any]) -> str:
    parts = [f'депрессия: от {v["dep_min_dates"]:g} дат выше предела × {v["dep_factor"]:g}' if v['dep_on'] else 'депрессия не учитывается',
             f'ЭЛПРО: КРУ ≥ 90 % в {v["elpro_high_share"]:g} % суток или расход на 1 % КРУ {v["elpro_drop"]:g} %' if v['el_on'] else 'ЭЛПРО не учитывается',
             f'слабая улика {v["weak"]:g} балла']
    parts += [f'{NAMES[m].lower()} ×{x:g}' for m, x in v['mults'].items()]
    return '; '.join(parts)


def variants() -> list[dict[str, Any]]:
    dep = [{'dep_on': False, 'dep_min_dates': 0, 'dep_factor': 1.0}] + [{'dep_on': True, 'dep_min_dates': k, 'dep_factor': f} for k, f in itertools.product(DEP_DATES, DEP_FACTORS)]
    el = [{'el_on': False, 'elpro_high_share': 0.0, 'elpro_drop': 0.0}] + [{'el_on': True, 'elpro_high_share': s, 'elpro_drop': d} for s, d in itertools.product(EL_SHARE, EL_DROP)]
    return [{**d, **e, 'weak': w, 'mults': m} for d, e, w, m in itertools.product(dep, el, WEAK, MULTS)]


def evaluate(v: dict[str, Any], prep: dict[int, list[dict[str, Any]]], years: list[int]) -> dict[str, Any]:
    per, dep_hit = {}, [0, 0]
    el_hit = [0, 0]
    for y in years:
        scores, reps = [], []
        for r in prep[y]:
            s = sum(v['mults'].get(m, 1.0) * (2.0 if lv == 2 else v['weak'] if lv == 1 else 0.0) for m, lv in r['lv'].items())
            if v['dep_on']:
                lvl = _dep_level(r['dep'], v['dep_min_dates'], v['dep_factor'])
                s += (2.0 if lvl == 2 else v['weak'] if lvl == 1 else 0.0) * v['mults'].get('depression', 1.0)
                dep_hit[0] += lvl == 2
                dep_hit[1] += 1
            if v['el_on']:
                lvl = _el_level(r['el'], v['elpro_high_share'], v['elpro_drop'])
                s += 2.0 * lvl / 2 * v['mults'].get('throttle', 1.0)
                el_hit[0] += lvl == 2
                el_hit[1] += 1
            scores.append(s)
            reps.append(r['rep'])
        per[y] = (*_year_metrics(scores, reps), sum(x > 0 for x in scores) / len(scores) if scores else None)
    return {'per_year': per, 'dep_share': dep_hit[0] / dep_hit[1] if dep_hit[1] else None, 'el_share': el_hit[0] / el_hit[1] if el_hit[1] else None}


def _mean(xs: list[float | None]) -> float | None:
    got = [x for x in xs if x is not None]
    return sum(got) / len(got) if got else None


def search(prep: dict[int, list[dict[str, Any]]], current: dict[str, float], progress: Callable[[int, int], None] | None = None,
           cancelled: Callable[[], bool] | None = None, top: int = 15) -> dict[str, Any]:
    """Прогон всех вариантов. Подбор по всем годам, кроме последнего; последний — проверка (если лет хотя бы два)."""
    years = sorted(y for y in prep if prep[y])
    fit, test = (years[:-1], years[-1:]) if len(years) >= 2 else (years, [])
    todo = variants()
    base = {'dep_on': True, 'dep_min_dates': current['dep_min_dates'], 'dep_factor': 1.0, 'el_on': True, 'elpro_high_share': current['elpro_high_share'],
            'elpro_drop': current['elpro_drop'], 'weak': 1.0, 'mults': {}}
    rows, canceled = [], False
    for i, v in enumerate(todo + [base]):
        if cancelled and cancelled():
            canceled = True
            break
        ev = evaluate(v, prep, years)
        fit_lift = _mean([ev['per_year'][y][1] for y in fit])
        test_lift = _mean([ev['per_year'][y][1] for y in test])
        shares = [s for s in (ev['dep_share'] if v['dep_on'] else None, ev['el_share'] if v['el_on'] else None) if s is not None]
        rows.append({'variant': v, 'text': describe(v), 'current': v is base,
                     'fit_lift': fit_lift, 'test_lift': test_lift, 'fit_precision': _mean([ev['per_year'][y][0] for y in fit]),
                     'test_precision': _mean([ev['per_year'][y][0] for y in test]), 'dep_share': ev['dep_share'], 'el_share': ev['el_share'],
                     'flagged': _mean([ev['per_year'][y][2] for y in years]),
                     'years_better': sum(1 for y in years if (ev['per_year'][y][1] or 0) > 1.0), 'years': len(years),
                     'worst_lift': min((ev['per_year'][y][1] for y in years if ev['per_year'][y][1] is not None), default=None),
                     'in_target': all(TARGET[0] <= s <= TARGET[1] for s in shares) if shares else False,
                     'per_year': {str(y): {'precision': ev['per_year'][y][0], 'lift': ev['per_year'][y][1]} for y in years}})
        if progress and i % 25 == 0:
            progress(i + 1, len(todo) + 1)
    if progress:
        progress(len(rows), len(todo) + 1)
    best = sorted((r for r in rows if r['fit_lift'] is not None and not r['current']), key=lambda r: (not r['in_target'], -(r['fit_lift'] or 0), -(r['years_better'])))[:top]
    cur = [r for r in rows if r['current']]
    return {'rows': best + cur, 'fit_years': fit, 'test_years': test, 'tried': len(rows), 'canceled': canceled,
            'notes': ['Подбор по годам ' + ', '.join(map(str, fit)) + ('; проверка по году ' + ', '.join(map(str, test)) + ', в подборе он не участвует.' if test else '; лет мало, проверки на отложенном годе нет.'),
                      'Варианты в целевой доле (механизм срабатывает у 5–10 % скважино-лет) идут первыми. Если «лучше случайного» в подборе сильно выше, чем в проверке, вариант подогнан под прошлые годы.',
                      'Применяются кнопкой пороги депрессии и ЭЛПРО и веса механизмов; решение за инженером.']}
