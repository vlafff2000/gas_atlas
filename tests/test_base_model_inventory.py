import pytest

from atlas import base_model

pytest.importorskip('tnav_results.base_model')


def test_inventory_groups_found_and_unknown(tmp_path):
    if not hasattr(__import__('tnav_results.base_model', fromlist=['x']), 'inventory'):
        pytest.skip('читалка без inventory')
    (tmp_path / 'pvt.inc').write_text('PVTG\n1 2 3 /\n/\nMYWORD\n')
    (tmp_path / 'm.data').write_text("START\n 1 JAN 2020 /\nINCLUDE\n'pvt.inc' /\nWELLTRACK 'W1' 1 2 3 4 /\n")
    r = base_model.inventory(str(tmp_path / 'm.data'))
    status = {i['words'][0]: i['status'] for g in r['groups'] for i in g['items']}
    assert status['WELLTRACK'] == 'read' and status['PVTG'] == 'found' and status['DIMENS'] == 'absent'
    assert [f['name'] for f in r['files']] == ['m.data', 'pvt.inc']
    assert [o['word'] for o in r['other']] == ['MYWORD']
