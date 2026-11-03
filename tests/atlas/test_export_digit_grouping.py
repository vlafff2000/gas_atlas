"""Выгрузка графиков: числа делятся по разрядам (80 000), настройка «Разделять числа по разрядам» включена по умолчанию."""
from __future__ import annotations

import matplotlib
import matplotlib.pyplot as plt
import pytest

from atlas.chart_style import clean_chart
from atlas.contract import Axis, Chart, Series
from atlas.render import chart_file

NBSP = ' '


@pytest.fixture
def tick_texts(monkeypatch):
    """Подписи делений Y и X, как они попали в файл: перехватываем фигуру перед закрытием."""
    matplotlib.use('Agg')
    seen: list[list[str]] = []
    real = plt.close

    def spy(fig=None):
        if fig is not None and hasattr(fig, 'axes'):
            fig.canvas.draw()
            seen.append([t.get_text() for ax in fig.axes for t in ax.get_yticklabels()])
        real(fig) if fig is not None else real()

    monkeypatch.setattr(plt, 'close', spy)
    return seen


def _line(style=None):
    c = Chart('t-1', 'Тест', Axis('Дата', scale='time'), Axis('Расход'))
    c.series.append(Series('a', ['2024-01-01', '2024-02-01', '2024-03-01'], [20000.0, 50000.0, 80000.0], 'line'))
    if style:
        c.style = style
    return c


def test_default_y_ticks_are_grouped_in_png(tick_texts):
    chart_file(_line(), 'png', 150)
    labels = [t for t in tick_texts[-1] if t]
    assert f'80{NBSP}000' in labels and '80000' not in labels


def test_group_digits_off_keeps_plain_numbers(tick_texts):
    chart_file(_line({'group_digits': False}), 'png', 150)
    labels = [t for t in tick_texts[-1] if t]
    assert '80000' in labels and f'80{NBSP}000' not in labels


def test_group_digits_setting_is_parsed():
    assert clean_chart({'group_digits': False}).get('group_digits') is False
    assert 'group_digits' not in clean_chart({})
