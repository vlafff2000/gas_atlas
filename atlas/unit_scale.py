"""Единицы отображения оси: подпись меняется вместе с числами (тыс. м³ → млн м³ → млрд м³), без приписки «×10ⁿ».

Зеркало на TS — ``web/src/unitScale.ts`` (общая таблица случаев ``tests/atlas/unit_scale_cases.json``).
Лесенки: счётные единицы (``м³``, ``т``, ``руб.``: «» → тыс. → млн → млрд → трлн) и системные (``Па`` → кПа → МПа → ГПа).
Единица вне лесенок (кгс/см², %, °C, скв.) не масштабируется: числа остаются как есть, подпись не трогается.
"""
from __future__ import annotations

import math
import re

STEPS = {'thousands': 1, 'millions': 2, 'billions': 3}      # «Тысячи/Миллионы/Миллиарды» в настройке оси = на сколько ступеней по 10³
AUTO = 'auto'

_COUNT = ('', 'тыс. ', 'млн ', 'млрд ', 'трлн ')
_SI = ('', 'к', 'М', 'Г')
_TAIL = r'(?P<s>/[^\s,;)\]]+)?(?=[\s,;)\]]*$)'
_COUNT_RE = re.compile(r'(?<![\w.])(?P<p>тыс\. |млн |млрд |трлн )?(?P<b>ст\. м³|м³|м3|т|кг|руб\.)' + _TAIL)
_SI_RE = re.compile(r'(?<![\w.])(?P<p>[кМГ])?(?P<b>Па|Вт|Дж)' + _TAIL)


def _match(text: str):
    for pattern, ladder in ((_COUNT_RE, _COUNT), (_SI_RE, _SI)):
        m = pattern.search(text or '')
        if m:
            return m, ladder
    return None


def shift(text: str, steps: int) -> str | None:
    """Подпись со сдвигом единицы на ``steps`` ступеней вверх (числа делятся на 1000**steps); None — единица не масштабируется."""
    found = _match(text)
    if not found:
        return None
    m, ladder = found
    index = ladder.index(m.group('p') or '') + steps
    if not 0 <= index < len(ladder):
        return None
    return text[:m.start()] + ladder[index] + m.group('b') + (m.group('s') or '') + text[m.end():]


def auto_steps(text: str, lo: float, hi: float) -> int:
    """Сколько ступеней взять, чтобы наибольшее по модулю число оси попало в 1…999; 0 — оставить как есть."""
    found = _match(text)
    peak = max(abs(lo), abs(hi))
    if not found or not math.isfinite(peak) or peak == 0:
        return 0
    m, ladder = found
    here = ladder.index(m.group('p') or '')
    want = math.floor(math.log10(peak) / 3 + 1e-9)
    return max(-here, min(len(ladder) - 1 - here, want))


def resolve(text: str, units: str | None, lo: float, hi: float, manual: bool = False) -> tuple[float, str]:
    """(делитель чисел, подпись) для настройки оси ``units``; (1, подпись как есть), если масштабировать нельзя.

    ``manual`` — название оси задано вручную: оно главнее любых автоматических надписей и остаётся как написано; числа делятся
    только при явном выборе ступеней (автоматический режим единицу не видит и числа не трогает)."""
    if manual:
        return 1000.0 ** STEPS.get(units or '', 0), text
    steps = auto_steps(text, lo, hi) if units == AUTO else STEPS.get(units or '', 0)
    shifted = shift(text, steps) if steps else None
    return (1000.0 ** steps, shifted) if shifted is not None else (1.0, text)
