"""Выбор скважин: список из буфера обмена, пересечение групп и скважин, пользовательские пресеты."""
from atlas import well_sets

MAPPING = {'1': {'group': 'ГСП 1'}, '2': {'group': 'ГСП 1'}, '3': {'group': 'ГСП 2'}, '4': {'group': 'ГСП 2'}}


def test_parse_list_accepts_excel_column_commas_tabs_and_semicolons():
    assert well_sets.parse_list('31\n12\r\n7') == ['31', '12', '7']
    assert well_sets.parse_list('31, 12,7') == ['31', '12', '7']
    assert well_sets.parse_list('31\t12;7|8') == ['31', '12', '7', '8']
    assert well_sets.parse_list('31 12  7') == ['31', '12', '7']
    assert well_sets.parse_list('31.0\n031\n31') == ['31']           # одна скважина в разной записи
    assert well_sets.parse_list('  \n ') == []


def test_match_keeps_list_order_and_reports_missing():
    found, missing = well_sets.match(['12', '99', '7'], ['7', '12', '31'])
    assert found == ['12', '7'] and missing == ['99']


def test_scoped_without_selection_is_no_restriction():
    assert well_sets.scoped([], [], MAPPING, ['1', '2', '3']) == (None, 0)


def test_scoped_intersects_groups_with_wells_filter_and_counts_hidden():
    picked, hidden = well_sets.scoped(['1', '3'], ['ГСП 1'], MAPPING, ['1', '2', '3', '4'])
    assert picked == ['1'] and hidden == 1                            # скважина 2 из ГСП 1 скрыта фильтром
    assert well_sets.scoped([], ['ГСП 2'], MAPPING, ['1', '2', '3', '4']) == (['3', '4'], 0)
    assert well_sets.scoped(['9'], ['ГСП 1'], MAPPING, ['1', '2']) == ([], 2)


def test_user_presets_are_saved_in_pxg_home(tmp_path, monkeypatch):
    monkeypatch.setenv('PXG_HOME', str(tmp_path))
    assert well_sets.user_presets() == []
    presets = well_sets.add_user_preset(' Сетка ', ['31', '31', '12'])
    assert presets[0]['label'] == 'Сетка' and presets[0]['wells'] == ['31', '12']
    assert well_sets.remove_user_preset(presets[0]['id']) == []


def test_user_preset_needs_name_and_wells(tmp_path, monkeypatch):
    monkeypatch.setenv('PXG_HOME', str(tmp_path))
    for name, wells in (('', ['1']), ('Пусто', [])):
        try:
            well_sets.add_user_preset(name, wells)
        except ValueError:
            continue
        raise AssertionError('пресет без названия или скважин не должен сохраняться')

