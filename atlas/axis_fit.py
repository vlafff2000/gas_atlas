"""Единый автоподбор шкал значений: границы и шаг делений для экрана, предпросмотра и всех файлов.

Чистая арифметика без зависимостей; зеркало для экрана — ``web/src/axisFit.ts``. Обе реализации проверяются одной таблицей
``tests/fixtures/axis_fit_cases.json`` (вход → ожидаемые границы и шаг), поэтому расхождений между экраном и файлом быть не может.

Правила:

* шаг «круглый»: 1, 2, 2,5, 5 · 10^k; границы кратны шагу, без дробных хвостов (98,60000000000001);
* число основных делений одно на ВСЕ шкалы графика (от 4 до 8, при равном качестве — 5): сетки шкал совпадают;
* «от нуля или нет»: столбцы, области и стопки (``anchor``) — нуль обязателен; линии и точки — нуль входит в шкалу, только если
  он отнимает не больше четверти высоты поля (``ZERO_SHARE``), иначе шкала срезана (давление 44–87 → 40…90, а не 0…100);
* данные одного знака за нуль не выходят (давление не бывает отрицательным) — кроме общей нулевой линии, см. ниже;
* у срезанной шкалы со стороны нуля остаётся запас 2 % размаха: минимум кривой не лежит на оси X, срез не выглядит нулём
  (давление 40–100 → 30…100); у шкалы от нуля запаса нет (доли 0…100 % остаются 0…100);
* у шкал, в которые входит нуль и хотя бы у одной он внутри (значения разных знаков), нулевые линии совпадают — с учётом
  обратных шкал; шкала одного знака при этом получает пустую полосу за нулём. Не делается, если из-за этого данные какой-то
  шкалы займут меньше половины поля, и для шкалы в режиме «по данным»;
* заданное инженером (граница, шаг, режим) сильнее подбора: подбирается только незаданное.

Режимы шкалы (``mode``): ``auto`` — по правилам выше, ``zero`` — нуль всегда входит, ``data`` — по данным, нуль не добавляется.
Причина выбора возвращается кодом ``why`` (``WHY``) — интерфейс и отчёты показывают её инженеру словами."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

MULTS = (1.0, 2.0, 2.5, 5.0)
N_MIN, N_MAX, N_PREFERRED = 4, 8, 5
ZERO_SHARE = 0.25            # нуль добавляется линиям и точкам, если отнимает не больше этой доли высоты поля
MODES = ('auto', 'zero', 'data')
MAX_INTERVALS = 150          # предохранитель для заданного вручную слишком мелкого шага
N_PENALTY = 0.03             # цена отхода числа делений от привычных пяти (в долях заполнения поля)
ODD_PENALTY = 0.02           # цена шага 2,5 · 10^k: деления 1, 2, 5 привычнее
ROUGH_FIXED = 0.6            # «заполнение» шкалы с ручными границами, которые не делятся на круглый шаг
MARGIN = 0.02                # запас срезанной шкалы со стороны нуля, в долях размаха данных
ALIGN_MIN = 0.5              # общая нулевая линия не делается, если из-за неё данные какой-то шкалы займут меньше половины поля
EPS = 1e-9

WHY = {
    'anchor': 'столбцы и области растут от нуля — нуль обязателен',
    'near': 'нуль рядом с данными — шкала начата от нуля',
    'cut': 'данные далеко от нуля — шкала срезана, чтобы кривая занимала поле',
    'mixed': 'значения разных знаков — нуль внутри шкалы',
    'mode-zero': 'режим «авто от нуля»',
    'mode-data': 'режим «по данным»',
    'flat': 'все значения равны — шкала вокруг значения',
    'manual': 'границы заданы вручную',
    'step': 'шаг задан вручную — границы кратны шагу',
    'empty': 'на шкале нет данных',
}


@dataclass(frozen=True)
class Need:
    """Что известно о шкале: размах данных (стопки — суммы), обязателен ли нуль, режим и то, что задано вручную."""
    lo: float | None = None
    hi: float | None = None
    anchor: bool = False
    mode: str = 'auto'
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    inverse: bool = False
    margin: float = MARGIN           # запас срезанной шкалы со стороны нуля; у оси X — 0: точка на краю поля там обычна


@dataclass(frozen=True)
class Fit:
    minimum: float
    maximum: float
    step: float
    n: int | None            # число делений общей сетки; None — шкала вне общей сетки (шаг задан вручную)
    zero: bool               # нуль входит в шкалу
    why: str                 # код причины (WHY)


def _pow10(e: int) -> float:
    return float(f'1e{e}')


def _exponent(value: float) -> int:
    """floor(log10(value)) без погрешности логарифма на границах декад."""
    e = math.floor(math.log10(value))
    while _pow10(e) > value:
        e -= 1
    while _pow10(e + 1) <= value:
        e += 1
    return e


def clean(value: float) -> float:
    """Число без двоичного хвоста: 98.60000000000001 → 98.6."""
    return float(f'{value:.12g}')


def _steps(raw: float) -> list[tuple[float, bool]]:
    """Круглые шаги не меньше ``raw`` по возрастанию (две декады): (шаг, это 2,5 · 10^k)."""
    e = _exponent(raw)
    out = []
    for k in (e, e + 1, e + 2):
        for m in MULTS:
            s = m * _pow10(k)
            if s >= raw * (1 - EPS):
                out.append((s, m == 2.5))
    return out


def nice_step(raw: float) -> float:
    """Наименьший круглый шаг (1, 2, 2,5, 5 · 10^k), не меньший ``raw``."""
    return _steps(raw)[0][0]


def is_nice(step: float) -> bool:
    if not step > 0:
        return False
    m = step / _pow10(_exponent(step))
    return any(abs(m - x) < 1e-6 for x in MULTS) or abs(m - 10) < 1e-6


def _half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _target(need: Need) -> tuple[float, float, bool, bool, str]:
    """Отрезок, который шкала обязана накрыть, входит ли в него нуль, условен ли отрезок (одно значение) и причина."""
    lo, hi = float(need.lo), float(need.hi)          # type: ignore[arg-type]
    if lo > hi:
        lo, hi = hi, lo
    flat = hi == lo
    span = hi - lo
    if need.mode == 'zero':
        zero, why = True, 'mode-zero'
    elif need.mode == 'data':
        zero, why = lo <= 0 <= hi, 'mode-data'
    elif need.anchor:
        zero, why = True, 'anchor'
    elif lo < 0 < hi:
        zero, why = True, 'mixed'
    else:
        gap = lo if lo >= 0 else -hi
        zero = gap <= span * ZERO_SHARE / (1 - ZERO_SHARE)
        why = 'near' if zero else 'flat' if flat else 'cut'
    a, b = (min(lo, 0.0), max(hi, 0.0)) if zero else (lo, hi)
    if b == a:                                       # одно значение: поле вокруг него, но не через нуль
        half = abs(a) * 0.05 if a else 0.5
        a, b = (0.0, 1.0) if not a and zero else (a - half, b + half)
        return a, b, zero, True, why
    return a, b, zero, False, why


def _free(need: Need, n: int) -> tuple[float, float, float, float, bool, str] | None:
    """Лучшая шкала из ``n`` делений для шкалы без ручных границ: (низ, верх, шаг, заполнение, нуль, причина)."""
    a, b, zero, loose, why = _target(need)
    lo, hi = min(float(need.lo), float(need.hi)), max(float(need.lo), float(need.hi))      # type: ignore[arg-type]
    pad = 0.0 if loose or zero else (b - a) * need.margin
    low = max(a - pad, 0.0) if a > 0 else a          # срез со стороны нуля: запас, чтобы край данных не лежал на оси
    high = min(b + pad, 0.0) if b < 0 else b
    for step, odd in _steps((b - a) / n):
        first = math.ceil((high - n * step) / step - EPS)
        last = math.floor(low / step + EPS)
        if lo >= 0:
            first = max(first, 0)                    # неотрицательные данные: шкала не уходит ниже нуля
        elif hi <= 0:
            last = min(last, -n)
        if zero and lo >= 0:
            last = min(last, 0)
        if zero and hi <= 0 and lo < 0:
            first = max(first, -n)
        if first > last:
            continue
        m = min(max(_half_up(((a + b) / 2 - n * step / 2) / step), first), last)      # данные по середине поля
        cover = (b - a) / (n * step) - (ODD_PENALTY if odd else 0.0)
        return m * step, (m + n) * step, step, cover, zero, why
    return None


def _half(need: Need, n: int) -> tuple[float, float, float, float, bool, str]:
    """Одна граница задана вручную: вторая и шаг подбираются."""
    a, b, _zero, _loose, _why = _target(Need(need.lo, need.hi, mode='data'))
    if need.minimum is not None:
        start = float(need.minimum)
        top = max(b, start)
        width = top - start if top > start else max(abs(start) * 0.1, 1.0)
        step, odd = _steps(width / n)[0]
        low, high = start, start + n * step
    else:
        end = float(need.maximum)                    # type: ignore[arg-type]
        bottom = min(a, end)
        width = end - bottom if end > bottom else max(abs(end) * 0.1, 1.0)
        step, odd = _steps(width / n)[0]
        low, high = end - n * step, end
    cover = width / (n * step) - (ODD_PENALTY if odd else 0.0)
    return low, high, step, cover, low <= 0 <= high, 'manual'


def _fixed(need: Need, n: int) -> tuple[float, float, float, float, bool, str]:
    """Обе границы заданы вручную: шаг делит шкалу на общее число делений (сетки шкал совпадают)."""
    low, high = float(need.minimum), float(need.maximum)      # type: ignore[arg-type]
    step = (high - low) / n
    return low, high, step, 1.0 if is_nice(step) else ROUGH_FIXED, low <= 0 <= high, 'manual'


def _empty(n: int) -> tuple[float, float, float, float, bool, str]:
    step = nice_step(1.0 / n)
    return 0.0, n * step, step, 1.0, True, 'empty'


def _stepped(need: Need) -> Fit | None:
    """Шаг задан вручную: границы кратны шагу и накрывают данные; шкала вне общей сетки."""
    step = float(need.step)                          # type: ignore[arg-type]
    if need.lo is None or need.hi is None or not step > 0:
        return None
    a, b, _zero, _loose, _why = _target(need)
    low = float(need.minimum) if need.minimum is not None else math.floor(a / step + EPS) * step
    high = float(need.maximum) if need.maximum is not None else math.ceil(b / step - EPS) * step
    if need.minimum is None and min(float(need.lo), float(need.hi)) >= 0:
        low = max(low, 0.0)
    if not high > low:
        high = low + step
    if (high - low) / step > MAX_INTERVALS:
        return None
    return Fit(clean(low), clean(high), step, None, low <= 0 <= high, 'step')


def _kind(need: Need | None, count: int) -> str:
    if need is None:
        return 'skip'
    for value in (need.lo, need.hi, need.minimum, need.maximum, need.step):
        if value is not None and not math.isfinite(value):
            return 'skip'
    both = need.minimum is not None and need.maximum is not None
    if both and not need.maximum > need.minimum:     # type: ignore[operator]
        return 'skip'
    if need.step is not None:
        return 'skip' if both else 'stepped'
    if both:
        return 'fixed' if count > 1 else 'skip'      # единственная шкала с ручными границами: подбирать нечего
    if need.lo is None or need.hi is None:
        return 'empty' if need.minimum is None and need.maximum is None else 'skip'
    return 'half' if need.minimum is not None or need.maximum is not None else 'free'


def _zero_index(cands: dict, needs: Sequence[Need | None], kinds: Sequence[str], n: int) -> None:
    """Общая нулевая линия: шкалы без ручных границ, в которые входит нуль, получают его на одном делении."""
    group = [i for i in cands if kinds[i] == 'free' and cands[i][4] and needs[i].mode != 'data']      # type: ignore[union-attr]
    if len(group) < 2 or not any(cands[i][0] < 0 < cands[i][1] for i in group):
        return
    best = None
    for k in range(n + 1):                           # деление нуля, считая снизу поля
        trial = {}
        for i in group:
            need = needs[i]
            a, b, _zero, _loose, why = _target(need)         # type: ignore[arg-type]
            below = n - k if need.inverse else k     # type: ignore[union-attr]
            if (a < 0 and below == 0) or (b > 0 and below == n):
                break
            raw = max(-a / below if below else 0.0, b / (n - below) if below < n else 0.0)
            step, odd = _steps(raw)[0]
            trial[i] = (-below * step, (n - below) * step, step, (b - a) / (n * step) - (ODD_PENALTY if odd else 0.0), True, why)
        else:
            covers = [t[3] for t in trial.values()]
            score = 0.5 * min(covers) + 0.5 * sum(covers) / len(covers)
            if min(covers) >= ALIGN_MIN and (best is None or score > best[0] + EPS):
                best = (score, trial)
    if best:
        cands.update(best[1])


def fit_axes(needs: Sequence[Need | None], n_min: int = N_MIN, n_max: int = N_MAX, prefer: int = N_PREFERRED) -> list[Fit | None]:
    """Границы и шаг всех шкал значений одного графика; ``None`` — шкала не подбирается (нет данных и задана вручную, ошибка в границах)."""
    count = sum(1 for need in needs if need is not None)
    kinds = [_kind(need, count) for need in needs]
    out: list[Fit | None] = [None] * len(needs)
    for i, kind in enumerate(kinds):
        if kind == 'stepped':
            out[i] = _stepped(needs[i])              # type: ignore[arg-type]
    grid = [i for i, kind in enumerate(kinds) if kind in ('free', 'half', 'fixed', 'empty')]
    if not grid:
        return out
    prefer = min(max(prefer, n_min), n_max)
    best = None
    for n in sorted(range(n_min, n_max + 1), key=lambda v: (abs(v - prefer), v)):
        cands = {}
        for i in grid:
            need, kind = needs[i], kinds[i]
            cand = _free(need, n) if kind == 'free' else _half(need, n) if kind == 'half' else _fixed(need, n) if kind == 'fixed' else _empty(n)      # type: ignore[arg-type]
            if cand is None:
                break
            cands[i] = cand
        else:
            _zero_index(cands, needs, kinds, n)
            covers = [cands[i][3] for i in grid if kinds[i] != 'empty']
            score = (0.5 * min(covers) + 0.5 * sum(covers) / len(covers) if covers else 0.0) - N_PENALTY * abs(n - prefer)
            if best is None or score > best[0] + EPS:
                best = (score, n, cands)
    if best is None:
        return out
    _score, n, cands = best
    for i, (low, high, step, _cover, zero, why) in cands.items():
        out[i] = Fit(clean(low), clean(high), clean(step), n, zero, why)
    return out


def fit_axis(need: Need, **kwargs) -> Fit | None:
    return fit_axes([need], **kwargs)[0]
