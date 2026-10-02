import io
import json
import zipfile
from pathlib import Path
import pandas as pd
import pytest
from app.core.loader import load_file
from app.core.demo import demo_frames
from app.core.storage import Store

def put(tmp_path,text,name='data.csv',encoding='utf8'):
    p=tmp_path/name;p.write_text(text,encoding=encoding);return p

def test_gdi_five_columns(tmp_path):
    p=put(tmp_path,'Скважина;Дата;Q;Рпл;Рзаб\n31;10.12.2021;256,8;75,4;71,01\n')
    r=load_file(p); d=r.frames['gdi']
    assert r.rejected==0 and d.well.iloc[0]=='31'
    assert abs(d.dp2.iloc[0]-642.7399)<1e-7

def test_response_cp1251_and_bad_text(tmp_path):
    p=put(tmp_path,'Скважина;Дата;Горизонт;Уровень жидкости;Рпл привед\n132;11.01.04;Окский;29,4 м;71\n133;12.01.04;Окский;10-20 м;72\n',encoding='cp1251')
    r=load_file(p); assert len(r.frames['response'])==1 and r.rejected==1

def test_matrix_and_units(tmp_path):
    p=put(tmp_path,'\t540\t541\n01.11.2026\t48\t181,68\n02.11.2026\t0\t175\n',name='Отборы.txt')
    d=load_file(p,production_unit='тыс. м³/сут').frames['production']
    assert len(d)==4 and d.q.sum()==404680

def test_header_offset_and_bad_rows(tmp_path):
    p=put(tmp_path,'Название отчета;;\nСкважина;Дата;Расход\n73;01.11.2025;2000\n73;не дата;2000\n73;02.11.2025;-1\n')
    r=load_file(p); assert len(r.frames['production'])==1 and r.rejected==2
    assert r.issues[0]['Строка']==4

def test_legacy_gdi(tmp_path):
    p=put(tmp_path,'№ скважины;Дата ГДИ;Qгаза тыс.м3/сут;Рпл2-Рз2;a;b\n73;01.11.2025;100;300;1;0,02\n')
    r=load_file(p); assert r.frames['gdi'].a_db.iloc[0]==1

def test_explicit_pressure_conflict_report(tmp_path):
    p=put(tmp_path,'Скважина;Дата;Q;Рпл;Рзаб;dp2\n1;01.01.2025;10;75;70;1\n')
    r=load_file(p); assert r.warnings==1 and r.frames['gdi'].dp2.iloc[0]==725

def test_original_xlsx_formats():
    examples=Path(__file__).resolve().parents[1]/'examples'
    for n in ('01_long_format.xlsx','02_matrix.xlsx','03_single_sheet.xlsx'):
        r=load_file(examples/n); assert 'production' in r.frames and len(r.frames['production'])>0

def test_group_import_header(tmp_path):
    p=put(tmp_path,'Скважина;Группа;Подгруппа\n540;ГСП 9;1\n')
    r=load_file(p); assert r.frames['groups'].group.iloc[0]=='ГСП 9'

def test_storage_persistence_backup_and_conflict(tmp_path):
    store=Store(tmp_path/'store'); pid=store.create('Тест'); frames=demo_frames()
    store.commit(pid,frames,expected=0)
    manifest,loaded=Store(tmp_path/'store').load(pid)
    pd.testing.assert_frame_equal(frames['gdi'],loaded['gdi'])
    with pytest.raises(ValueError,match='другой вкладке'): store.commit(pid,settings={},expected=0)
    copy=store.restore(store.backup(pid)); m,d=store.load(copy)
    assert copy!=pid and m['name']=='Тест (копия)' and len(d['production'])==len(frames['production'])

def test_backup_traversal_rejected(tmp_path):
    s=Store(tmp_path); b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z: z.writestr('../escape','x')
    with pytest.raises(ValueError,match='пути'): s.restore(b.getvalue())

def test_chunked_import(tmp_path):
    p=put(tmp_path,'Скважина;Дата;Q\n'+'\n'.join(f'{i};01.11.2025;10' for i in range(1003)))
    result=load_file(p,chunk_size=101); assert len(result.frames['production'])==1003

def test_legacy_project_migration(tmp_path):
    s=Store(tmp_path/'store')
    obj={'version':1,'name':'Старый объект','settings':{'start':10,'end':3},'mapping':{'73':{'group':'ГСП 9','subgroup':'1'}},
         'records':[{'well':'73','date':'2025-11-01','flow':40000,'kind':'withdrawal','season':'2025-2026','source':'ГСП 9'}]}
    pid=s.import_legacy(json.dumps(obj));m,d=s.load(pid)
    assert m['settings']['season_start']==10 and d['production'].q.iloc[0]==40000 and m['groups']['73']['subgroup']=='1'

def test_header_units_override_default(tmp_path):
    p=put(tmp_path,'Скважина;Дата;Q, м³/сут;Рпл;Рзаб;a;b\n31;01.01.2026;100000;75;70;0,001;0,00000002\n')
    d=load_file(p).frames['gdi']
    assert d.q.iloc[0]==100 and d.a_db.iloc[0]==1 and abs(d.b_db.iloc[0]-.02)<1e-12

def test_headerless_groups(tmp_path):
    p=put(tmp_path,'540\tГСП 9\t1\n541\tГСП 9\t2\n',name='groups.txt')
    r=load_file(p,module='groups');assert r.frames['groups'].well.tolist()==['540','541']
    p=put(tmp_path,'540\t2\n541\t3\n',name='subgroups.txt')
    r=load_file(p,module='subgroups');assert r.frames['groups'].subgroup.tolist()==['2','3']
