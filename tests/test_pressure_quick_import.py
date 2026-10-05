import pytest
from app.core import pressure_import
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
    with pd.ExcelWriter(path) as xl:frame.to_excel(xl,sheet_name='Лист1',index=False);frame.assign(**{'5':frame['5']+2}).to_excel(xl,sheet_name='Лист2',index=False)
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

def test_rows_without_well_are_dropped_and_do_not_break_filtering():
    table=pd.DataFrame({'Дата':['2023-01-01','2023-01-02','2023-01-03'],'Скважина':['5',None,float('nan')],'Давление':[100.,101.,102.]})
    norm=pm.normalize(table,{'format':'long','date':'Дата','well':'Скважина','value':'Давление'})
    assert norm.well.tolist()==['5']
    data=pd.DataFrame({'object':'o','scenario':'s','well':['5',None],'date':pd.to_datetime(['2023-01-01']*2),'fact':[100.,100.],'model':[101.,101.],'fond':'Неизвестный','group':'Без группы','subgroup':''})
    d,_=pm.filter_data(data,{},{},{});assert d.well.tolist()==['5']
    import json;json.dumps({str(w):1 for w in data.well.unique()},sort_keys=True)


def test_wide_headers_named_like_wells_are_not_a_well_column():
    # эталон «dashboard 1.html»: id скважины из заголовков «WBP:74:», «'74'», «скв 89»
    for header in ('скв 74\tскв 89', "'74'\t'89'", 'WBP:74:\tWBP:89:', 'Well 74\tWell 89'):
        text = 'Дата\t' + header + '\n01.01.20\t119,9\t98\n01.02.20\t117,8\t96,5\n'
        record = pressure_import.parse_file('f.txt', text.encode())['sheets']['f']
        assert record['error'] is None and record['spec']['wide'], header
        assert sorted(set(record['norm'].well)) == ['74', '89'], header
        assert sorted(record['norm'].value) == [96.5, 98.0, 117.8, 119.9], header
    long = pressure_import.parse_file('l.txt', 'Дата\tСкважина\tДавление\n01.01.2020\t74\t119,9\n'.encode())['sheets']['l']
    assert not long['spec']['wide'] and list(long['norm'].well) == ['74']


def test_pair_duplicate_rules_and_diagnostics():
    from app.modules import pressure_match as pm
    fact = pd.DataFrame({'well': ['1', '1', '2'], 'date': pd.to_datetime(['2020-01-01'] * 2 + ['2020-01-01']),
                         'value': [10.0, 20.0, 5.0], '_row': [2, 3, 4]})
    model = pd.DataFrame({'well': ['1', '2'], 'date': pd.to_datetime(['2020-01-01'] * 2), 'value': [11.0, 6.0], '_row': [2, 3]})
    first, notes = pm.pair(fact, model, 'О', 'М')
    assert first.fact.tolist() == [10.0, 5.0] and notes and notes[0]['Строк'] == 2   # по умолчанию — первая запись
    assert pm.pair(fact, model, 'О', 'М', duplicate='last')[0].fact.tolist() == [20.0, 5.0]
    assert pm.pair(fact, model, 'О', 'М', duplicate='mean')[0].fact.tolist() == [15.0, 5.0]
    with pytest.raises(ValueError):
        pm.pair(fact, model, 'О', 'М', duplicate='error')

def test_space_separated_files_with_spelled_out_dates(tmp_path):
    days=pd.date_range('2022-01-01',periods=6,freq='10D');files={}
    for suffix,shift in [('факт',0),('модель_1',1)]:
        lines=['Скважина Дата Давление']+['%s %s %s'%(w,d.strftime('%d %b %Y'),100+i+shift) for w in ('1','2') for i,d in enumerate(days)]
        path=tmp_path/('Север_'+suffix+'.txt');path.write_text('\n'.join(lines),encoding='utf-8');files[str(path)]=(path.name,path.read_bytes())
    cache=loaded(files);rows=q.build_rows(files,cache,{},'Проект')
    data,notes,errors,warnings,summary=q.assemble(rows,cache,'first')
    assert not errors and len(data)==2*6 and np.allclose(data.model-data.fact,1)
    assert data.date.min()==pd.Timestamp('2022-01-01') and data.date.max()==pd.Timestamp('2022-02-20')


def history_files(tmp_path):
    days=pd.date_range('2022-01-01',periods=10,freq='10D');files={}
    fact=pd.DataFrame([(w,d.strftime('%d.%m.%Y'),100.0+i) for w in ('1','2') for i,d in enumerate(days)],columns=['Скважина','Дата','Давление'])
    for name,frame in [('история_факт',fact),('Старая_модель',fact.assign(Давление=fact.Давление+1)),('Новая_модель',fact.assign(Давление=fact.Давление+2))]:
        path=tmp_path/(name+'.csv');frame.to_csv(path,sep=';',index=False,encoding='cp1251',decimal=',');files[str(path)]=(path.name,path.read_bytes())
    return files

def test_shared_history_is_used_for_every_object(tmp_path):
    files=history_files(tmp_path);cache=loaded(files);shas={v[0]:k for k,v in files.items()}
    rows=q.build_rows(files,cache,{(shas['история_факт.csv'],'история_факт'):{'shared':True}},'Проект')
    data,notes,errors,warnings,summary=q.assemble(rows,cache,'first')
    assert not errors and sorted(data.object.unique())==['Новая','Старая']
    assert len(data)==2*2*10 and data.fact.notna().all()
    assert np.allclose(data[data.object=='Новая'].model-data[data.object=='Новая'].fact,2)

def test_history_is_taken_from_project_when_batch_has_no_fact(tmp_path):
    files=history_files(tmp_path);cache=loaded(files);shas={v[0]:k for k,v in files.items()}
    rows=q.build_rows(files,cache,{(shas['история_факт.csv'],'история_факт'):{'shared':True}},'Проект')
    stored,*_=q.assemble(rows,cache,'first')
    only={k:v for k,v in files.items() if v[0]=='Новая_модель.csv'};cache2=loaded(only)
    rows=q.build_rows(only,cache2,{},'Проект')
    assert q.assemble(rows,cache2,'first')[0] is None
    data,notes,errors,warnings,summary=q.assemble(rows,cache2,'first',stored)
    assert not errors and len(data)==20 and data.fact.notna().all() and 'история взята из проекта' in warnings[0]
