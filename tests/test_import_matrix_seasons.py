"""Матрица расходов без колонки вида: отбор и закачка определяются по расписанию сезонов проекта."""
import pandas as pd

from atlas.engine.core.loader import load_file
from atlas.engine.modules.seasons import resolve_auto_kinds

SCHEDULE = [['2024-11-01', 'withdrawal'], ['2025-04-16', 'none'], ['2025-05-01', 'injection'], ['2025-10-16', 'none'],
            ['2025-11-01', 'withdrawal']]


def matrix(tmp_path):
    p = tmp_path / 'matrix.xlsx'
    dates = ['2025-01-10', '2025-03-01', '2025-04-20', '2025-06-15', '2025-09-30', '2025-12-01']
    pd.DataFrame({'': pd.to_datetime(dates), '101': 100, '102': 200}).to_excel(p, sheet_name='Расход', index=False)
    return p


def test_matrix_kind_by_schedule(tmp_path):
    r = load_file(str(matrix(tmp_path)), production_kind='auto')
    prod = r.frames['production']
    assert set(prod.kind) == {'auto'}
    out, notes = resolve_auto_kinds(prod, SCHEDULE, 11, 4)
    by = out.groupby('date').kind.first().to_dict()
    assert by[pd.Timestamp('2025-01-10')] == 'withdrawal'
    assert by[pd.Timestamp('2025-06-15')] == 'injection'
    assert by[pd.Timestamp('2025-09-30')] == 'injection'
    assert by[pd.Timestamp('2025-12-01')] == 'withdrawal'
    assert by[pd.Timestamp('2025-04-20')] == 'withdrawal'       # нейтральный период: по месяцам (ноябрь–апрель — отбор)
    assert 'auto' not in set(out.kind)
    assert any('расписан' in n for n in notes)


def test_matrix_without_schedule_uses_months(tmp_path):
    prod = load_file(str(matrix(tmp_path)), production_kind='auto').frames['production']
    out, notes = resolve_auto_kinds(prod, None, 11, 4)
    assert out.set_index('date').kind[pd.Timestamp('2025-06-15')].iloc[0] == 'injection'
    assert notes and 'месяц' in notes[0]


def test_explicit_kind_not_touched(tmp_path):
    p = tmp_path / 'отбор.csv'
    p.write_text('Дата;101\n2025-06-15;100\n', encoding='utf-8')
    prod = load_file(str(p), production_kind='auto').frames['production']
    assert set(prod.kind) == {'withdrawal'}       # «отбор» в названии листа главнее расписания


def test_import_check_auto_kind_uses_project_schedule(tmp_path):
    from atlas.imports import Imports
    from atlas.projects import Projects
    path = matrix(tmp_path)
    imports = Imports(Projects(tmp_path / 'storage'))
    pid = imports.projects.create_demo()
    imports.projects.update_settings(pid, {'season_schedule': '01.11.2024 prod\n01.05.2025 inj\n01.11.2025 prod'})
    token = imports.upload(path.name, path.read_bytes())['token']
    pending = imports.check(pid, {'files': [{'token': token}], 'mode': 'production', 'kind': 'auto'})
    prod = imports.pending[pending['id']]['frames']['production']
    assert set(prod.kind) == {'withdrawal', 'injection'}
    assert prod[prod.date.eq(pd.Timestamp('2025-06-15'))].kind.eq('injection').all()
    assert any('расписанию' in str(x) for x in imports.pending[pending['id']]['issues']['Причина'])
