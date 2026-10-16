"""БД по учету газа в Атласе: чтение листа «БД», итоги по месяцам, график и пропуски.
Файлы — литеральные, в тестах записываются прямо здесь; реальных файлов компании в репозитории нет."""
import pandas as pd
import pytest

from atlas.domain import DatasetKind
from atlas.engine.core import gas_db_import as g
from atlas.modules.gas_accounting import GasAccountingModule, monthly

GAS = DatasetKind.GAS_DB
W = 'Отобрано газа из ПХГ за сутки / Всего по ПЗРГ - за сутки по ПХГ'
I = 'Закачано в ПХГ за СУТКИ, тыс.м3/сут'
WATER = 'Расход за сутки / Пластовая жидкость (м3) / Всего по ПХГ'


def _book(path, rows, extra=None):
    df = pd.DataFrame(rows)
    df.to_excel(path, sheet_name='БД', index=False)
    return path


def test_build_takes_one_row_per_day_and_kind(tmp_path):
    rows = [
        {'Режим': 'отбор', 'Дата': '2025-10-01', W: 100.0, I: None, WATER: 10.0},
        {'Режим': 'отбор', 'Дата': '2025-10-02', W: 200.0, I: None, WATER: None},   # нет замера выноса
        {'Режим': 'закачка', 'Дата': '2025-10-01', W: None, I: 50.0, WATER: None},
        {'Режим': 'прочее', 'Дата': '2025-10-03', W: 1.0, I: 1.0, WATER: 1.0},       # не отбор и не закачка
    ]
    out = g.build(_book(tmp_path / 'БД_по_учету_газа.xlsx', rows))
    # сортировка по режиму, затем по дате: injection < withdrawal
    assert list(out['kind']) == ['injection', 'withdrawal', 'withdrawal']
    assert list(out['gas']) == [50.0, 100.0, 200.0]
    assert out['water'].iloc[1] == 10.0 and pd.isna(out['water'].iloc[2])


def test_build_refuses_missing_or_ambiguous_column(tmp_path):
    rows = [{'Режим': 'отбор', 'Дата': '2025-10-01', W: 1.0, WATER: 1.0}]          # нет колонки закачки
    with pytest.raises(ValueError, match='найден 0 раз'):
        g.build(_book(tmp_path / 'x.xlsx', rows))


def test_monthly_gap_is_not_zero_and_factor_uses_measured_days_only():
    frame = pd.DataFrame({
        'kind': ['withdrawal'] * 4,
        'date': pd.to_datetime(['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04']),
        'gas': [80000.0, 0.0, 40000.0, 20000.0],
        'water': [100.0, None, None, 60.0],
    })
    m = monthly(frame).iloc[0]
    assert m['days'] == 4 and m['water_days'] == 2
    assert m['water'] == pytest.approx(160.0)
    assert m['factor'] == pytest.approx(1.6)                    # 160 / (100000 / 1000)
    empty = monthly(pd.DataFrame({'kind': ['x'], 'date': pd.to_datetime(['2025-10-23']), 'gas': [5.0],
                                  'water': [None]})).iloc[0]
    assert pd.isna(empty['water']) and pd.isna(empty['factor'])


def test_module_chart_and_table_for_selected_kind():
    data = {GAS: pd.DataFrame({
        'kind': ['withdrawal', 'withdrawal', 'injection'],
        'date': pd.to_datetime(['2025-10-01', '2025-10-02', '2025-10-01']),
        'gas': [100.0, 200.0, 50.0],
        'water': [10.0, None, None]})}
    res = GasAccountingModule().run(data, {'kind': 'withdrawal', 'date_from': None, 'date_to': None})
    assert res.charts[0].series[0].y == [100.0, 200.0]
    assert res.tables[0].frame['days'].tolist() == [2]


def test_module_without_data_gives_note_not_error():
    res = GasAccountingModule().run({}, {'kind': 'injection', 'date_from': None, 'date_to': None})
    assert not res.charts and res.notes and 'БД по учету газа' in res.notes[0].text


def test_build_reads_canonical_column_names(tmp_path):
    # новые выгрузки: главные колонки под каноническими именами (как в all_scripts), строки те же
    rows = [
        {'Режим': 'отбор', 'Дата': '2025-10-01', g.CANON_WITHDRAW: 100.0, g.CANON_INJECT: None, g.CANON_WATER: 10.0},
        {'Режим': 'закачка', 'Дата': '2025-10-01', g.CANON_WITHDRAW: None, g.CANON_INJECT: 50.0, g.CANON_WATER: None},
    ]
    out = g.build(_book(tmp_path / 'БД_по_учету_газа.xlsx', rows))
    assert list(out['kind']) == ['injection', 'withdrawal']
    assert list(out['gas']) == [50.0, 100.0]
    assert out['water'].iloc[1] == 10.0
