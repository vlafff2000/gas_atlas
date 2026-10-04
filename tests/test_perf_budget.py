"""Бюджет времени на большом демо (tools/check_perf.py): сравнение с бюджетом и целостность файла бюджета."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import check_perf  # noqa: E402


def test_compare_marks_slow_errors_and_missing_budget():
    rows = [('быстро', 0.5, 100, None), ('медленно', 9.0, 100, None), ('повтор (повтор)', 99.0, 1, None),
            ('сломано', 0.1, 1, 'HTTP 500: сбой'), ('новый', 1.0, 1, None)]
    report = check_perf.compare(rows, {'быстро': 2.0, 'медленно': 5.0, 'сломано': 5.0})
    assert report == [('быстро', 0.5, 2.0, 'ok'), ('медленно', 9.0, 5.0, 'медленно'),
                      ('сломано', 0.1, 5.0, 'ошибка'), ('новый', 1.0, None, 'без бюджета')]


def test_budget_file_is_sane_and_covers_new_sections():
    budget = json.loads(check_perf.BUDGET.read_text(encoding='utf8'))
    assert budget and all(isinstance(v, (int, float)) and v >= check_perf.FLOOR for v in budget.values())
    assert 'gdi_trend · все скважины' in budget and 'quality · все наборы' in budget
