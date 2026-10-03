"""Data import page: a simple mode (drop files, review one table) and the detailed per-sheet editor.

The simple mode classifies every sheet automatically, lists all sheets of all files in one table
and only opens the detailed editor for a sheet when the user asks for it.
"""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
import pandas as pd
import streamlit as st
from app.core.config import MODULES
from app.core.export import csv_bytes
from app.core.logging_utils import show_error
from app.core import profiles
from app.core.loader import load_file,merge_frames,detect_layout
from app.core.templates import input_templates
from app.core.well_import import REQUIRED
from app.ui.import_editor import file_editor,parse_pressure_book,samples,sheet_editor,text_options,FIELDS,MODULE_CHOICES

from app.core.import_rules import TYPES,TEXT_TYPES,PRESSURE_WORDS,PSI_TO_KGF,type_label,is_pressure_book,auto_spec,describe,to_kgf,merge_import

def simple_options(incoming,mode,key):
    """One table for all sheets of all files. Returns (options per file index, problems)."""
    state=st.session_state.setdefault(key('gi_state'),{'choices':{},'overrides':{},'text':{}})
    choices,overrides,text=state['choices'],state['overrides'],state['text']
    rows=[];problems=[];info={}
    for i,(name,content) in enumerate(incoming):
        sha=hashlib.sha256(content+name.encode()).hexdigest();encoding,delimiter=text.get(sha,('auto','auto'))
        try:fmt,tables=samples(content,name,encoding,delimiter)
        except Exception as error:problems.append(name+': '+str(error));continue
        if mode=='auto' and is_pressure_book(tables):
            rows.append({'Исп.':False,'Файл':name,'Лист':'(вся книга)','Тип данных':'Книга давлений','Распознанные поля':'','Статус':'Это книга факта и моделей давлений: загрузите ее на вкладке «Кроссплот давлений»','_i':i,'_sha':sha,'_auto':None});continue
        for sheet,raw in tables.items():
            if sheet=='Инструкция':continue
            found,fields=describe(raw,mode)
            remembered=profiles.find(raw,'general')
            if remembered and (sha,sheet) not in st.session_state[key('gi_state')]['overrides'] and (sha,sheet) not in choices:
                st.session_state[key('gi_state')]['overrides'][(sha,sheet)]=remembered
            c=choices.get((sha,sheet),{});chosen=c.get('module',found or 'unknown')
            use=c.get('use',found is not None);status='OK' if found else 'Таблица не распознана'
            if chosen!=found and chosen!='unknown':
                try:
                    forced=auto_spec(raw,chosen);fields=', '.join(FIELDS.get(f,f) for f in forced['mapping']) if not forced['wide'] else 'матрица: даты × скважины';status='OK'
                except ValueError as error:fields='';status='Не подходит: '+str(error)
            if (sha,sheet) in overrides:status='По сохраненному профилю' if profiles.find(raw,'general') else 'Настроено вручную'
            rows.append({'Исп.':bool(use),'Файл':name,'Лист':sheet,'Тип данных':type_label(chosen) if chosen!='unknown' else 'не распознан','Распознанные поля':fields,'Статус':status,'_i':i,'_sha':sha,'_auto':found,'_raw':raw})
        info[i]={'encoding':encoding,'delimiter':delimiter}
    return rows,problems,info,state

def render(store,pid,manifest,raw_frames,key,root,show_frame):
    revision=manifest['revision']

    view=st.radio('Режим импорта',['Простой (автоматически)','Подробный (по листам)'],horizontal=True,key=key('gi_view'),
        help='Простой: перетащите все файлы, программа определит тип каждого листа, проверка — в одной таблице. Подробный: ручная настройка шапки и колонок каждого листа.')
    simple=view.startswith('Простой')
    a,b,c,d,e=st.columns(5)
    mode=a.selectbox('Тип таблицы',['auto']+MODULE_CHOICES[1:],format_func=type_label,key=key('gi_mode'))
    kind=b.selectbox('Динамика без названия',['withdrawal','injection'],format_func=lambda v:'Отбор' if v=='withdrawal' else 'Закачка')
    punit=c.selectbox('Расходы динамики',['м³/сут','тыс. м³/сут'])
    gunit=d.selectbox('Q ГДИ без единиц',['тыс. м³/сут','м³/сут'])
    pressure_unit=e.selectbox('Единицы давлений',['кгс/см²','МПа'])
    st.caption('Давления внутри проекта: кгс/см². При выборе МПа пересчитываются давления, ΔP² и коэффициенты БД. Единицы Q в заголовке имеют приоритет; a и b БД считаются заданными для единиц Q исходного файла и пересчитываются вместе с ним.')
    generation=st.session_state.get(key('gi_generation'),0)
    files=st.file_uploader('Excel / CSV / TXT — можно сразу много файлов',type=TEXT_TYPES,accept_multiple_files=True,key=key('gi_files_'+str(generation)))
    with st.popover('Вставить таблицу из буфера'):
        pasted=st.text_area('Таблица с заголовками',height=140,key=key('gi_paste'))
    incoming=[(f.name,f.getvalue()) for f in files]
    if pasted.strip():incoming.append(('Вставленная_таблица.txt',pasted.encode('utf-8')))
    import_options={};editor_errors=[];blocked=False
    if simple and incoming:
        rows,problems,info,state=simple_options(incoming,mode,key)
        for message in problems:editor_errors.append(message);show_error(message)
        if rows:
            table=pd.DataFrame(rows);labels=[type_label(m) for m in MODULE_CHOICES[1:]]
            signature_rows=hashlib.sha256(json.dumps([[r['_sha'],r['Лист']] for r in rows]).encode()).hexdigest()[:10]
            count=st.columns(4)
            for col,(label,value) in zip(count,[('Файлов',len(incoming)),('Листов',len(rows)),('Будет загружено',sum(r['Исп.'] for r in rows)),('Не распознано',sum(r['Статус']=='Таблица не распознана' for r in rows))]):col.metric(label,value)
            edited=st.data_editor(table[['Исп.','Файл','Лист','Тип данных','Распознанные поля','Статус']],hide_index=True,use_container_width=True,height=min(560,45+35*len(table)),key=key('gi_table_'+signature_rows),
                disabled=['Файл','Лист','Распознанные поля','Статус'],
                column_config={'Исп.':st.column_config.CheckboxColumn('Исп.',width='small'),'Тип данных':st.column_config.SelectboxColumn('Тип данных',options=labels+['не распознан'],width='medium',help='Тип можно изменить: колонки будут сопоставлены заново'),
                    'Статус':st.column_config.TextColumn('Статус',width='large')})
            reverse={type_label(m):m for m in MODULE_CHOICES[1:]}
            for i,row in edited.reset_index(drop=True).iterrows():
                source=table.iloc[i];entry=state['choices'].setdefault((source['_sha'],source['Лист']),{})
                if bool(row['Исп.'])!=bool(source['Исп.']):entry['use']=bool(row['Исп.'])
                if row['Тип данных']!=source['Тип данных'] and row['Тип данных'] in reverse:entry['module']=reverse[row['Тип данных']];entry['use']=True
            sheets_by_file={}
            for i,row in edited.reset_index(drop=True).iterrows():
                source=table.iloc[i]
                if source['Лист']=='(вся книга)':sheets_by_file.setdefault(int(source['_i']),{});continue
                spec_key=(source['_sha'],source['Лист']);entry=state['choices'].get(spec_key,{});use=entry.get('use',bool(source['Исп.']))
                spec=state['overrides'].get(spec_key)
                module=entry.get('module',source['_auto'])
                sheets=sheets_by_file.setdefault(int(source['_i']),{})
                if not use:sheets[source['Лист']]={'enabled':False}
                elif spec is not None:sheets[source['Лист']]=spec
                elif module and module!=source['_auto']:
                    try:sheets[source['Лист']]=auto_spec(source['_raw'],module)
                    except ValueError as error:blocked=True;st.error(source['Файл']+' / '+source['Лист']+': '+str(error))
            for i,sheets in sheets_by_file.items():
                if not sheets and not any(r['_i']==i and r['Лист']!='(вся книга)' for r in rows):continue
                import_options[i]={'sheets':sheets,'encoding':info[i]['encoding'],'delimiter':info[i]['delimiter']}
            candidates=[(r['_i'],r['Файл'],r['Лист'],r['_sha']) for r in rows if r['Лист']!='(вся книга)']
            choice=st.selectbox('Нестандартный лист? Тонкая настройка шапки и колонок',[None]+candidates,format_func=lambda v:'— не нужна —' if v is None else v[1]+' · '+v[2],key=key('gi_fine'))
            if choice:
                i,name,sheet,sha=choice;content=incoming[i][1];raw=next(r['_raw'] for r in rows if r['_sha']==sha and r['Лист']==sheet)
                with st.container(border=True):
                    if not content.startswith((b'PK',b'\xd0\xcf\x11\xe0')):
                        enc,delim=text_options(content,name,key('gi_text_'+sha[:10]))
                        if (enc,delim)!=state['text'].get(sha,('auto','auto')):state['text'][sha]=(enc,delim);st.rerun()
                    spec=sheet_editor(raw,sheet,key('gi_fine_')+sha[:10]+sheet,mode)
                    if spec.get('enabled') and spec.get('valid',True):
                        state['overrides'][(sha,sheet)]=spec
                        if st.checkbox('Запомнить для файлов с такой же шапкой',value=profiles.find(raw,'general') is not None,key=key('gi_remember_'+sha[:10]+sheet),help='В следующий раз такая разметка применится автоматически.'):profiles.save(raw,spec,'general')
                        else:profiles.forget(raw,spec,'general')
                    else:state['overrides'].pop((sha,sheet),None)
                    if st.button('Вернуть автоматические настройки листа',key=key('gi_reset')):state['overrides'].pop((sha,sheet),None);st.rerun()
        blocked=blocked or bool(editor_errors) or not any(any(s.get('enabled',True) for s in o['sheets'].values()) or not o['sheets'] for o in import_options.values())
    elif incoming:
        if len(incoming)>6:st.info('Загружено много файлов. Для быстрой проверки в одной таблице переключитесь на «Простой» режим.')
        for i,(name,content) in enumerate(incoming):
            try:import_options[i]=file_editor(content,name,key('import_editor_'+str(i)),mode)
            except Exception as error:editor_errors.append(name+': '+str(error));show_error(editor_errors[-1])
        blocked=bool(editor_errors) or any(not spec.get('valid',True) for cfg in import_options.values() for spec in cfg['sheets'].values())
    signature=json.dumps([mode,kind,punit,gunit,pressure_unit,simple,[(name,hashlib.sha256(content).hexdigest()) for name,content in incoming],import_options],ensure_ascii=False,sort_keys=True,default=str)
    previous=st.session_state.get(key('pending'))
    if previous and previous.get('signature')!=signature:
        shutil.rmtree(previous['staging'],ignore_errors=True);st.session_state.pop(key('pending'),None)
    with st.expander('Шаблоны и примеры'):
        for filename,content in input_templates().items():st.download_button('Скачать '+filename,content,filename,key=key('xlsx_'+filename))
        st.caption('Давление объекта: ровно две колонки — Дата и Пластовое давление, кгс/см2. Выберите тип «Давление объекта» или автоопределение.')
        st.markdown('**Динамика:** Скважина, Дата, Расход. **ГДИ:** Скважина, Дата, Q, Рпл, Рзаб. **Реагирование:** Скважина, Дата, Горизонт, Уровень жидкости, Рпл привед.')
        st.caption('Также поддерживаются матрицы расходов: даты в первом столбце, скважины в первой строке. Группы: Скважина, Группа, Подгруппа.')
        for p in sorted((root/'examples').glob('*')):
            if p.suffix in ('.csv','.xlsx','.txt'):st.download_button(p.name,p.read_bytes(),p.name,key=key('template_'+p.name))
    if st.button('Проверить файлы',type='primary',disabled=not incoming or blocked):
        staging=Path(tempfile.mkdtemp(prefix='gas_atlas_import_'));parsed={};issues=[];originals=[];rejected=0;warnings_count=0
        status=st.empty();progress=st.progress(0.)
        for i,(name,content) in enumerate(incoming):
            if i not in import_options:progress.progress((i+1)/len(incoming));continue
            path=staging/str(i)/Path(name).name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            try:
                if import_options[i].get('pressure_book'):r=parse_pressure_book(content,name,import_options[i])
                else:r=load_file(path,mode,kind,punit,gunit,sheet_options=import_options[i]['sheets'],encoding=import_options[i]['encoding'],delimiter=import_options[i]['delimiter'],progress=lambda sh,n:status.info(name+' / '+sh+': обработано '+format(n,',')+' строк'))
                if pressure_unit=='МПа':to_kgf(r.frames)
                for module,frame in r.frames.items():parsed[module]=pd.concat([parsed[module],frame],ignore_index=True) if module in parsed else frame
                issues.extend(r.issues);rejected+=r.rejected;warnings_count+=r.warnings
                if r.frames:originals.append(str(path))
            except Exception as error:
                issues.append({'Файл':name,'Лист':'','Строка':0,'Уровень':'ошибка','Причина':str(error)});rejected+=1
            progress.progress((i+1)/len(incoming))
        status.empty();progress.empty()
        old=st.session_state.pop(key('pending'),None)
        if old:shutil.rmtree(old['staging'],ignore_errors=True)
        st.session_state[key('pending')]={'frames':parsed,'issues':issues,'rejected':rejected,'warnings':warnings_count,'originals':originals,'staging':str(staging),'signature':signature}
    import_status=st.session_state.pop(key('import_status'),None)
    if import_status:getattr(st,import_status[0])(import_status[1])
    pending=st.session_state.get(key('pending'))
    if not pending:return
    st.subheader('Результат проверки')
    st.write({MODULES.get(k,'Группы'):len(v) for k,v in pending['frames'].items()})
    if pending['issues']:
        st.warning('Отклоненных строк / файлов: '+str(pending['rejected'])+'. Предупреждений: '+str(pending['warnings'])+'. В журнале до 2000 замечаний на файл.')
        show_frame(pd.DataFrame(pending['issues']),200)
        st.download_button('Скачать журнал проверки',csv_bytes(pd.DataFrame(pending['issues'])),'import_issues.csv')
    for module,frame in pending['frames'].items():
        with st.expander(MODULES.get(module,'Группы')+' — предпросмотр'):show_frame(frame,30)
    policy=st.radio('Повторы и обновление',['new','old','replace'],format_func=lambda v:{'new':'Добавить, совпадения заменить новыми','old':'Добавить, совпадения оставить прежними','replace':'Заменить целиком только импортируемые модули'}[v])
    st.caption('Повтор ГДИ заменяет исследование целиком по скважине, дате, методу и номеру исследования. Расходы за одну дату не суммируются.')
    accepted=True if not pending['rejected'] else st.checkbox('Загрузить корректные строки, исключив перечисленные ошибки')
    def apply_import():
        try:
            updated,groups,duplicates=merge_import(raw_frames,manifest['groups'],pending['frames'],policy)
            originals=manifest.get('imports',[])+[store.keep_original(pid,p) for p in pending['originals']]
            store.commit(pid,updated,groups=groups,imports=originals,expected=revision,action='Импорт данных')
            store.event(pid,'Результат импорта',{'removed_duplicates':duplicates,'rejected':pending['rejected']})
            shutil.rmtree(pending['staging'],ignore_errors=True);del st.session_state[key('pending')]
            st.session_state[key('gi_generation')]=generation+1;st.session_state.pop(key('gi_state'),None)
            st.session_state[key('import_status')]=('success','Данные сохранены')
        except Exception as error:
            st.session_state[key('import_status')]=('error',str(error))
    st.button('Применить загрузку',type='primary',disabled=not pending['frames'] or not accepted,on_click=apply_import)
