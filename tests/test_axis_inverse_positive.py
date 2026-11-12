"""Ось «в обратном направлении» снимается и ставится; «положительные числа» — настройка оси в общем ядре графиков."""
from __future__ import annotations

from atlas import chart_style as cs
from atlas.contract import Axis


def test_inverse_false_survives_cleaning():
    """Снятая галка при включённой по умолчанию обратной оси (уровень жидкости) сохраняется как явное «нет»."""
    assert cs.clean_axis({'inverse': False}, 'y')['inverse'] is False
    assert cs.clean_axis({'inverse': True}, 'y')['inverse'] is True
    assert 'inverse' not in cs.clean_axis({}, 'y')


def test_style_axis_can_turn_inverse_off():
    axis = Axis('Уровень', 'м', inverse=True)
    cs.style_axis(axis, {'inverse': False}, 'Y', [], [])
    assert axis.inverse is False
    other = Axis('Давление', 'кгс/см²')
    cs.style_axis(other, {'inverse': True}, 'Y', [], [])
    assert other.inverse is True


def test_positive_numbers_setting_is_axis_style():
    spec = cs.clean_axis({'positive': True}, 'y')
    axis = Axis('Уровень', 'м')
    cs.style_axis(axis, spec, 'Y', [], [])
    assert axis.style['positive'] is True


def test_export_formatter_positive():
    from atlas.engine.core.export_style import ru_format
    f = ru_format(1, positive=True)
    assert f(-12.5, 0) == '12,5'
