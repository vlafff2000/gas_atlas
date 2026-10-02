import pandas as pd
from pathlib import Path
from app.core import config,profiles,tabular
from app.ui import general_import as gi
from app.ui import pressure_quick_import as q

EXAMPLES=Path(__file__).resolve().parents[1]/'examples'

def sheet(name):
    fmt,tables=tabular.read_content((EXAMPLES/name).read_bytes(),name,31)
    return next(iter(tables.values()))

def test_every_example_sheet_is_classified():
    expected={'01_long_format.xlsx':'production','06_GDI_5_columns.csv':'gdi','07_response.csv':'response','04_groups.xlsx':'groups'}
    for name,module in expected.items():
        assert gi.describe(sheet(name),'auto')[0]==module,name

def test_forced_type_builds_the_same_spec_structure_as_the_detailed_editor():
    spec=gi.auto_spec(sheet('06_GDI_5_columns.csv'),'gdi')
    assert spec['enabled'] and spec['module']=='gdi' and {'well','date','q','p_res','p_bh'}<=set(spec['mapping'])
    try:gi.auto_spec(sheet('07_response.csv'),'gdi');assert False
    except ValueError:pass

def test_pressure_books_are_recognised_by_sheet_names():
    assert gi.is_pressure_book(['Факт','Модель 1','Фонд']) and not gi.is_pressure_book(['Отбор','Закачка'])

def test_profiles_roundtrip_and_apply_to_quick_import(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'STORAGE',tmp_path)
    raw=pd.DataFrame([['Отчет',None,None],['Дата','Скв.','Рпл, бар'],['2023-01-01','5',100.],['2023-01-02','5',101.]])
    spec={'enabled':True,'valid':True,'header':1,'mapping':{'date':0,'well':1,'value':2},'wide':False,'names':{},'wellcols':[],'fond_pairs':[],'module':'pressure_match','datecol':0}
    assert profiles.find(raw,'pressure') is None
    assert profiles.save(raw,spec,'pressure') and profiles.count()==1
    assert profiles.find(raw,'pressure')['mapping']['value']==2 and profiles.find(raw,'general') is None
    assert q.auto_spec(raw)['mapping']['value']==2
    profiles.forget(raw,spec,'pressure');assert profiles.count()==0
