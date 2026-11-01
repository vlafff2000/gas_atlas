"""Границы периода можно вводить неполными: «2020» — с 01.01 / по 31.12."""
import pytest

from atlas.contract import Param, ParamError, is_end_param, parse_partial_date


@pytest.mark.parametrize('text, end, expected', [
    ('2020', False, '2020-01-01'), ('2020', True, '2020-12-31'),
    ('03.2020', False, '2020-03-01'), ('02.2024', True, '2024-02-29'), ('2020-03', True, '2020-03-31'),
    ('15.03.2020', True, '2020-03-15'), ('2020-03-15', False, '2020-03-15'),
])
def test_parse(text, end, expected):
    assert parse_partial_date(text, end) == expected


def test_param_by_name():
    assert Param('date_from', 'с', 'date').coerce('2020') == '2020-01-01'
    assert Param('date_to', 'по', 'date').coerce('2020') == '2020-12-31'
    assert Param('end', 'по', 'date').coerce('2021') == '2021-12-31'
    assert is_end_param('cubes_to') and not is_end_param('start')


def test_bad():
    with pytest.raises(ParamError):
        Param('date_to', 'по', 'date').coerce('13.2020')
