"""Одна база расходов — три читалки (аудит объединения, пункт 8): Атлас дает те же суммы, что Карты ГСП и Скедул.

Файл tests/fixtures/db_rashody_mini.xlsx — тот же, что в all_scripts/tests/fixtures (байты совпадают).
Ожидаемые суммы — в EXPECTED; менять только вместе с all_scripts/tests/test_db_rashody_readers.py.
"""
import os
from datetime import date

from atlas.engine.core.loader import load_file

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fixtures', 'db_rashody_mini.xlsx')

# (скважина, дата) → суточный расход газа, м³/сут; отбор и закачка
EXPECTED = {
    (101, date(2026, 10, 1)): 1000.0,
    (101, date(2026, 10, 2)): 1200.0,
    (102, date(2026, 10, 1)): 800.0,
    (102, date(2026, 10, 2)): 900.0,
    (201, date(2026, 10, 1)): 500.0,
}


def test_atlas_reads_same_sums():
    frame = load_file(FIXTURE).frames['production']
    got = {(int(r.well), r.date.date()): float(r.q) for r in frame.itertuples()}
    assert got == EXPECTED
