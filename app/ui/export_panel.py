import datetime as dt
import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from pathlib import Path
from app.core import reporting
from app.core.config import MODULES,VERSION,ordered
from app.core.export import figure_bytes,decode_arrays
from app.core.logging_utils import show_error
from app.core.performance import Frames
from app.core.bulk_export import export_plan,export_word,bundle_exports
from app.core.documents import DEFAULT_CAPTIONS
from app.modules import production,gdi,well_charts
from app.ui.selection import checklist

@st.cache_data(show_spinner=False,max_entries=8)
def file_preview(figure_json,width):
    return figure_bytes(go.Figure(decode_arrays(json.loads(figure_json))),'png',150,width)


def migrate_preset(values):
    values=dict(values);modules=list(values.get('modules',[]))
    view=values.get('production_view')
    if view in ('hist','mixed'):
        if 'histograms' not in modules:modules.append('histograms')
        if view=='hist':modules=[m for m in modules if m!='production']
        for field in ('wells','groups','split','direction','histaxis','hist_size','groupmode','size','panels'):
            if 'production_'+field in values:values.setdefault('histograms_'+field,values['production_'+field])
        values['production_view']='curve'
    for kind in ('withdrawal','injection'):
        if 'periods_'+kind in values:
            values.setdefault('production_periods_'+kind,values['periods_'+kind]);values.setdefault('histograms_periods_'+kind,values['periods_'+kind])
    values['modules']=modules;return values


def render(store,pid,manifest,frames,raw_frames,mapping,viewer,point_controls,key):
    settings=manifest['settings'];revision=manifest['revision']
    def ek(name):return key('exp_'+name)
    current={**settings.get('panels',{}),**viewer}
    available=[m for m in ('production','histograms','gdi','response','object_pressure','well_dashboard','operations','water','bottom','construction','pressure_match') if (m=='histograms' and 'production' in raw_frames) or (m=='well_dashboard' and any(k!='object_pressure' for k in raw_frames)) or m in raw_frames]
    default_modules=st.session_state.get(ek('modules'),[m for m in ('production','gdi','response','object_pressure') if m in raw_frames])
    presets=settings.get('export_presets',{})
    with st.expander('Шаблоны параметров экспорта'):
        preset_name=st.text_input('Название шаблона',key=ek('preset_name'))
        chosen_preset=st.selectbox('Сохраненный шаблон',['']+list(presets),key=ek('preset_choice'))
        if st.button('Загрузить шаблон',disabled=not chosen_preset):
            loaded=migrate_preset(presets[chosen_preset])
            for field,value in loaded.items():
                st.session_state[ek(field)]=tuple(pd.Timestamp(v).date() for v in value) if field.endswith('_dates') else pd.Timestamp(value).date() if field.endswith('_asof') and value else value
            for module in available:st.session_state[ek(module+'_enabled')]=module in loaded.get('modules',default_modules)
            default_modules=loaded.get('modules',default_modules)
        if st.button('Сохранить шаблон экспорта',disabled=not preset_name.strip()):
            import copy
            cfg=copy.deepcopy(settings);prefix=ek('');values={}
            for state_key in st.session_state:
                if state_key.startswith(prefix):
                    field=state_key[len(prefix):]
                    if field in ('modules','formats','dpi','width','exclusions','raw','auto') or field.startswith(('production_','histograms_','gdi_','response_','dashboard_','pressure_','periods_','caption_','style_')):
                        value=st.session_state[state_key]
                        if isinstance(value,(str,int,float,bool,list,tuple,dict)) and not field.endswith('__checklist'):
                            try:values[field]=json.loads(json.dumps(value,default=str))
                            except (TypeError,ValueError):pass
            cfg.setdefault('export_presets',{})[preset_name.strip()]=values
            store.commit(pid,settings=cfg,expected=revision,action='Шаблон экспорта');st.rerun()
    if st.button('Взять параметры из вкладок просмотра',key=ek('sync')):
        for module in ('gdi','response','well_dashboard','pressure_match'):
            cfg=current.get(module,{})
            if module=='well_dashboard':
                for field in ('n','orientation','curves','db','crosshair','excluded','seasons'):st.session_state.pop(ek('dashboard_gdi_'+field),None)
            if module=='pressure_match':
                for name in list(st.session_state):
                    if name.startswith(ek('pressure_')):st.session_state.pop(name,None)
                continue
            for field,value in cfg.items():
                target='dashboard' if module=='well_dashboard' else module
                st.session_state[ek(target+'_'+field)]=tuple(pd.Timestamp(v).date() for v in value) if field=='dates' else value
        for module,panel in [('production','prod_0'),('histograms','hist_0')]:
            cfg=current.get('group_totals' if module=='production' and st.session_state.get(key('prod_mode'))=='groups' else panel,{})
            for field,value in cfg.items():
                if field=='periods' and isinstance(value,dict):
                    for kind,chosen in value.items():st.session_state[ek(module+'_periods_'+kind)]=chosen
                elif field=='periods' and isinstance(value,list):st.session_state[ek(module+'_periods_'+cfg.get('kind','withdrawal'))]=value
                else:st.session_state[ek(module+'_'+field)]=value
        for field,value in current.get('style',{}).items():st.session_state[ek('style_'+field)]=value
        st.success('Параметры просмотра перенесены.')
    with st.expander('Общие параметры файлов',expanded=True):
        a,b,c=st.columns(3)
        formats=a.multiselect('Форматы графиков',['svg','pdf','png'],default=['svg','pdf'],key=ek('formats'))
        dpi=b.selectbox('Разрешение PNG',[300,600,1200],key=ek('dpi'))
        width=c.number_input('Ширина, мм',80,300,220,key=ek('width'))
        apply_exclusions=st.checkbox('Применять исключения точек проекта',True,key=ek('exclusions'))
        raw=st.checkbox('Добавить нормализованные данные',False,key=ek('raw'))
        style={};columns=st.columns(3)
        for container,(field,label) in zip(columns,[('points','Экспорт: точки'),('legend','Экспорт: легенда'),('grid','Экспорт: сетка')]):style[field]=container.checkbox(label,settings.get('chart_style',{}).get(field,True),key=ek('style_'+field))
    source=frames if apply_exclusions else Frames(raw_frames.project,{**settings,'excluded_points':{}},st.session_state.get('fast_mode',True)) if hasattr(raw_frames,'project') else raw_frames
    allw=ordered(raw_frames.project.catalog()['wells']) if hasattr(raw_frames,'project') else ordered(w for d in raw_frames.values() if 'well' in d for w in d.well.unique())
    options={'modules':[],'wells':[],'raw':raw,'apply_exclusions':apply_exclusions,'style':style};mods=[];selected=set()
    def choices(module):
        real='production' if module=='histograms' else module
        if real=='well_dashboard':return allw
        return ordered(raw_frames.project.catalog()['modules'][real]['wells']) if hasattr(raw_frames,'project') else ordered(raw_frames[real].well)
    def module_wells(module):
        wells=choices(module);groups=ordered(mapping.get(w,{}).get('group','Без группы') for w in wells)
        a,b=st.columns(2)
        with a:gs=checklist(MODULES[module]+': группы',groups,groups,ek(module+'_groups'))
        wells=[w for w in wells if mapping.get(w,{}).get('group','Без группы') in gs]
        with b:ws=checklist(MODULES[module]+': скважины',wells,wells,ek(('dashboard' if module=='well_dashboard' else module)+'_wells'),lambda x:'№ '+x)
        return ws,gs
    dashboard_gdi=st.session_state.get(ek('dashboard_gdi'),current.get('well_dashboard',{}).get('gdi',{}))
    for name,field in [('n','n'),('orientation','orientation'),('curves','curves'),('db','db_curves'),('crosshair','crosshair'),('excluded','show_excluded'),('seasons','seasons')]:
        if field in dashboard_gdi:st.session_state.setdefault(ek('dashboard_gdi_'+name),dashboard_gdi[field])
    focus=st.session_state.get(ek('focus_module'))
    if focus in available:available=[focus]+[m for m in available if m!=focus]  # tab opened from a viewer page comes first
    tabs=st.tabs([MODULES[m] for m in available]) if available else []
    for module,tab in zip(available,tabs):
        with tab:
            enabled=st.checkbox('Включить '+MODULES[module]+' в выгрузку',value=module in default_modules,key=ek(module+'_enabled'))
            if not enabled:st.caption('Включите модуль для выбора графиков и таблиц.');continue
            mods.append(module)
            if module=='object_pressure':options[module]={};continue
            if module=='pressure_match':
                from app.ui.pressure_panel import options as pressure_options
                cfg=pressure_options(raw_frames[module],mapping,lambda name:ek('pressure_'+name),compact=True,default=current.get(module,{}))
                options[module]=cfg;selected.update(cfg['wells']);continue
            ws,gs=module_wells(module);selected.update(ws);cfg={'wells':ws,'groups':gs}
            if module in ('production','histograms'):
                d=source['production'];periods={};cols=st.columns(2)
                for col,(kind,label) in zip(cols,[('withdrawal','Отбор'),('injection','Закачка')]):
                    values=ordered(d.loc[d.kind.eq(kind),'period'])
                    with col:periods[kind]=checklist(label+' — периоды',values,values,ek(module+'_periods_'+kind))
                a,b=st.columns(2)
                view='hist' if module=='histograms' else a.selectbox('Производительность: вид графика',['curve','time'],key=ek('production_view'),format_func=lambda x:'Q / накопленный объем' if x=='curve' else 'Q / дата')
                split=b.selectbox(MODULES[module]+': построение',['well','group','subgroup','all']+(['group_total'] if module=='production' else []),key=ek(module+'_split'),format_func=lambda x:{'well':'По скважинам','group':'По группам (отдельные кривые)','subgroup':'По подгруппам','all':'Все выбранные вместе','group_total':'Сумма по каждой группе + скважины'}[x])
                direction=st.selectbox(MODULES[module]+': порядок',['number','desc','asc'],key=ek(module+'_direction'),format_func=lambda x:{'number':'По номеру','desc':'Больший дебит слева','asc':'Больший дебит справа'}[x])
                cfg.update(periods=periods,view=view,split=split,direction=direction)
                panel_prefix='hist' if module=='histograms' else 'prod'
                both=st.checkbox('Экспортировать обе панели · '+MODULES[module],False,key=ek(module+'_panels'),disabled=not current.get(panel_prefix+'_1'))
                if both:
                    cfg['panels']=[{**cfg,'panels':None,'wells':v.get('wells',ws),'periods':{v['kind']:v['periods']},'view':v.get('view',view),'direction':v.get('direction',direction),'histaxis':v.get('histaxis','well'),'hist_size':v.get('hist_size','Авто'),'split':'all'} for v in [current.get(panel_prefix+'_0'),current.get(panel_prefix+'_1')] if v]
                if split=='group_total':
                    cfg['metric']=st.selectbox('Суммарный показатель',['daily','cumulative','active'],key=ek('production_metric'),format_func=lambda x:{'daily':'Суточный расход','cumulative':'Накопленный объем','active':'Работающие скважины'}[x])
                    cfg['overlay']=checklist('Наложение скважин',ws,[],ek('production_overlay'),lambda x:'№ '+x)
                    st.caption('Сумма включает весь состав группы; список наложения меняет только отдельные кривые.')
                if split=='subgroup':
                    cfg['group_mode']=st.selectbox('Подгруппы',['manual','auto'],key=ek(module+'_groupmode'))
                    cfg['size']=st.number_input('Скважин на график подгруппы',1,30,8,key=ek(module+'_size'))
                if module=='histograms':
                    cfg['histaxis']=st.selectbox('Ось гистограммы',['well','period'],key=ek('histograms_histaxis'),format_func=lambda x:'Скважины' if x=='well' else 'Периоды')
                    cfg['hist_size']=st.selectbox('Скважин на одной гистограмме',['Авто','10','20','50','Все'],key=ek('histograms_hist_size'))
            elif module=='gdi':
                a,b=st.columns(2);cfg['n']=a.selectbox('ГДИ: последние даты',[1,2,3,0],index=2,key=ek('gdi_n'),format_func=lambda x:'Все' if x==0 else str(x))
                cfg['orientation']=b.selectbox('ГДИ: оси',['standard','swapped'],key=ek('gdi_orientation'),format_func=lambda x:'X = Q, Y = ΔP²' if x=='standard' else 'X = ΔP², Y = Q')
                a,b,c=st.columns(3);cfg['curves']=a.checkbox('ГДИ: расчетные кривые',True,key=ek('gdi_curves'));cfg['db_curves']=b.checkbox('ГДИ: кривые по коэффициентам БД',True,key=ek('gdi_db_curves'));cfg['crosshair']=c.checkbox('ГДИ: перекрестная линейка',True,key=ek('gdi_crosshair'))
                cfg['show_excluded']=st.checkbox('ГДИ: показывать исключенные точки',True,key=ek('gdi_show_excluded'))
                data=source['gdi'];seasons=ordered(data.season[data.season.ne('')]) if 'season' in data else []
                cfg['seasons']=checklist('ГДИ: сезоны (пусто — все)',seasons,[],ek('gdi_seasons')) if seasons else []
            elif module=='response':
                data=source['response'];hs=ordered(data.horizon);a,b=st.columns(2)
                with a:cfg['horizons']=checklist('Горизонты',hs,hs,ek('response_horizons'))
                with b:cfg['working']=checklist('Рабочие горизонты',hs,[h for h in settings.get('working_horizons',[]) if h in hs],ek('response_working'))
                dates=st.date_input('Реагирование: период',(data.date.min().date(),data.date.max().date()),key=ek('response_dates'));cfg['dates']=[str(v) for v in dates]
                a,b=st.columns(2);cfg['view']=a.selectbox('Реагирование: вид графиков',['separate','combined','level','pressure'],key=ek('response_view'),format_func=lambda x:{'separate':'Уровень и давление отдельно','combined':'Уровень + давление','level':'Только уровень','pressure':'Только давление'}[x])
                cfg['split']=b.selectbox('Реагирование: построение',['horizon','all','well'],key=ek('response_split'),format_func=lambda x:{'horizon':'По горизонтам','all':'Все вместе','well':'По скважинам'}[x])
            elif module=='well_dashboard':
                from app.modules import well_analysis
                kind=st.selectbox('Анализ: режим',['withdrawal','injection'],format_func=lambda x:'Отбор' if x=='withdrawal' else 'Закачка',key=ek('dashboard_kind'))
                daily=well_analysis.dataset(source,settings,mapping)['daily'];periods=ordered(daily.loc[daily.kind.eq(kind),'period']) if not daily.empty else []
                cfg.update(kind=kind,periods=checklist('Анализ: периоды (пусто — все)',periods,[],ek('dashboard_periods')) or None)
                methods=ordered(source['gdi'].method) if 'gdi' in source else []
                cfg['method']=st.selectbox('Анализ: метод ГДИ',[None]+methods,format_func=lambda x:'Все методы' if x is None else x or 'Без метода',key=ek('dashboard_method'))
                fixed=st.checkbox('Анализ: общий ΔP² вручную',False,key=ek('dashboard_fixed'));cfg['delta']=st.number_input('Анализ: общий ΔP²',min_value=.001,value=500.,step=10.,key=ek('dashboard_delta')) if fixed else None
                latest=max((info['end'] for info in raw_frames.project.catalog()['modules'].values() if pd.notna(info.get('end'))),default=pd.Timestamp.today()) if hasattr(raw_frames,'project') else pd.Timestamp.today()
                if isinstance(st.session_state.get(ek('dashboard_asof')),str):st.session_state[ek('dashboard_asof')]=pd.Timestamp(st.session_state[ek('dashboard_asof')]).date()
                cfg['asof']=str(st.date_input('Анализ: дата состояния',value=pd.Timestamp(latest).date(),key=ek('dashboard_asof')))
                cfg['threshold']=st.number_input('Анализ: порог изменения, %',1.,80.,10.,key=ek('dashboard_threshold'))
                cfg['alignment']=st.selectbox('Анализ: начало отсчета сезонов',['well','object'],format_func=lambda x:'Первый замер скважины = 0' if x=='well' else 'Первый день данных объекта',key=ek('dashboard_alignment'))
                with st.expander('Анализ: настройки графика ГДИ'):
                    a,b=st.columns(2);gn=a.selectbox('Анализ: последние даты ГДИ',[0,1,2,3],key=ek('dashboard_gdi_n'),format_func=lambda x:'Все' if x==0 else str(x));orientation=b.selectbox('Анализ: оси ГДИ',['standard','swapped'],key=ek('dashboard_gdi_orientation'))
                    a,b,c=st.columns(3);curves=a.checkbox('Анализ: расчетные кривые',True,key=ek('dashboard_gdi_curves'));db=b.checkbox('Анализ: кривые БД',True,key=ek('dashboard_gdi_db'));cross=c.checkbox('Анализ: линейка',True,key=ek('dashboard_gdi_crosshair'))
                    show=st.checkbox('Анализ: исключенные точки ГДИ',True,key=ek('dashboard_gdi_excluded'))
                    seasons=ordered(source['gdi'].season[source['gdi'].season.ne('')]) if 'gdi' in source and 'season' in source['gdi'] else []
                    selected_seasons=checklist('Анализ: сезоны ГДИ',seasons,[],ek('dashboard_gdi_seasons')) if seasons else []
                    cfg['gdi']={'n':gn,'orientation':orientation,'curves':curves,'db_curves':db,'crosshair':cross,'show_excluded':show,'seasons':selected_seasons}
                cfg['charts']=checklist('Анализ: графики',list(well_charts.LABELS),list(well_charts.LABELS),ek('dashboard_charts'),lambda x:well_charts.LABELS[x])
            options[module]=cfg
    options['modules']=mods;options['wells']=ordered(selected);ws=options['wells'];st.session_state[ek('modules')]=mods
    caption_config={}
    with st.expander('Word: подписи под графиками'):
        st.caption('Таблица в две колонки. Доступные поля: {раздел}, {номер}, {скважина}, {горизонт}, {период}, {модуль}. Нумерация идет отдельно внутри каждого модуля.')
        for module in mods:
            default=DEFAULT_CAPTIONS.get(module,DEFAULT_CAPTIONS['well_dashboard']);st.markdown('**'+MODULES[module]+'**')
            a,b=st.columns(2)
            section=a.text_input('Раздел · '+MODULES[module],default['section'],key=ek('caption_section_'+module))
            start=b.number_input('Первый номер · '+MODULES[module],1,10000,default['start'],key=ek('caption_start_'+module))
            template=st.text_input('Шаблон подписи · '+MODULES[module],default['template'],max_chars=500,key=ek('caption_template_'+module))
            caption_config[module]={'section':section,'start':start,'template':template}
    signature=json.dumps([revision,options,formats,dpi,width],ensure_ascii=False,sort_keys=True)
    auto=st.checkbox('Автоматически обновлять предпросмотр',False,key=ek('auto'))
    a,b,c=st.columns(3)
    preview=a.button('Предпросмотр',key=ek('preview'),disabled=not mods or (not ws and 'object_pressure' not in mods))
    generate=b.button('Сформировать архив',key=ek('generate'),type='primary',disabled=not mods or (not ws and 'object_pressure' not in mods))
    word=c.button('Создать отчет Word',key=ek('word'),disabled=not mods or (not ws and 'object_pressure' not in mods))
    word_signature=signature+json.dumps(caption_config,sort_keys=True,ensure_ascii=False)
    prepared=st.session_state.get(ek('report'))
    if (auto or preview or generate or word) and (not prepared or prepared[0]!=signature) and mods and (ws or 'object_pressure' in mods):
        try:
            with st.spinner('Подготовка перечня графиков и расчетных таблиц…'):
                prepared=(signature,reporting.plan(source,mapping,settings,options,raw_frames))
            st.session_state[ek('report')]=prepared
        except Exception as error:
            show_error('Не удалось подготовить экспорт: '+str(error));prepared=None
    if preview:st.session_state[ek('show_preview')]=True
    if prepared and prepared[0]==signature:
        plan=prepared[1]
        st.subheader('Состав выгрузки')
        st.caption(f'Графиков: {len(plan.jobs)}; таблиц: {len(plan.tables)}. Предпросмотр строит только выбранный график. При массовом экспорте остальные строятся последовательно; каждый модуль сохраняется в один общий архив или документ без разбиения.')
        if plan.jobs and st.session_state.get(ek('show_preview'),False):
            labels=[j.name for j in plan.jobs];preview_key=ek('preview_chart')
            if st.session_state.get(preview_key) not in labels:st.session_state[preview_key]=labels[0]
            chosen=st.selectbox('График предпросмотра',labels,key=preview_key)
            try:
                fig=plan.figures()[chosen]
                file_tab,interactive_tab=st.tabs(['Макет файла','Интерактивный предпросмотр'])
                with file_tab:
                    st.caption('Макет статического файла при выбранной ширине. Для предпросмотра используется 150 DPI.')
                    st.image(file_preview(fig.to_json(),width),use_container_width=True)
                with interactive_tab:point_controls.plot(fig,ek('preview_plot'),None,allow_edit=apply_exclusions)
                module=next((t.meta.get('module') for t in fig.data if isinstance(t.meta,dict) and t.meta.get('module')),None)
                if module in raw_frames and apply_exclusions:
                    cfg=options.get(module,{});subset=raw_frames[module]
                    if 'well' in subset:subset=subset[subset.well.isin(ws)&subset.well.isin(cfg.get('wells',ws))]
                    if module=='gdi':subset=gdi.select_studies(subset,cfg.get('wells',ws),cfg.get('n',3),cfg.get('seasons'))
                    elif module=='response':
                        subset=subset[subset.horizon.isin(cfg.get('horizons',ordered(subset.horizon)))]
                        if len(cfg.get('dates',[]))==2:subset=subset[subset.date.between(pd.Timestamp(cfg['dates'][0]),pd.Timestamp(cfg['dates'][1]))]
                    point_controls.tools(module,subset,suffix='предпросмотр экспорта')
            except Exception as error:show_error('Не удалось отобразить этот график: '+str(error))
        elif not plan.jobs:st.info('Нет графиков в этом выборе; расчетные таблицы доступны для экспорта.')
        metadata={'project':manifest['name'],'version':VERSION,'revision':revision,'options':options,'settings':settings,
            'formats':formats,'dpi':dpi,'width_mm':width,'created_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
        def progress(value,text):bar.progress(float(value),text=text)
        if word:
            try:
                bar=st.progress(0.,text='Создание Word-отчета…')
                result=export_word(plan,store,pid,manifest['name'],caption_config,{**metadata,'captions':caption_config},progress)
                st.session_state[ek('word_ready')]=(word_signature,result);bar.empty()
            except Exception as error:show_error('Word-отчет не завершен: '+str(error)+'. Уже сохраненные файлы доступны в разделе «Проекты».')
        if generate:
            try:
                bar=st.progress(0.,text='Создание архива…')
                result=export_plan(plan,store,pid,formats,dpi,width,metadata,progress)
                st.session_state[ek('archive')]=(signature,result);bar.empty();store.event(pid,'Экспорт',metadata)
            except Exception as error:show_error('Экспорт не завершен: '+str(error)+'. Уже сохраненные файлы доступны в разделе «Проекты».')
    ready_word=st.session_state.get(ek('word_ready'))
    if ready_word and ready_word[0]==word_signature:
        result=ready_word[1]
        if result.errors:st.warning('Word создан частично. Ошибок: '+str(len(result.errors))+'. Причины включены в документ соответствующего модуля.')
        else:st.success('Word: сохранено графиков '+str(result.completed)+'; документов '+str(len(result.paths)))
        result_download(result,'Скачать отчет Word',ek('word_part'))
    exported=st.session_state.get(ek('archive'))
    if exported and exported[0]==signature:
        result=exported[1]
        if result.errors:
            st.warning(f'Экспорт завершен частично: графиков {result.completed}/{result.planned}; ошибок {len(result.errors)}. Готовые файлы сохранены. Журнал export_errors.csv включен в архив соответствующего модуля.')
            st.dataframe(pd.DataFrame(result.errors),hide_index=True,use_container_width=True)
        else:st.success(f'Готово: {result.completed} графиков, {result.files} файлов графиков; единых архивов модулей: {len(result.paths)}. Таблицы и журнал включены в каждый архив.')
        result_download(result,'Скачать архив результатов',ek('archive_part'))

    ready=[]
    for value in (ready_word,exported):
        if value and value[0] in (signature,word_signature):ready.extend(value[1].paths)
    if ready:
        signature_files=json.dumps([str(p) for p in ready])
        combined=st.session_state.get(ek('all_ready'))
        if not combined or combined[0]!=signature_files or not Path(combined[1]).exists():
            with st.spinner('Объединение созданных файлов…'):
                combined=(signature_files,str(bundle_exports(store,pid,ready,{'version':VERSION})))
            st.session_state[ek('all_ready')]=combined
        if combined and combined[0]==signature_files and Path(combined[1]).exists():
            with Path(combined[1]).open('rb') as content:st.download_button('Скачать все созданные файлы одним ZIP',content,Path(combined[1]).name,key=ek('all_download'),type='primary')


@st.fragment
def result_download(result,label,state_key):
    paths=[Path(p) for p in result.paths]
    if not paths:st.info('Нет готовых файлов.');return
    choices=[str(p) for p in paths]
    if st.session_state.get(state_key) not in choices:st.session_state[state_key]=choices[0]
    selected=Path(st.selectbox('Файл для скачивания',choices,format_func=lambda x:Path(x).name,key=state_key)) if len(paths)>1 else paths[0]
    if len(paths)>1:st.caption('Для общего скачивания используйте кнопку ниже. Файлы также сохранены в разделе «Проекты».')
    if selected.exists():
        with selected.open('rb') as content:st.download_button(label,content,selected.name,key=state_key+'_download',type='primary')
    else:st.error('Сохраненный файл не найден. Сформируйте экспорт заново.')
