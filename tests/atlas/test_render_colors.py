"""Выгрузка графиков: цвета 5.8 заменяются палитрой Атласа 6 так же, как на экране (web/src/chartTheme.ts)."""
import re
from pathlib import Path

from atlas.engine.core.config import COLORS
from atlas.contract import Axis, Chart, Series
from atlas.render import LEGACY, PALETTE, to_plotly

THEME = Path(__file__).resolve().parents[2] / 'web' / 'src' / 'chartTheme.ts'


def test_palette_matches_screen():
    text = THEME.read_text(encoding='utf-8')
    screen = re.findall(r"'(#[0-9a-f]{6})'", text.split('export const PALETTE', 1)[1].split('\n', 1)[0])
    assert screen == PALETTE
    assert set(LEGACY) == {c.lower() for c in COLORS}


def test_export_uses_new_palette():
    chart = Chart('gdi-1', 'Скважина 1', Axis('Q'), Axis('ΔP²'))
    chart.series.append(Series('a', [1, 2], [3, 4], 'line', color=COLORS[0]))
    chart.series.append(Series('b', [1, 2], [3, 4], 'points', color='#64748B'))
    chart.series.append(Series('c', [1, 2], [3, 4], 'line'))
    fig = to_plotly(chart)
    assert fig.data[0].line.color == PALETTE[0]
    assert fig.data[1].marker.color == '#64748B'          # цвета со смыслом, заданные модулем, не меняются
    assert fig.data[2].line.color == PALETTE[2]
