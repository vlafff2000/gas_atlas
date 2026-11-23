"""Автоматический перебор критериев вывода скважины в КРС на истории КР.

Один запуск прогоняет сетку вариантов: пороги депрессии (число дат выше предела × коэффициент предела), пороги ЭЛПРО, множители весов
механизмов и вес слабых улик. Каждый вариант оценивается так же, как проверка на истории: скважины года ранжируются по сумме улик, берётся
столько верхних, сколько ремонтировали (K). Защита от подгонки: подбор по ранним годам, проверка по последнему году, который в подборе не участвует.
Только таблица для инженера: ничего не применяется само.

История КР — слабая проверка: план ремонтов ограничен ресурсами и не покрывает все проблемные скважины, поэтому скважина, отмеченная критериями и не взятая
в КР, не считается ошибкой. Главное — явные причины отметки, устойчивость набора отмеченных скважин (к небольшому сдвигу порогов и от года к году)
и реальное падение расхода у отмеченных, в том числе у неремонтировавшихся."""
from __future__ import annotations

import itertools
from typing import Any, Callable

from atlas import passport_assess, well_assess as wa
from atlas.well_backtest import PERF_DROP

DEP_DATES = (1, 2, 3, 5)
DEP_FACTORS = (0.8, 1.0, 1.2, 1.5)
EL_SHARE = (20.0, 30.0, 40.0, 50.0, 70.0)
EL_DROP = (-10.0, -15.0, -20.0, -30.0)
WEAK = (0.5, 1.0)                                  # во сколько баллов оценивается слабая улика (сильная = 2)
MULTS = ({}, {'bottom_fill': 0.0}, {'bottom_fill': 2.0}, {'sand': 0.0}, {'sand': 2.0}, {'gdi_old': 0.0}, {'gdi_old': 0.5}, {'gdi_old': 2.0})
TARGET = (0.05, 0.10)                              # только справочно: доля срабатывания механизма, на порядок не влияет
STABLE = 0.8                                       # перекрытие наборов отмеченных скважин при сдвиге порога на шаг, с которого набор считается устойчивым
MAX_WELLS = 400                                    # строк в таблице отмеченных скважин на вариант
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
            rows.append({'well': well, 'rep': well in fact[year], 'lv': lv, 'dep': dep, 'el': el, 'perf': f.get('perf')})
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


def _row(v: dict[str, Any], r: dict[str, Any]) -> tuple[float, int | None, int | None]:
    """Балл скважино-года по варианту и уровни депрессии и ЭЛПРО (None — механизм выключен)."""
    s = sum(v['mults'].get(m, 1.0) * (2.0 if lv == 2 else v['weak'] if lv == 1 else 0.0) for m, lv in r['lv'].items())
    dl = el = None
    if v['dep_on']:
        dl = _dep_level(r['dep'], v['dep_min_dates'], v['dep_factor'])
        s += (2.0 if dl == 2 else v['weak'] if dl == 1 else 0.0) * v['mults'].get('depression', 1.0)
    if v['el_on']:
        el = _el_level(r['el'], v['elpro_high_share'], v['elpro_drop'])
        s += 2.0 * el / 2 * v['mults'].get('throttle', 1.0)
    return s, dl, el


def evaluate(v: dict[str, Any], prep: dict[int, list[dict[str, Any]]], years: list[int]) -> dict[str, Any]:
    per, dep_hit, el_hit, flags = {}, [0, 0], [0, 0], []
    for y in years:
        scores, reps = [], []
        for r in prep[y]:
            s, dl, el = _row(v, r)
            if dl is not None:
                dep_hit[0] += dl == 2
                dep_hit[1] += 1
            if el is not None:
                el_hit[0] += el == 2
                el_hit[1] += 1
            scores.append(s)
            reps.append(r['rep'])
            flags.append(s > 0)
        per[y] = (*_year_metrics(scores, reps), sum(x > 0 for x in scores) / len(scores) if scores else None)
    return {'per_year': per, 'dep_share': dep_hit[0] / dep_hit[1] if dep_hit[1] else None, 'el_share': el_hit[0] / el_hit[1] if el_hit[1] else None, 'flags': flags}


def reasons(v: dict[str, Any], r: dict[str, Any]) -> list[str]:
    """Видимая причина отметки: что именно сработало у скважины по этому варианту критериев."""
    out = [f'{NAMES[m]} ({"сильная" if lv == 2 else "слабая"} улика)' for m, lv in r['lv'].items() if lv and v['mults'].get(m, 1.0) > 0]
    if v['dep_on'] and v['mults'].get('depression', 1.0) > 0:
        lvl = _dep_level(r['dep'], v['dep_min_dates'], v['dep_factor'])
        if lvl:
            lim = r['dep']['limit'] * v['dep_factor']
            over = sum(d > lim for d in r['dep']['deps'])
            out.append(f'депрессия выше предела {lim:.1f} кгс/см² на {over} из {len(r["dep"]["deps"])} дат замера' if over else f'депрессия у предела {lim:.1f} кгс/см² (≥ 90 %)')
    if v['el_on'] and v['mults'].get('throttle', 1.0) > 0 and _el_level(r['el'], v['elpro_high_share'], v['elpro_drop']):
        e = r['el']
        if e['high_share'] >= v['elpro_high_share']:
            out.append(f'КРУ ≥ 90 % в {e["high_share"]:.0f} % суток сезона')
        if e.get('eff_change') is not None and e['eff_change'] <= v['elpro_drop']:
            out.append(f'расход на 1 % КРУ {e["eff_change"]:.0f} % к прошлому сезону')
    return out


def _grid_key(v: dict[str, Any]) -> tuple:
    return (v['dep_on'], v['dep_min_dates'], v['dep_factor'], v['el_on'], v['elpro_high_share'], v['elpro_drop'], v['weak'], tuple(sorted(v['mults'].items())))


def _neighbors(v: dict[str, Any]) -> list[tuple]:
    """Варианты, отличающиеся от данного одним шагом одного порога сетки (остальное то же)."""
    out = []
    for field, grid, on in (('dep_min_dates', DEP_DATES, v['dep_on']), ('dep_factor', DEP_FACTORS, v['dep_on']),
                            ('elpro_high_share', EL_SHARE, v['el_on']), ('elpro_drop', EL_DROP, v['el_on'])):
        if not on or v[field] not in grid:
            continue
        i = grid.index(v[field])
        for j in (i - 1, i + 1):
            if 0 <= j < len(grid):
                out.append(_grid_key({**v, field: grid[j]}))
    return out


def _jaccard(a: int, b: int) -> float:
    u = (a | b).bit_count()
    return 1.0 if not u else (a & b).bit_count() / u


def _stability(masks: dict[tuple, int], v: dict[str, Any]) -> float | None:
    """Насколько набор отмеченных скважин (скважино-лет) сохраняется при сдвиге порога на один шаг: 1 — не меняется, 0 — совсем другой."""
    mine, near = masks.get(_grid_key(v)), [masks[k] for k in _neighbors(v) if k in masks]
    return sum(_jaccard(mine, m) for m in near) / len(near) if near and mine is not None else None


def review(v: dict[str, Any], prep: dict[int, list[dict[str, Any]]], years: list[int]) -> dict[str, Any]:
    """Разбор варианта по скважинам: причины отметки, ремонтировали или нет, реальное изменение расхода, устойчивость от года к году.

    Реальное падение — средний расход первого сезона отбора после 1 января года против последнего до него (индикатор, не замер продуктивности)."""
    entries, flagged_by_year = [], {}
    for y in years:
        flagged_by_year[y] = set()
        for r in prep[y]:
            s, _, _ = _row(v, r)
            if s > 0:
                flagged_by_year[y].add(r['well'])
                ch = (r.get('perf') or {}).get('change')
                entries.append({'year': y, 'well': r['well'], 'repaired': r['rep'], 'reasons': '; '.join(reasons(v, r)), 'perf': None if ch is None else round(ch, 1)})
    persist = []
    for a, b in zip(years, years[1:]):
        both = {r['well'] for r in prep[a]} & {r['well'] for r in prep[b]}
        now = flagged_by_year[b] & both
        if now:
            persist.append(len(now & flagged_by_year[a]) / len(now))
    every = {(y, r['well']): r for y in years for r in prep[y]}

    def perf_part(items: list[float | None]) -> dict[str, Any]:
        got = [x for x in items if x is not None]
        return {'n': len(got), 'mean': sum(got) / len(got) if got else None, 'drop_share': sum(x <= PERF_DROP for x in got) / len(got) if got else None}

    fl = {(e['year'], e['well']) for e in entries}
    rep_total = sum(r['rep'] for r in every.values())
    fl_rep = [e for e in entries if e['repaired']]
    fl_not = [e for e in entries if not e['repaired']]
    other = [(r.get('perf') or {}).get('change') for k, r in every.items() if k not in fl and not r['rep']]
    shown = sorted(entries, key=lambda e: (-e['year'], e['repaired'], e['well']))[:MAX_WELLS]
    return {'flagged': len(entries), 'flagged_repaired': len(fl_rep), 'flagged_not_repaired': len(fl_not), 'repaired': rep_total, 'missed_repaired': rep_total - len(fl_rep),
            'persistence': sum(persist) / len(persist) if persist else None,
            'perf_flagged_not_repaired': perf_part([e['perf'] for e in fl_not]), 'perf_flagged_repaired': perf_part([e['perf'] for e in fl_rep]),
            'perf_not_flagged': perf_part(other), 'entries': shown, 'entries_total': len(entries)}


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
    rows, canceled, masks = [], False, {}
    for i, v in enumerate(todo + [base]):
        if cancelled and cancelled():
            canceled = True
            break
        ev = evaluate(v, prep, years)
        mask = int(''.join('1' if f else '0' for f in ev['flags']) or '0', 2)
        masks.setdefault(_grid_key(v), mask)
        fit_lift = _mean([ev['per_year'][y][1] for y in fit])
        test_lift = _mean([ev['per_year'][y][1] for y in test])
        shares = [s for s in (ev['dep_share'] if v['dep_on'] else None, ev['el_share'] if v['el_on'] else None) if s is not None]
        rows.append({'variant': v, 'text': describe(v), 'current': v is base, '_key': _grid_key(v),
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
    for r in rows:
        r['stability'] = _stability(masks, r['variant'])
        r['stable'] = r['stability'] is not None and r['stability'] >= STABLE
    # порядок: сначала устойчивые к сдвигу порога, затем по «лучше случайного» на истории (слабая проверка), затем по числу лет лучше случайного;
    # доля срабатывания (5–10 %) в порядке не участвует, она показана справочно
    best = sorted((r for r in rows if r['fit_lift'] is not None and not r['current']), key=lambda r: (not r['stable'], -(r['fit_lift'] or 0), -(r['years_better'])))[:top]
    cur = [r for r in rows if r['current']]
    for r in best[:1] + cur:
        r['review'] = review(r['variant'], prep, years)
    for r in rows:
        r.pop('_key', None)
    return {'rows': best + cur, 'fit_years': fit, 'test_years': test, 'tried': len(rows), 'canceled': canceled,
            'notes': ['Подбор по годам ' + ', '.join(map(str, fit)) + ('; проверка по году ' + ', '.join(map(str, test)) + ', в подборе он не участвует.' if test else '; лет мало, проверки на отложенном годе нет.'),
                      'История КР — слабая проверка: план ремонтов ограничен ресурсами и не покрывает все проблемные скважины, поэтому отмеченная и не отремонтированная скважина не считается ошибкой. '
                      'Первыми идут устойчивые варианты: набор отмеченных скважин почти не меняется при сдвиге порога на шаг (перекрытие не ниже ' + f'{STABLE * 100:.0f} %' + '). Если «лучше случайного» в подборе сильно выше, чем в проверке, вариант подогнан под прошлые годы.',
                      'Для лучшего варианта и текущих критериев показаны причины отметки по скважинам, деление на ремонтировавшиеся и нет, и изменение среднего расхода сезона (падение — от ' + f'{-PERF_DROP:.0f} %' + ').',
                      'Применяются кнопкой пороги депрессии и ЭЛПРО и веса механизмов; решение за инженером.']}
