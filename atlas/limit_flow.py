"""Предельный расход газа по скважине при предельной депрессии и его падение с пластовым давлением.

Уравнение притока по ГДИ: Рпл² − Рзаб² = a·q + b·q² (давления абсолютные, q — тыс. м³/сут). Депрессия dP = Рпл − Рзаб, значит
Рпл² − (Рпл − dP)² = 2·Рпл·dP − dP² = a·q + b·q². При предельной депрессии левая часть линейно падает вместе с Рпл, поэтому предельный расход
считается на КАЖДОМ Рпл заново: так учитывается падение продуктивности при снижении пластового давления. Коэффициенты a и b берутся из самого
свежего надёжного ГДИ и считаются неизменными (их зависимость от Рпл через вязкость и сверхсжимаемость мала); вне диапазона расходов ГДИ
оценка грубая — об этом говорит пометка. Предел депрессии — решение инженера: авто-источник (конструкция) только подсказка, источник виден.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

EXTRAPOLATION = 1.2     # расход больше Qmax ГДИ в столько раз — оценка вне диапазона исследования


def q_at_limit(p_res: float, a: float, b: float, dp: float) -> float | None:
    """Максимальный расход, тыс. м³/сут, при депрессии не выше ``dp`` и пластовом давлении ``p_res``; нет решения — None.

    Депрессия не может быть больше Рпл (Рзаб ≥ 0): тогда расход — свободный (Рзаб = 0)."""
    if not (p_res and p_res > 0 and dp and dp > 0) or a is None or b is None or a < 0 or b < 0:
        return None
    dp = min(dp, p_res)
    drop2 = 2 * p_res * dp - dp * dp                  # доступный перепад квадратов давлений
    if b == 0:
        return drop2 / a if a > 0 else None
    return (-a + math.sqrt(a * a + 4 * b * drop2)) / (2 * b)


def pressure_grid(start: float, step: float, count: int) -> list[float]:
    """Сетка Рпл сверху вниз: start, start − step, … (count значений, только положительные)."""
    if not step or step <= 0 or count < 1:
        return []
    return [round(start - i * step, 6) for i in range(int(count)) if start - i * step > 0]


def parse_limits(text: Any) -> dict[str, float]:
    """Ручные пределы: строки «скважина=значение» (запятая или точка), разделители — перенос строки и «;»."""
    import re
    out: dict[str, float] = {}
    for line in re.split(r'[\n;]+', str(text or '')):
        if '=' in line:
            well, val = (s.strip() for s in line.split('=', 1))
            try:
                v = float(val.replace(',', '.'))
            except ValueError:
                continue
            if well and v > 0:
                out[well.lstrip('№ ').strip()] = v
    return out


def pick_limit(well: str, manual: dict[str, float], by_type: float | None, type_name: str = '') -> tuple[float | None, str]:
    """Предел депрессии и источник: ручной главнее, иначе по типу забоя (конструкции), иначе предела нет."""
    if well in manual:
        return manual[well], 'задан вручную'
    if by_type:
        return by_type, f'по конструкции: {type_name}' if type_name else 'по конструкции'
    return None, 'предел не задан'


def flow_row(a: float, b: float, dp: float, grid: Iterable[float], p_gdi: float | None, q_max_gdi: float | None) -> dict[str, Any]:
    """Расход на дату ГДИ (при Рпл ГДИ) и на сетке Рпл; пометка, где оценка вне диапазона расходов ГДИ."""
    out: dict[str, Any] = {'q_gdi': q_at_limit(p_gdi, a, b, dp) if p_gdi else None, 'rough': []}
    for p in grid:
        q = q_at_limit(p, a, b, dp)
        out[p] = q
        if q is not None and q_max_gdi and q > EXTRAPOLATION * q_max_gdi:
            out['rough'].append(p)
    return out
