"""Линии тренда ряда (как в Excel): линейная, полином 2–6, логарифмическая, степенная, экспоненциальная, скользящее среднее.

Одна и та же математика есть на экране (``web/src/trend.ts``): общие контрольные значения проверяются тестом
``tests/atlas/test_trend.py`` и скриптом из ``web/scripts``. R² — по самому ряду (не по преобразованным значениям)."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd

KINDS = ('linear', 'poly', 'log', 'power', 'exp', 'moving')
POINTS = 120                 # точек на гладкой линии тренда


def _num(value: float) -> str:
    return format(float(value), '.4g').replace('.', ',')


def _numbers(x: Sequence, y: Sequence) -> tuple[np.ndarray, np.ndarray, bool]:
    """Числа точек ряда: дата — миллисекунды (третье значение — ось времени); пары с пропуском отбрасываются."""
    ys = pd.to_numeric(pd.Series(list(y), dtype='object'), errors='coerce').to_numpy(float)
    xs = pd.to_numeric(pd.Series(list(x), dtype='object'), errors='coerce')
    time = False
    if xs.isna().all():
        dates = pd.to_datetime(pd.Series(list(x), dtype='object'), errors='coerce')
        xs = pd.Series(dates.astype('int64') / 1e6).where(dates.notna())
        time = True
    xv = xs.to_numpy(float)
    ok = np.isfinite(xv) & np.isfinite(ys)
    return xv[ok], ys[ok], time


def _poly_text(coef: np.ndarray) -> str:
    """Коэффициенты от старшей степени; «y = 2x² + 3x − 1»."""
    terms = []
    n = len(coef) - 1
    for i, c in enumerate(coef):
        p = n - i
        if abs(c) == 0:
            continue
        body = _num(abs(c)) + ('' if p == 0 else 'x' + ('' if p == 1 else '⁰¹²³⁴⁵⁶'[p]))
        terms.append(('−' if c < 0 else '+', body))
    if not terms:
        return 'y = 0'
    first = terms[0]
    return 'y = ' + ('−' if first[0] == '−' else '') + first[1] + ''.join(f' {s} {b}' for s, b in terms[1:])


def _raw_poly(c_u: np.ndarray, m: float, s: float) -> np.ndarray:
    """Коэффициенты по x из коэффициентов по u = (x − m) / s (от старшей степени)."""
    deg = len(c_u) - 1
    out = np.zeros(deg + 1)                  # от младшей степени
    for k in range(deg + 1):
        ck = c_u[deg - k] / s ** k
        for j in range(k + 1):
            out[j] += ck * math.comb(k, j) * (-m) ** (k - j)
    return out[::-1]


def fit(kind: str, x: Sequence, y: Sequence, order: int = 2, period: int = 5) -> dict | None:
    """Тренд по точкам ряда: ``{'x': [...], 'y': [...], 'equation': str, 'r2': float}`` или None, когда точек мало
    или вид не подходит (логарифм при x ≤ 0, степень и экспонента при y ≤ 0). Уравнение — только при числовой оси X."""
    xv, yv, time = _numbers(x, y)
    if kind not in KINDS or len(xv) < 2:
        return None
    idx = np.argsort(xv, kind='stable')
    xv, yv = xv[idx], yv[idx]
    if kind == 'moving':
        period = int(period)
        if period < 2 or len(xv) < period:
            return None
        smooth = pd.Series(yv).rolling(period).mean().to_numpy()
        keep = np.isfinite(smooth)
        return {'x': xv[keep].tolist(), 'y': smooth[keep].tolist(), 'equation': f'скользящее среднее, {period}', 'r2': None}
    if np.ptp(xv) == 0:
        return None
    if kind == 'log' and (xv <= 0).any() or kind in ('power',) and ((xv <= 0).any() or (yv <= 0).any()) or kind == 'exp' and (yv <= 0).any():
        return None
    deg = {'linear': 1, 'poly': int(order)}.get(kind, 1)
    if kind == 'poly' and (deg < 2 or deg > 6 or len(xv) <= deg):
        return None
    m, s = float(xv.mean()), float(np.ptp(xv)) / 2
    tx = {'log': np.log, 'power': np.log}.get(kind, lambda v: v)
    ty = {'power': np.log, 'exp': np.log}.get(kind, lambda v: v)
    u = (tx(xv) - (tx(xv).mean() if kind in ('log', 'power') else m)) / (np.ptp(tx(xv)) / 2 if kind in ('log', 'power') else s)
    c_u = np.polyfit(u, ty(yv), deg)
    center = float(tx(xv).mean()) if kind in ('log', 'power') else m
    scale = float(np.ptp(tx(xv)) / 2) if kind in ('log', 'power') else s

    def predict(xs: np.ndarray) -> np.ndarray:
        uu = (tx(xs) - center) / scale
        z = np.polyval(c_u, uu)
        return np.exp(z) if kind in ('power', 'exp') else z

    fitted = predict(xv)
    sst = float(((yv - yv.mean()) ** 2).sum())
    r2 = 1.0 - float(((yv - fitted) ** 2).sum()) / sst if sst > 0 else 1.0
    xs = np.linspace(xv[0], xv[-1], POINTS)
    equation = ''
    if not time:
        raw = _raw_poly(c_u, center, scale)          # по x (или по ln x), от старшей степени
        if kind in ('linear', 'poly'):
            equation = _poly_text(raw)
        elif kind == 'log':
            equation = f'y = {_num(raw[0])} ln(x) {"−" if raw[1] < 0 else "+"} {_num(abs(raw[1]))}'
        elif kind == 'power':
            equation = f'y = {_num(math.exp(raw[1]))}x^{_num(raw[0])}'
        else:
            equation = f'y = {_num(math.exp(raw[1]))}e^({_num(raw[0])}x)'
    return {'x': xs.tolist(), 'y': predict(xs).tolist(), 'equation': equation, 'r2': r2}


def label(kind_name: str, result: dict, show: bool) -> str:
    """Подпись в легенде: «Тренд: ряд» и, если нужно, уравнение с R²."""
    extra = [result['equation']] if show and result.get('equation') else []
    if show and result.get('r2') is not None:
        extra.append(f'R² = {_num(result["r2"])}')
    return f'Тренд: {kind_name}' + (f' ({"; ".join(extra)})' if extra else '')
