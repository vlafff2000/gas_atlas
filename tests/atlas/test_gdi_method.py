"""Метод ГДИ (в атмосферу / в шлейф) из столбцов «способ исслед.», «метод исслед.» и «% КРУ» базы ГДИ."""
import pandas as pd

from atlas.engine.core.loader import load_file

HEAD = ['№ п/п', '№скв', 'ГСП', 'дата', 'метод исслед.', 'способ исслед.', 'a', 'b', 'Qгаза тыс.м3/сут', '% КРУ', 'Рпл, на ИП кгс/см2', 'Рзаб, кгс/см2']


def _book(tmp_path, rows, extra=None):
    cols = HEAD + (extra or [])
    path = tmp_path / 'gdi.xlsx'
    pd.DataFrame(rows, columns=cols).to_excel(path, index=False)
    return path


def test_method_from_dikt_and_kru(tmp_path):
    rows = [[1, 37, 1, '2025-08-04', 'стац', 'ДИКТ-50', 0.5, 0.003, 134.2, 10, 90, 89],      # ДИКТ: в «% КРУ» диаметр шайбы
            [2, 31, 1, '2024-08-04', 'ИД', 'стац', 0.4, 0.002, 120.0, 55, 90, 88],
            [3, 32, 1, '2024-09-04', 'ИД', 'стац', 0.4, 0.002, 120.0, None, 90, 88]]
    got = load_file(_book(tmp_path, rows), module='gdi').frames['gdi'].set_index('well').method
    assert got.to_dict() == {'37': 'в атмосферу', '31': 'в шлейф', '32': ''}


def test_explicit_method_column_wins(tmp_path):
    rows = [[1, 37, 1, '2025-08-04', 'стац', 'ДИКТ-50', 0.5, 0.003, 134.2, 10, 90, 89, 'в шлейф']]
    got = load_file(_book(tmp_path, rows, ['метод']), module='gdi').frames['gdi']
    assert got.method.tolist() == ['в шлейф']
