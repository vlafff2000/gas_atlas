import numpy as np
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from tools.make_pressure_samples import make_book
from app.modules import pressure_match as pm
from app.ui import pressure_quick_import as q


def books(tmp_path,count=3,wells=5,dates=20):
    files={}
    for i in range(count):
        path=tmp_path/('Объект_{:02d}.xlsx'.format(i+1));make_book(path,i,wells,dates);files[str(path)]=(path.name,path.read_bytes())
    return files

def loaded(files):
    return {sha:q.parse_file(name,content) for sha,(name,content) in files.items()}

def test_roles_and_objects_are_guessed_from_names():
    assert q.guess_role('Факт','a.xlsx',['Факт','Модель 1'],True)==(q.FACT,True)
    assert q.guess_role('Модель 2','a.xlsx',['Факт','Модель 2'],True)==(q.MODEL,True)
    assert q.guess_role('Фонд','a.xlsx',['Факт','Фонд'],True)==(q.FOND,True)
    assert q.guess_role('Инструкция','a.xlsx',['Факт','Инструкция'],True)[0]==q.SKIP
    assert q.guess_role('data','Север_факт.csv',['data'],False)==(q.FACT,True)
    assert q.guess_role('data','Север_модель_1.csv',['data'],True)==(q.MODEL,True)
    assert q.guess_object('Север_факт.csv',False,'Проект')=='Север'
    assert q.guess_object('Модель_1.csv',False,'Проект')=='Проект'
    assert q.guess_object('Книга.xlsx',True,'Проект')=='Книга'
    assert q.guess_scenario('Север_модель_1.csv','x',False,'Север')=='модель_1'

def test_many_workbooks_are_paired_per_object(tmp_path):
    files=books(tmp_path,count=4);cache=loaded(files)
    rows=q.build_rows(files,cache,{},'Проект')
    assert len(rows)==16 and {r['Роль'] for r in rows}=={q.FACT,q.MODEL,q.FOND}
    assert all(r['Статус']=='OK' for r in rows)
    data,notes,errors,warnings,summary=q.assemble(rows,cache,'first')
    assert not errors and data.object.nunique()==4 and data.scenario.nunique()==2
    assert len(data)==4*2*5*20 and data.fact.notna().all() and data.model.notna().all()
    assert set(data.fond)=={'Эксплуатационные','Наблюдательные'}
    assert len(summary)==8

def test_user_choices_override_guesses_and_missing_fact_is_reported(tmp_path):
    files=books(tmp_path,count=1);cache=loaded(files);sha=next(iter(files))
    rows=q.build_rows(files,cache,{(sha,'Факт'):{'use':False}},'Проект')
    data,notes,errors,warnings,summary=q.assemble(rows,cache,'first')
    assert data is None and 'не выбран лист или файл с фактом' in errors[0]

def test_separate_cp1251_files_are_grouped_by_object(tmp_path):
    rng=np.random.default_rng(0);days=pd.date_range('2022-01-01',periods=10,freq='10D');files={}
    for obj in ('Север','Юг'):
        fact=pd.DataFrame([(w,d.strftime('%d.%m.%Y'),round(100+rng.normal(),2)) for w in ('1','2') for d in days],columns=['Скважина','Дата','Давление'])
        for suffix,frame in [('факт',fact),('модель_1',fact.assign(Давление=fact.Давление+1))]:
            path=tmp_path/(obj+'_'+suffix+'.csv');frame.to_csv(path,sep=';',index=False,encoding='cp1251',decimal=',');files[str(path)]=(path.name,path.read_bytes())
    cache=loaded(files);rows=q.build_rows(files,cache,{},'Проект')
    data,notes,errors,warnings,summary=q.assemble(rows,cache,'first')
    assert not errors and sorted(data.object.unique())==['Север','Юг'] and set(data.scenario)=={'модель_1'}
    assert len(data)==2*2*10 and np.allclose(data.model-data.fact,1)

def test_unrecognized_sheet_names_use_order_and_ask_for_review(tmp_path):
    path=tmp_path/'Книга.xlsx';frame=pd.DataFrame({'Дата':pd.date_range('2023-01-01',periods=6),'5':np.arange(6)+100.})
    with pd.ExcelWriter(path) as xl:frame.to_excel(xl,'Лист1',index=False);frame.assign(**{'5':frame['5']+2}).to_excel(xl,'Лист2',index=False)
    files={'k':(path.name,path.read_bytes())};cache=loaded(files);rows=q.build_rows(files,cache,{},'Проект')
    assert [r['Роль'] for r in rows]==[q.FACT,q.MODEL] and all('проверьте' in r['Статус'] for r in rows)
    data,*_=q.assemble(rows,cache,'first');assert len(data)==6 and np.allclose(data.model-data.fact,2)

def test_large_box_groups_send_exact_quartiles_not_raw_values():
    values=np.random.default_rng(1).normal(10,2,20000)
    small=go.Figure();pm.add_box(small,values[:100],'a','a');assert len(small.data[0].y)==100
    big=go.Figure();pm.add_box(big,values,'a','a')
    box=big.data[0];assert box.y is None
    q1,median,q3=np.percentile(values,[25,50,75])
    assert np.isclose(box.q1[0],q1) and np.isclose(box.median[0],median) and np.isclose(box.q3[0],q3)
    assert len(big.data)==2 and len(big.data[1].y)<=300

def test_cdf_downsampling_keeps_range_and_last_point():
    x,y=pm.downsample_sorted(np.random.default_rng(2).random(100000),500)
    assert len(x)<=500 and y[-1]==100 and x[0]<=x[1]

def test_screen_crossplot_is_sampled_but_exports_stay_complete(tmp_path):
    files=books(tmp_path,count=2,wells=10,dates=50);cache=loaded(files);rows=q.build_rows(files,cache,{},'Проект')
    data,*_=q.assemble(rows,cache,'first');d,_=pm.filter_data(data,{},{},{})
    full=pm.figure.__wrapped__(d,'cross',{});shown=pm.figure.__wrapped__(d,'cross',{'screen_limit':300})
    count=lambda fig:sum(len(t.x) for t in fig.data if t.meta and t.meta.get('selectable'))
    assert count(full)==len(d) and count(shown)==300
    assert any(a.text.startswith('Показана выборка') for a in shown.layout.annotations)
