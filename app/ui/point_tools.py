"""Shared click-to-exclude handling and an auditable restoration screen."""
import copy
import datetime as dt
import uuid
import hashlib
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from app.ui.theme import chart_for_screen
from app.core import exclusions
from app.core.history import filter_details
from app.core.logging_utils import show_error
from app.core.config import MODULES
from app.core.export import csv_bytes

LABELS={'well':'Скважина','date':'Дата','kind':'Тип','horizon':'Горизонт','method':'Метод',
        'study':'Исследование','q':'Q','dp2':'ΔP²','level':'Уровень, м','pressure':'Рпл привед.',
        'file':'Файл','sheet':'Лист','_row':'Строка','reason':'Причина','excluded_utc':'Исключено (UTC)',
        'metric':'Показатель','module':'Модуль','work_hours':'Часы работы','gas_volume_m3':'Объем газа, м³',
        'water_volume_m3':'Объем воды, м³','water_rate':'Расход воды, м³/сут','water_flag':'Вода',
        'bottom_m':'Низ / забой, м','top_m':'Верх, м','tool_diameter_mm':'Диаметр шаблона, мм',
        'fact':'Фактическое давление','model':'Модельное давление','scenario':'Сценарий','object':'Объект','fond':'Фонд',
        'element':'Элемент','diameter_mm':'Наружный диаметр, мм','inner_diameter_mm':'Внутренний диаметр, мм','comment':'Комментарий'}

class PointControls:
    def __init__(self,store,pid,revision,settings,raw_frames,edit=False):
        self.store=store;self.pid=pid;self.revision=revision;self.settings=settings
        self.raw=raw_frames;self.edit=edit
    def key(self,name):return self.pid+'_points_'+name
    def notify(self):
        note=st.session_state.pop(self.key('note'),None)
        if note:getattr(st,note[0])(note[1])
    def change(self,added=None,removed=None):
        cfg=copy.deepcopy(self.settings);items=cfg.setdefault('excluded_points',{})
        added=added or [];removed=removed or []
        operation=uuid.uuid4().hex;stamp=dt.datetime.now(dt.timezone.utc).isoformat()
        for entry in added:
            if entry:items[entry['id']]={**entry,'batch':operation,'excluded_utc':stamp}
        for identifier in removed:items.pop(identifier,None)
        try:
            details=filter_details(self.raw,self.settings,cfg,added,removed)
            self.store.commit(self.pid,settings=cfg,expected=self.revision,action='Ручной фильтр точек',details=details)
            st.session_state[self.key('note')]=('success',f'Фильтр сохранен. Исключено: {len(items)}. Данные и кривые пересчитаны.')
        except Exception as error:st.session_state[self.key('note')]=('error',str(error))
    def plot(self,fig,key,module=None,allow_edit=True,copy_figure=True):
        fig=chart_for_screen(fig,copy_figure=copy_figure)
        module=module or next((t.meta.get('module') for t in fig.data if isinstance(t.meta,dict) and t.meta.get('module')),None)
        edit=self.edit and allow_edit and module is not None
        if edit:
            for trace in fig.data:
                if isinstance(trace.meta,dict) and trace.meta.get('module')=='production' and trace.mode=='lines':
                    trace.mode='lines+markers';trace.marker.size=6
        chart_key=key+'_rev'+str(self.revision)+('_edit' if edit else '_view')
        def selected():
            state=st.session_state.get(chart_key,{})
            points=state.get('selection',{}).get('points',[])
            entries=[]
            for point in points:
                ci=point.get('curve_number',point.get('curveNumber',-1))
                pi=point.get('point_index',point.get('pointIndex',point.get('point_number',-1)))
                if not isinstance(ci,int) or not 0<=ci<len(fig.data):continue
                trace=fig.data[ci];meta=trace.meta or {}
                if not meta.get('selectable') or trace.customdata is None:continue
                if not isinstance(pi,int) or not 0<=pi<len(trace.customdata):continue
                identifier=str(trace.customdata[pi][0])
                if not identifier or identifier in self.settings.get('excluded_points',{}):continue
                entry=exclusions.entry(self.raw,meta['module'],identifier,meta.get('metric'),'Исключено кликом на графике')
                if entry:entries.append(entry)
            if entries:self.change(added=entries)
        if edit:fig.update_layout(clickmode='event+select',dragmode='pan')
        return st.plotly_chart(fig,key=chart_key,use_container_width=True,theme='streamlit',
            on_select=selected if edit else 'ignore',selection_mode='points',
            config={'displaylogo':False,'scrollZoom':False,'toImageButtonOptions':{'format':'png','scale':3}})
    def tools(self,module,subset=None,suffix='',metric=None):
        with st.expander('Ручной фильтр точек'+(' · '+suffix if suffix else '')):
            st.caption('Отметьте «Исключить» и примените изменения. Исходные значения сохраняются. Гистограммы и накопленный объем пересчитываются по действующим точкам.')
            if not st.checkbox('Показать таблицу точек',False,key=self.key('open_'+module+suffix)):return
            source=self.raw.get(module,pd.DataFrame()) if subset is None else subset() if callable(subset) else subset
            if source.empty:st.info('Нет исходных точек в этом выборе.');return
            if module=='response':
                options=[c for c in ('level','pressure') if c in source]
                metric=st.selectbox('Показатель для фильтра',options,format_func=lambda x:'Уровень жидкости' if x=='level' else 'Приведенное давление',key=self.key('metric'+suffix))
            else:metric='pressure' if module=='object_pressure' else 'q'
            order=[c for c in ('date','well') if c in source]
            source=source.sort_values(order,ascending=[False,True][:len(order)])
            total=max(1,(len(source)+499)//500)
            page_key=self.key('page_'+module+suffix)
            if not 1<=st.session_state.get(page_key,1)<=total:st.session_state[page_key]=1
            page=st.number_input('Страница точек',min_value=1,max_value=total,value=1,step=1,key=page_key)
            part=source.iloc[(page-1)*500:page*500].copy()
            st.caption(f'Страница {page} из {total}; всего {len(source):,} исходных строк.')
            fields=[c for c in LABELS if c in part and c not in ('reason','excluded_utc','metric','module')]
            table=part[fields].rename(columns=LABELS).reset_index(drop=True)
            if 'Q' in table:table=table.rename(columns={'Q':'Q, м³/сут' if module=='production' else 'Q, тыс. м³/сут'})
            ids=part['_point_id'].map(lambda value:exclusions.point_id(module,value,metric)).tolist()
            table.insert(0,'Исключить',[identifier in self.settings.get('excluded_points',{}) for identifier in ids]);table['_ID']=ids
            before=dict(zip(ids,table['Исключить']))
            identity=hashlib.sha1(','.join(ids).encode('utf8')).hexdigest()[:12]
            edited=st.data_editor(table,hide_index=True,use_container_width=True,
                disabled=[c for c in table if c!='Исключить'],column_config={'_ID':None},
                key=self.key('editor_'+module+suffix+'_'+metric+'_'+identity+'_'+str(self.revision)))
            reason=st.text_input('Причина исключения',value='Ручная проверка',key=self.key('reason_'+module+suffix))
            def save():
                added=[];removed=[]
                for row in edited.to_dict('records'):
                    identifier=row['_ID'];new=bool(row['Исключить'])
                    if new and not before[identifier]:added.append(exclusions.entry(self.raw,module,identifier,metric,reason))
                    elif not new and before[identifier]:removed.append(identifier)
                if added or removed:self.change(added,removed)
            st.button('Применить ручной фильтр',on_click=save,key=self.key('apply_'+module+suffix),type='primary')
    def manager(self):
        journal=exclusions.journal(self.settings)
        if journal.empty:st.info('Исключенных точек нет. Включите режим исключения в боковой панели или используйте ручной фильтр под графиком.');return
        st.metric('Исключенных показателей',len(journal))
        st.download_button('Скачать журнал исключений',csv_bytes(journal.drop(columns=['batch'],errors='ignore')),'excluded_points.csv')
        a,b,c=st.columns(3)
        a.button('Восстановить все',on_click=lambda:self.change(removed=journal.id.tolist()),key=self.key('restore_all'))
        latest=journal.sort_values('excluded_utc').iloc[-1]
        batch=journal[journal.batch.eq(latest['batch'])] if 'batch' in journal else journal.iloc[-1:]
        b.button('Отменить последнее исключение',on_click=lambda:self.change(removed=batch.id.tolist()),key=self.key('undo'))
        module=c.selectbox('Модуль исключений',['all']+journal.module.unique().tolist(),format_func=lambda x:'Все модули' if x=='all' else MODULES.get(x,x))
        search=st.text_input('Поиск по скважине / горизонту / причине',key=self.key('search'))
        chosen=journal if module=='all' else journal[journal.module.eq(module)]
        if search:
            columns=[c for c in ('well','horizon','reason') if c in chosen]
            mask=chosen[columns].fillna('').astype(str).apply(lambda col:col.str.contains(search,case=False,regex=False)).any(axis=1)
            chosen=chosen[mask]
        total=max(1,(len(chosen)+499)//500);page_key=self.key('restore_page')
        if not 1<=st.session_state.get(page_key,1)<=total:st.session_state[page_key]=1
        page=st.number_input('Страница исключений',1,total,1,key=page_key)
        part=chosen.iloc[(page-1)*500:page*500].copy();part=part.drop(columns=['batch'],errors='ignore').rename(columns=LABELS)
        part.insert(0,'Восстановить',False)
        identity=hashlib.sha1(','.join(part['id']).encode('utf8')).hexdigest()[:12]
        edited=st.data_editor(part,hide_index=True,use_container_width=True,disabled=[c for c in part if c!='Восстановить'],
            column_config={'id':None},key=self.key('restore_editor_'+identity+'_'+str(self.revision)))
        def restore():self.change(removed=edited.loc[edited['Восстановить'],'id'].tolist())
        st.button('Восстановить выбранные',on_click=restore,key=self.key('restore_selected'),type='primary')
