"""Комбинированные виды графика конструктора в статическом рендере: столбцы рядом и стопкой, область, ступенчатая линия.

Рисует только то, что помечено ``meta['combo']`` (``atlas/render.py``), остальные модули выгружаются как раньше.
Столбцы: ширина — 0,8 шага данных ряда (сутки, месяц или шаг числового X), столбцы разных стопок делят её поровну.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def is_combo(trace) -> bool:
    return isinstance(trace.meta, dict) and bool(trace.meta.get('combo'))


def positions(x, date_axis: bool) -> np.ndarray:
    """X как число matplotlib: даты — сутки, остальное — как есть."""
    if date_axis:
        from matplotlib.dates import date2num
        return np.asarray(date2num(pd.to_datetime(list(x)).to_pydatetime()), dtype=float)
    return np.asarray(list(x), dtype=float)


def step_of(pos: np.ndarray) -> float:
    """Шаг данных: наименьшая положительная разность соседних X; одна точка — 1."""
    u = np.unique(pos[np.isfinite(pos)])
    d = np.diff(u)
    d = d[d > 0]
    return float(d.min()) if len(d) else 1.0


class Bars:
    """Столбцы одного рисунка: «единица» — стопка (общее имя) или одиночный ряд на своей оси."""

    def __init__(self, traces):
        self.units: list = []
        for t in traces:
            key = self.key(t)
            if key not in self.units:
                self.units.append(key)
        self.base: dict = {}      # накопленная высота стопки по положению X

    @staticmethod
    def key(t):
        stack = t.meta.get('stack') if isinstance(t.meta, dict) else ''
        return (t.yaxis or 'y', stack or id(t))

    def draw(self, target, t, x, y, label, color, date_axis: bool) -> None:
        pos = positions(x, date_axis)
        step = step_of(pos)
        unit = self.units.index(self.key(t))
        w = .8 * step / len(self.units)
        left = pos - .4 * step + unit * w
        height = np.nan_to_num(np.asarray(y, dtype=float))
        acc = self.base.setdefault(unit, {})
        bottom = np.array([acc.get(p, 0.0) for p in pos])
        for p, h in zip(pos, height):
            acc[p] = acc.get(p, 0.0) + h
        alpha = t.opacity if isinstance(t.opacity, (int, float)) else None
        target.bar(left, height, width=w, bottom=bottom, align='edge', label=label, color=color, alpha=alpha, zorder=1.5)


class Areas:
    """Стопки областей: верх каждой области — сумма предыдущих (по номеру точки; X у рядов стопки общий)."""

    def __init__(self):
        self.top: dict = {}

    def lower(self, t, n: int) -> np.ndarray:
        stack = t.meta.get('stack') if isinstance(t.meta, dict) else ''
        if not stack:
            return np.zeros(n)
        key = (t.yaxis or 'y', stack)
        prev = self.top.get(key)
        return prev if prev is not None and len(prev) == n else np.zeros(n)

    def remember(self, t, upper: np.ndarray) -> None:
        stack = t.meta.get('stack') if isinstance(t.meta, dict) else ''
        if stack:
            self.top[(t.yaxis or 'y', stack)] = upper


def is_back(trace) -> bool:
    """Нижний слой: столбцы и области (под линиями и точками)."""
    return is_combo(trace) and (trace.type == 'bar' or bool((trace.meta or {}).get('fill')))


def overlay(main):
    """Прозрачные оси поверх ``base`` без своей шкалы: на них рисуются линии и точки, чтобы они лежали над столбцами
    и областями даже с другой оси (правые оси matplotlib иначе всегда выше левой). Пределы Y берёт ``sync`` перед сохранением,
    а для автомасштаба те же данные невидимой линией кладутся на ``base`` (``ghost``)."""
    top = main.twinx()       # именно от основной оси: twinx переводит шкалу исходной оси влево, у правой шкалы это сломало бы подписи
    top.yaxis.set_visible(False)
    top.spines['right'].set_visible(False)
    top.set_zorder(10)
    return top


def ghost(base, x, y) -> None:
    base.plot(x, y, linestyle='None', marker='None', label='_nolegend_')


def sync(base, top) -> None:
    top.set_yscale(base.get_yscale())
    top.set_ylim(base.get_ylim())
