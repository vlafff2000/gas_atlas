"""Прореживание графика расхода не должно обрывать линию на значении перед остановкой скважины."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip('plotly')

from atlas.thinning import screen_decimate


def test_line_drops_to_zero_right_after_last_working_day():
    rng = np.random.default_rng(1)
    for _ in range(50):
        q = np.zeros(6000)
        start = int(rng.integers(0, 3000))
        end = start + int(rng.integers(5, 2500))
        q[start:end] = rng.random(end - start) * 50 + 1
        frame = pd.DataFrame({'q': q, 'date': pd.date_range('2020-01-01', periods=6000)})
        out = screen_decimate(frame, 'q', 1500)
        pos = np.flatnonzero(out.q.to_numpy() > 0)
        assert len(out) < len(frame)
        last = out.index[pos[-1]]
        assert last == end - 1
        assert out.index[pos[-1] + 1] == end        # следующая точка — первый нулевой день
        assert out.index[pos[0] - 1] == start - 1 if pos[0] else True
