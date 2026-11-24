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



def test_manual_axis_title_beats_unit_text():
    """Ручное название оси остаётся как написано, даже если в нём есть единица; числа делятся только по явному выбору ступеней."""
    assert resolve('Накоплено, тыс. м³', 'auto', 0, 5e6, manual=True) == (1.0, 'Накоплено, тыс. м³')
    assert resolve('Накоплено, тыс. м³', 'thousands', 0, 5e6, manual=True) == (1000.0, 'Накоплено, тыс. м³')


def test_any_chart_manual_label_marks_axis():
    from atlas.contract import Axis, Chart
    from atlas.export_any import prepared, settings_of
    chart = Chart(id='t', title='T', series=[], x=Axis(label='X'), y=Axis(label='Объём', unit='тыс. м³', style={'units': 'millions'}))
    out, _ = prepared(chart, settings_of({'labels': {'y': 'Мой объём'}}), with_doc=False)
    assert (out.y.label, out.y.unit, out.y.style) == ('Мой объём', '', {'units': 'millions', 'manual_title': True})
