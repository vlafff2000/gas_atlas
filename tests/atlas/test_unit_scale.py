"""Единицы отображения оси: единица в подписи меняется вместе с числами, приписки «×10ⁿ» нет. Случаи общие с web/src/unitScale.ts."""
import json
from pathlib import Path

import pytest

from atlas.unit_scale import resolve

CASES = json.loads((Path(__file__).parent / 'unit_scale_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('c', CASES, ids=lambda c: f"{c['text']}|{c['units']}|{c['hi']}")
def test_units_shift_label(c):
    divisor, text = resolve(c['text'], c['units'], c['lo'], c['hi'])
    assert (divisor, text) == (c['divisor'], c['out'])
    assert '×' not in text and '10' not in text

