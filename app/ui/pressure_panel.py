"""Compact two-pane pressure dashboard inspired by the supplied HTML page."""
import io,json,tempfile,hashlib
from collections import OrderedDict
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st
from app.core.config import ordered
from app.core.export import csv_bytes
from app.core.logging_utils import show_error
from app.modules import pressure_match as pm,charts
from app.modules.pressure_workbook import workbook_bytes
from app.ui.filters import filter_bar
from app.ui.selection import checklist,parse_wells,paginate

from app.ui.import_editor import samples,full_tables,text_options,sheet_editor,pressure_table,fonds_table

def read(content,name):return full_tables(content,name)

def _pressure_source(file,prefix):
    prefix+='_'+hashlib.sha256(file.getvalue()).hexdigest()[:12]
    st.markdown('**'+file.name+'**')
    encoding,delimiter=text_options(file.getvalue(),file.name,prefix)
    fmt,preview=samples(file.getvalue(),file.name,encoding,delimiter)
    st.caption('Формат по содержимому: '+fmt.upper())
    data=full_tables(file.getvalue(),file.name,encoding,delimiter)
    for table in data.values():table.attrs['source_options']=[encoding,delimiter]
    return data,preview,prefix

def import_panel(store,pid,manifest,raw_frames,key):
    done=st.session_state.pop(key('pmq_done'),None)
    if done:getattr(st,done[0])(done[1])
    has='pressure_match' in raw_frames
    title='Данные давлений · загрузить или обновить' if has else 'Загрузка данных давлений'
    # A bordered container, not an expander: the import forms use expanders and Streamlit forbids nesting them.
    if has and not st.toggle(title,value=False,key=key('pm_import_open')):return
    with st.container(border=True):
        mode=st.radio('Способ загрузки',['Быстрая (автоматически)','Подробная (по листам)'],horizontal=True,key=key('pm_import_style'),
            help='Быстрая: перетащите сразу все файлы — факт, модели и фонды определятся сами, проверка в одной таблице. Подробная: ручная настройка шапки и колонок каждого листа.')
        if mode.startswith('Быстрая'):
            from app.ui.pressure_quick_import import render as quick_import
            quick_import(store,pid,manifest,raw_frames,key)
        else:
            detailed_import(store,pid,manifest,raw_frames,key)

def detailed_import(store,pid,manifest,raw_frames,key):
    with st.container():
        mode=st.radio('Источники',['Книги Excel / ODS: факт + модель','Отдельные файлы факта и сценариев'],horizontal=True,key=key('pm_import_mode'))
        duplicate=st.selectbox('Повторные скважина / дата',['first','last','mean','error'],format_func=lambda x:{'first':'Первая запись (как в Python-скрипте)','last':'Последняя запись','mean':'Среднее значение','error':'Остановить импорт'}[x],key=key('pm_duplicates'))
        imports=[];originals=[]
        try:
            if mode.startswith('Книги'):
                books=st.file_uploader('Объекты: одна или несколько книг Excel / ODS',type=['xlsx','xls','xlsm','ods'],accept_multiple_files=True,key=key('pm_books'))
                for i,file in enumerate(books):
                    data,preview,prefix=_pressure_source(file,key('pm_book_'+str(i)));names=list(data)
                    fs=next((n for n in names if any(k in n.lower() for k in ('факт','hist','fact'))),names[0])
                    a,b=st.columns(2);fact_sheet=a.selectbox('Лист факта',names,index=names.index(fs),key=prefix+'_fact_sheet')
                    ms=[n for n in names if n!=fact_sheet and any(k in n.lower() for k in ('модел','gdm','model'))]
                    model_sheets=b.multiselect('Листы моделей / сценариев',[n for n in names if n!=fact_sheet],default=ms,key=prefix+'_models')
                    name=st.text_input('Название объекта',Path(file.name).stem,key=prefix+'_object')
                    fact_spec=sheet_editor(preview[fact_sheet],fact_sheet,prefix+'_fact',pressure=True)
                    fd,fact_cfg=pressure_table(data[fact_sheet],fact_spec);fonds={}
                    fond_sheets=[n for n in names if n!=fact_sheet and n not in model_sheets and ('фонд' in n.lower() or 'fond' in n.lower())]
                    fond_sheets=st.multiselect('Листы фондов', [n for n in names if n!=fact_sheet and n not in model_sheets],default=fond_sheets,key=prefix+'_fonds')
                    for n in fond_sheets:
                        spec=sheet_editor(preview[n],n,prefix+'_fond_'+n,pressure=True,fonds=True);fonds.update(fonds_table(data[n],spec))
                    models=[]
                    for n in model_sheets:
                        spec=sheet_editor(preview[n],n,prefix+'_model_'+n,pressure=True)
                        md,cfg=pressure_table(data[n],spec);models.append((n,md,cfg))
                    imports.append((name,fd,fact_cfg,models,fonds,file.name,fact_sheet));originals.append(file)
            else:
                a,b=st.columns(2)
                fact_file=a.file_uploader('Факт (X)',type=['xlsx','xls','xlsm','ods','csv','tsv','txt','dat'],key=key('pm_fact_upload'))
                model_files=b.file_uploader('Модели / сценарии (Y)',type=['xlsx','xls','xlsm','ods','csv','tsv','txt','dat'],accept_multiple_files=True,key=key('pm_model_upload'))
                name=st.text_input('Объект для отдельных файлов',manifest['name'],key=key('pm_separate_object'))
                if fact_file:
                    fd,preview,prefix=_pressure_source(fact_file,key('pm_separate_fact'))
                    fs=st.selectbox('Лист факта',list(fd),key=prefix+'_sheet')
                    spec=sheet_editor(preview[fs],fs,prefix,pressure=True);fact,fcfg=pressure_table(fd[fs],spec);models=[]
                    for i,file in enumerate(model_files):
                        md,mpreview,mprefix=_pressure_source(file,key('pm_separate_model_'+str(i)))
                        ms=st.selectbox('Лист модели · '+file.name,list(md),key=mprefix+'_sheet')
                        scenario=st.text_input('Название сценария · '+file.name,Path(file.name).stem,key=mprefix+'_scenario')
                        spec=sheet_editor(mpreview[ms],ms,mprefix,pressure=True);model,cfg=pressure_table(md[ms],spec)
                        models.append((scenario,model,cfg))
                    imports.append((name,fact,fcfg,models,{},fact_file.name,fs));originals=[fact_file]+model_files
            fingerprint=json.dumps([duplicate,[(name,fcfg,list(fd.columns),[(label,cfg,list(md.columns)) for label,md,cfg in models],fonds,filename,sheet) for name,fd,fcfg,models,fonds,filename,sheet in imports],[(f.name,hashlib.sha256(f.getvalue()).hexdigest()) for f in originals]],ensure_ascii=False,sort_keys=True)
            st.caption('Сопоставление по скважине и календарной дате. Интерполяция и подстановка модели с соседней даты не выполняются. Поддерживаются длинные таблицы и матрицы «дата × скважины».')
            if st.button('Проверить сопоставление',key=key('pm_validate'),disabled=not imports):
                parts=[];diagnostics=[]
                for name,fd,fcfg,models,fonds,filename,sheet in imports:
                    fact=pm.normalize(fd,fcfg)
                    for scenario,md,mcfg in models:
                        data,notes=pm.pair(fact,pm.normalize(md,mcfg),name,scenario,fonds,duplicate)
                        data['file']=filename;data['sheet']=sheet;parts.append(data);diagnostics.extend(notes)
                if not parts:raise ValueError('Выберите хотя бы один модельный лист или файл сценария.')
                result=pd.concat(parts,ignore_index=True)
                if result.empty:raise ValueError('Нет записей с распознанными датами и скважинами. Проверьте колонки и формат даты.')
                if result.duplicated(['object','scenario','well','date']).any():raise ValueError('Повторяются имена объектов / сценариев. Задайте уникальные названия.')
                st.session_state[key('pm_pending')]=(result,diagnostics,[(f.name,f.getvalue()) for f in originals],fingerprint)
            pending=st.session_state.get(key('pm_pending'))
            if pending and pending[3]==fingerprint:
                data,notes=pending[:2];st.success('Проверено: '+str(len(data))+' пар / неполных пар, объектов '+str(data.object.nunique())+', сценариев '+str(data.scenario.nunique()))
                if notes:st.dataframe(pd.DataFrame(notes),hide_index=True,use_container_width=True)
                if st.button('Сохранить данные давлений в проект',key=key('pm_commit'),type='primary'):
                    frames=dict(raw_frames);frames['pressure_match']=data
                    store.commit(pid,frames,expected=manifest['revision'],action='Импорт кроссплота давлений',details={'rows':len(data),'diagnostics':notes})
                    with tempfile.TemporaryDirectory() as tmp:
                        for name,content in pending[2]:
                            p=Path(tmp)/Path(name).name;p.write_bytes(content);store.keep_original(pid,p)
                    st.session_state.pop(key('pm_pending'),None);st.rerun()
                st.caption('Сохранение заменит только таблицу сопоставления давлений; остальные модули сохранятся.')
        except Exception as error:show_error('Загрузка давлений: '+str(error))

def _multi(label,choices,default,widget,fmt=str,container=None):
    """Compact dropdown multi-select that keeps the stored selection valid when the options shrink."""
    choices=list(dict.fromkeys(str(v) for v in choices))
    st.session_state[widget]=[v for v in st.session_state.get(widget,default) if v in choices]
    return (container or st).multiselect(label,choices,key=widget,format_func=fmt,placeholder='Не выбрано')

def _pick(label,choices,default,widget,container,fmt=str,searchable=False):
    """Filter button showing 'selected of total'; the list opens in a popover (checklist with search for long lists)."""
    choices=list(dict.fromkeys(str(v) for v in choices))
    current=[v for v in st.session_state.get(widget,default) if v in choices]
    known=st.session_state.get(widget+'_universe')
    if known is not None and set(choices)-set(known):
        # Data was added: newly appeared objects / scenarios / wells join the selection instead of staying hidden.
        current=[v for v in choices if v in current or v not in known];st.session_state[widget]=current
    st.session_state[widget+'_universe']=choices
    with container:
        st.caption(label)
        with st.popover(str(len(current))+' из '+str(len(choices)),use_container_width=True):
            if searchable:return checklist(label,choices,default,widget,fmt)
            return _multi(label,choices,default,widget,fmt)

def _seed(data,key,default):
    for widget,field in FIELDS.items():
        if field in default and key(widget) not in st.session_state:st.session_state[key(widget)]=default[field]
    if default.get('dates') and key('pm_dates') not in st.session_state:st.session_state[key('pm_dates')]=tuple(pd.Timestamp(v).date() for v in default['dates'])
    if default.get('percentiles') and key('pm_percentiles') not in st.session_state:st.session_state[key('pm_percentiles')]=','.join(str(v) for v in default['percentiles'])
    for group,value in default.get('group_thresholds',{}).items():
        st.session_state.setdefault(key('pm_override_'+group),True);st.session_state.setdefault(key('pm_threshold_'+group),value)

FIELDS={'pm_objects':'objects','pm_scenarios':'scenarios','pm_groups':'groups','pm_wells':'wells','pm_fonds':'fonds','pm_recent':'recent','pm_zeros':'exclude_zeros','pm_unit':'unit','pm_threshold_mode':'threshold_mode','pm_threshold':'threshold','pm_inclusive':'inclusive','pm_color':'color','pm_bins':'bins','pm_bands':'bands','pm_percentile_lines':'percentile_lines','pm_outliers':'outliers'}
COLORS={'scenario':'Сценарии','group':'Группы','well':'Скважины','object':'Объекты','object_group':'Категории объектов'}

def options(data,mapping,key,compact=False,default=None,bar=False,slots=None):
    """Crossplot settings. bar=False: one vertical column (export tab). bar=True: compact bar above the charts."""
    default=default or {};cfg={'recent_starts':{str(obj):str(pd.Timestamp(year=value.year-3,month=4,day=1).date()) for obj,value in data.groupby('object').date.max().items()}}
    _seed(data,key,default)
    all_objects,all_scenarios=ordered(data.object),ordered(data.scenario)
    groups=ordered(mapping.get(w,{}).get('group','Без группы') for w in data.well.unique())
    if bar:
        oc,sc,gc,fc,wc,dc=st.columns([1,1,1,1,1,1.7])
        cfg['objects']=_pick('Объекты',all_objects,default.get('objects',all_objects),key('pm_objects'),oc)
        cfg['scenarios']=_pick('Сценарии модели',all_scenarios,default.get('scenarios',all_scenarios),key('pm_scenarios'),sc)
        cfg['groups']=_pick('Группы',groups,default.get('groups',groups),key('pm_groups'),gc)
        cfg['fonds']=_pick('Фонды',ordered(data.fond),default.get('fonds',ordered(data.fond)),key('pm_fonds'),fc)
        choices=ordered(w for w in data.well if mapping.get(w,{}).get('group','Без группы') in cfg['groups'])
        cfg['wells']=_pick('Скважины',choices,default.get('wells',choices),key('pm_wells'),wc,lambda w:'№ '+w,searchable=True)
        extent=(data.date.min().date(),data.date.max().date())
        if st.session_state.get(key('pm_dates_extent')) not in (None,extent):st.session_state[key('pm_dates')]=extent
        st.session_state[key('pm_dates_extent')]=extent
        dc.caption('Период сопоставления');span=dc.date_input('Период сопоставления',(data.date.min().date(),data.date.max().date()),key=key('pm_dates'),label_visibility='collapsed');cfg['dates']=[str(v) for v in span]
        uc,mc,tc,cc,kc=st.columns([1,1.1,1,1.1,1.8])
    else:
        a,b=st.columns(2)
        with a:cfg['objects']=checklist('Объекты',all_objects,default.get('objects',all_objects),key('pm_objects'))
        with b:cfg['scenarios']=checklist('Сценарии модели',all_scenarios,default.get('scenarios',all_scenarios),key('pm_scenarios'))
        a,b=st.columns(2)
        with a:cfg['groups']=checklist('Группы',groups,default.get('groups',groups),key('pm_groups'))
        choices=ordered(w for w in data.well if mapping.get(w,{}).get('group','Без группы') in cfg['groups'])
        with b:cfg['wells']=checklist('Скважины',choices,default.get('wells',choices),key('pm_wells'),lambda w:'№ '+w)
        cfg['fonds']=st.multiselect('Фонды',ordered(data.fond),default=default.get('fonds',ordered(data.fond)),key=key('pm_fonds'))
        span=st.date_input('Период сопоставления',(data.date.min().date(),data.date.max().date()),key=key('pm_dates'));cfg['dates']=[str(v) for v in span]
        uc=mc=tc=cc=kc=st
    if not bar:
        cfg['recent']=st.checkbox('Только последние 3 года по правилу исходного скрипта',default.get('recent',False),key=key('pm_recent'))
        cfg['exclude_zeros']=st.checkbox('Исключать нулевые давления факта и модели',default.get('exclude_zeros',True),key=key('pm_zeros'))
        a,b=st.columns(2);uc,mc=a,b
    cfg['unit']=uc.selectbox('Единицы',['бар','кгс/см²','МПа'],key=key('pm_unit'),help='Меняет подписи. Числа факта и модели должны быть уже в одинаковых единицах.')
    cfg['threshold_mode']=mc.selectbox('Порог совпадения',['absolute','relative'],format_func=lambda x:('Абсолютный' if bar else 'Абсолютное отклонение (как в HTML)') if x=='absolute' else ('Относительный, %' if bar else 'Относительное отклонение, %'),key=key('pm_threshold_mode'))
    if bar:cfg['threshold']=tc.number_input('Значение порога',min_value=0.,value=float(default.get('threshold',10)),key=key('pm_threshold'))
    else:cfg['threshold']=st.number_input('Общий порог совпадения',min_value=0.,value=float(default.get('threshold',10)),key=key('pm_threshold'))
    if bar:
        cfg['color']=cc.selectbox('Цвет точек',list(COLORS),format_func=COLORS.get,key=key('pm_color'))
        with kc:
            cfg['exclude_zeros']=st.checkbox('Без нулевых давлений',default.get('exclude_zeros',True),key=key('pm_zeros'))
            cfg['recent']=st.checkbox('Последние 3 года',default.get('recent',False),key=key('pm_recent'),help='По правилу исходного скрипта: с 1 апреля (последний год данных − 3).')
        calc,view,axes_slot,cats,save_slot,export_slot,group_slot=st.columns([1.2,1,1,1.2,1,.8,1])
    else:
        calc=view=axes_slot=cats=None
    def calc_block():
        cfg['inclusive']=st.checkbox('Включать границу порога: ≤ (в HTML используется <)',default.get('inclusive',False),key=key('pm_inclusive'))
        with st.expander('Пороги отдельных групп',expanded=bar) if not bar else st.container():
            cfg['group_thresholds']={}
            for group in groups:
                override=st.checkbox('Отдельный порог · '+group,key=key('pm_override_'+group))
                if override:cfg['group_thresholds'][group]=st.number_input('Порог · '+group,min_value=0.,value=float(default.get('group_thresholds',{}).get(group,cfg['threshold'])),key=key('pm_threshold_'+group))
        text=st.text_input('Процентили через запятую','80,85,90',key=key('pm_percentiles'))
        try:
            cfg['percentiles']=sorted(set(float(s.strip()) for s in text.replace(';',',').split(',') if s.strip()))
            if not cfg['percentiles'] or any(not 0<=p<=100 for p in cfg['percentiles']):raise ValueError()
        except ValueError:st.warning('Процентили: числа от 0 до 100. Используются 80, 85, 90.');cfg['percentiles']=[80,85,90]
    def view_block():
        if not bar:cfg['color']=st.selectbox('Цвета точек',list(COLORS),format_func=COLORS.get,key=key('pm_color'))
        cfg['bins']=st.number_input('Интервалов гистограммы',5,100,20,key=key('pm_bins'))
        cfg['bands']=st.checkbox('Линии порога на кроссплоте',True,key=key('pm_bands'))
        cfg['percentile_lines']=st.checkbox('Линии процентилей на кроссплоте',False,key=key('pm_percentile_lines'))
        cfg['outliers']=st.checkbox('Показывать выбросы на ящиках с усами',True,key=key('pm_outliers'))
    def axes_block():
        cfg['axes']={}
        for axis in ('x','y'):
            if axis+'_range' in default.get('axes',{}) and key('pm_axis_'+axis) not in st.session_state:
                st.session_state[key('pm_axis_'+axis)]=True
                st.session_state[key('pm_'+axis+'_min')]=float(default['axes'][axis+'_range'][0]);st.session_state[key('pm_'+axis+'_max')]=float(default['axes'][axis+'_range'][1]);st.session_state[key('pm_'+axis+'_step')]=float(default['axes'].get(axis+'_dtick',10))
            fixed=st.checkbox('Задать ось '+axis.upper(),key=key('pm_axis_'+axis))
            if fixed:
                a,b,c=st.columns(3);lo=a.number_input(axis.upper()+' min',value=0.,key=key('pm_'+axis+'_min'));hi=b.number_input(axis.upper()+' max',value=150.,key=key('pm_'+axis+'_max'));step=c.number_input(axis.upper()+' шаг',min_value=.001,value=10.,key=key('pm_'+axis+'_step'))
                if hi>lo:cfg['axes'][axis+'_range']=[lo,hi];cfg['axes'][axis+'_dtick']=step
                else:st.warning('Максимум оси должен быть больше минимума.')
    def object_block():
        cfg['object_groups']={}
        for obj in all_objects:
            widget=key('pm_object_group_'+obj)
            if widget not in st.session_state:st.session_state[widget]=default.get('object_groups',{}).get(obj,'Без категории')
            cfg['object_groups'][obj]=st.text_input('Категория · '+obj,key=widget,help='Например: ПХГ или месторождение. Произвольное название.')
    if bar:
        if slots is not None:slots.update(save=save_slot,export=export_slot,group=group_slot)
        with calc.popover('Расчет',use_container_width=True):calc_block()
        with view.popover('График',use_container_width=True):view_block()
        with axes_slot.popover('Оси',use_container_width=True):axes_block()
        with cats.popover('Категории',use_container_width=True):object_block()
    else:
        calc_block();view_block()
        with st.expander('Категории объектов (как группы файлов в скрипте)'):object_block()
        with st.expander('Границы и шаг осей'):axes_block()
    if compact:
        cfg['split']=st.selectbox('Построение при экспорте',['all','well','group'],format_func=lambda x:{'all':'Все выбранные вместе','well':'Отдельно по скважинам','group':'Отдельно по группам'}[x],key=key('pm_export_split'))
        cfg['charts']=checklist('Графики кроссплота для выгрузки',list(pm.LABELS),list(pm.LABELS),key('pm_charts'),lambda n:pm.LABELS[n])
    return cfg

SCREEN_POINTS=30000
PER_WELL=('time','error_time','box')
_FILTERED=OrderedDict()

def filtered(source,manifest,mapping,cfg):
    """Filtering millions of pairs takes seconds; reruns that change nothing (tabs, popovers) reuse the result."""
    key=(manifest.get('snapshot'),manifest.get('name'),len(source),manifest['revision'],json.dumps([manifest['settings'].get('season_start'),manifest['settings'].get('season_end'),cfg,{w:mapping.get(w,{}).get('group') for w in source.well.unique()}],sort_keys=True,default=str))
    if key not in _FILTERED:
        _FILTERED[key]=pm.filter_data(source,manifest['settings'],mapping,cfg)
        while len(_FILTERED)>3:_FILTERED.popitem(last=False)
    _FILTERED.move_to_end(key)
    return _FILTERED[key]

TABS={'Кроссплот':['cross'],'Динамика':['time','error_time'],'Распределения':['overall_box','box','fond_box','hist','cdf'],'Объекты':['object_box','percentiles']}
SUMMARY_COLUMNS=['object','scenario','Точек','Среднее отклонение','RMSE','Смещение модели','В пределах порога, %']
SUMMARY_NAMES={'object':'Объект','scenario':'Сценарий','Точек':'Точек','Среднее отклонение':'Средн. |ΔP|','RMSE':'RMSE','Смещение модели':'Смещение','В пределах порога, %':'В пороге, %'}

def scenario_summary(d,cfg):
    rows=[{'object':o,'scenario':s,**pm.statistics(g,cfg['percentiles'])} for (o,s),g in d.groupby(['object','scenario'],sort=False)]
    return pd.DataFrame(rows)[SUMMARY_COLUMNS].rename(columns=SUMMARY_NAMES).round(2)

def render(store,pid,manifest,frames,raw_frames,mapping,controls,key,style,viewer,quick_download):
    import_panel(store,pid,manifest,raw_frames,key)
    if 'pressure_match' not in frames:
        st.info('Загрузите книгу с листами «Факт», «Модель», «Фонд» либо отдельные файлы факта и моделей.');return
    raw=raw_frames['pressure_match'];source=frames['pressure_match']
    with filter_bar():
        slots={};cfg=options(raw,mapping,key,default=manifest['settings'].get('panels',{}).get('pressure_match',{}),bar=True,slots=slots)
        if slots['save'].button('Сохранить',key=key('pm_save'),help='Запомнить текущие фильтры и параметры в проекте.',use_container_width=True):
            settings={**manifest['settings'],'panels':{**manifest['settings'].get('panels',{}),'pressure_match':cfg}}
            store.commit(pid,settings=settings,expected=manifest['revision'],action='Параметры кроссплота');st.rerun()
        def to_export():
            for name in list(st.session_state):
                if name.startswith(key('exp_pressure_')):st.session_state.pop(name,None)
            st.session_state[key('exp_modules')]=['pressure_match'];st.session_state[key('exp_focus_module')]='pressure_match'
            from app.core.config import MODULES
            for module in MODULES:st.session_state[key('exp_'+module+'_enabled')]=module=='pressure_match'
            st.session_state['next_nav']='Экспорт'
        slots['export'].button('Экспорт',on_click=to_export,key=key('pm_to_export'),help='Перенести фильтры и параметры в раздел «Экспорт».',use_container_width=True)
        with slots['group'].popover('Группы',use_container_width=True):
            wells=st.text_input('Номера скважин через запятую',key=key('pm_bulk_wells'));group=st.text_input('Название группы',key=key('pm_bulk_group'))
            if st.button('Назначить группу',disabled=not wells.strip() or not group.strip(),key=key('pm_bulk_apply')):
                selected=parse_wells(wells);unknown=set(selected)-set(raw.well)
                if unknown:st.error('Не найдены: '+', '.join(ordered(unknown)))
                else:
                    groups={w:dict(v) for w,v in manifest['groups'].items()}
                    for w in selected:groups.setdefault(w,{})['group']=group.strip()
                    store.commit(pid,groups=groups,expected=manifest['revision'],action='Группы кроссплота');st.rerun()
    viewer['pressure_match']=cfg
    d,diagnostics=filtered(source,manifest,mapping,cfg)
    stats=pm.statistics(d,cfg['percentiles']);cols=st.columns(4)
    for col,(label,value) in zip(cols,[('Сопоставленных точек',stats.get('Точек',0)),('Средняя |ΔP|',stats.get('Среднее отклонение',np.nan)),('RMSE',stats.get('RMSE',np.nan)),('В пределах порога, %',stats.get('В пределах порога, %',np.nan))]):col.metric(label,str(value) if isinstance(value,int) else f'{value:.2f}' if np.isfinite(value) else '—')
    st.caption('Пропущено неполных пар: '+str(diagnostics.get('missing',0))+'; нулевых: '+str(diagnostics.get('zeros',0))+'; отрицательных: '+str(diagnostics.get('negative',0))+'. Последние 3 года: с '+diagnostics.get('recent_start','—')+'.')
    if d.empty:st.info('Нет пар после выбранных фильтров. Расширьте объекты, сценарии, период или снимите «Последние 3 года».');return
    bar=st.columns([3,2,1.3]);tab=bar[0].radio('Представление',list(TABS)+['Статистика'],horizontal=True,key=key('pm_tab'),label_visibility='collapsed')
    scope=bar[1].selectbox('Область графиков',['Все выбранные']+['№ '+w for w in ordered(d.well)]+['Группа '+g for g in ordered(d.group)],key=key('pm_scope'),label_visibility='collapsed',help='Ограничить графики одной скважиной или группой.')
    many=d.well.nunique()>12 and tab in ('Динамика','Распределения')
    well_limit=bar[2].selectbox('Скважин на графике',[12,24,48,96,'Все'],index=1,key=key('pm_well_limit'),label_visibility='collapsed',help='Графики по скважинам при большом числе скважин становятся нечитаемыми и медленными.') if many else 'Все'
    if tab=='Статистика':
        results=pm.tables(d,cfg)
        for name in ('Сводная объектов','Общая статистика','По скважинам','По фондам','По сезонам','Последние 3 года','По группам'):
            with st.expander(name,expanded=name=='Сводная объектов'):st.dataframe(results[name],hide_index=True,use_container_width=True)
    else:
        chosen=d[d.well.eq(scope[2:])] if scope.startswith('№ ') else d[d.group.eq(scope[7:])] if scope.startswith('Группа ') else d
        names=TABS[tab];screen=dict(cfg,screen_limit=SCREEN_POINTS)
        def draw(name):
            view=chosen
            if name in PER_WELL and well_limit!='Все' and chosen.well.nunique()>well_limit:
                view=chosen[chosen.well.isin(ordered(chosen.well)[:well_limit])]
                st.caption('Показано '+str(well_limit)+' из '+str(chosen.well.nunique())+' скважин. Увеличьте число в списке справа или выберите область графиков.')
            fig=charts.style_figure(pm.figure(view,name,screen),style,copy_figure=False);controls.plot(fig,key('pm_plot_'+name),allow_edit=name=='cross',copy_figure=False);quick_download(fig,'Кроссплот_'+name)
        if tab=='Кроссплот':
            left,right=st.columns([3,2])
            with left:draw('cross')
            with right:
                st.markdown('**Сводка по сценариям**');st.dataframe(scenario_summary(chosen,cfg),hide_index=True,use_container_width=True)
                st.caption('Объектов: '+str(chosen.object.nunique())+' · скважин: '+str(chosen.well.nunique())+'. Порог: '+('±{:g} {}'.format(cfg['threshold'],'%' if cfg['threshold_mode']=='relative' else cfg['unit']))+'.')
        else:
            for name in paginate(names,'Графики кроссплота',key('pm_graph_page_'+tab),size=2,format_func=lambda n:pm.LABELS[n]):draw(name)
    st.caption('Абсолютные ошибки и процентили рассчитаны по |модель − факт|. Стандартное отклонение — ddof=0. Совпадение по порогу учитывает выбранные < / ≤; IQR-выбросы не исключаются из статистики автоматически.')
    exp=st.columns([1.5,1.5,3])
    if exp[0].button('Подготовить Excel-отчет',key=key('pm_xlsx_prepare')):
        content=workbook_bytes(pm.tables(d,cfg),cfg);path=store.save_export(pid,'Кроссплот_давлений.xlsx',content,{'options':cfg});st.session_state[key('pm_xlsx_ready')]=(json.dumps([manifest['revision'],cfg],sort_keys=True),str(path))
    ready=st.session_state.get(key('pm_xlsx_ready'))
    if ready and ready[0]==json.dumps([manifest['revision'],cfg],sort_keys=True) and Path(ready[1]).exists():
        with Path(ready[1]).open('rb') as f:exp[1].download_button('Скачать Excel-отчет',f,Path(ready[1]).name,key=key('pm_xlsx_download'))
    controls.tools('pressure_match',raw,suffix='сопоставление давлений')
