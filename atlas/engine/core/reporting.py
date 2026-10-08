"""A lazy figure plan shared by previews and sequential report export."""
from dataclasses import dataclass,field
from functools import partial
from collections.abc import Mapping
import pandas as pd
from atlas.engine.core import exclusions
from atlas.engine.core.config import ordered
from atlas.engine.modules import production,gdi,response,charts,group_analysis

@dataclass
class FigureJob:
    name: str
    factory: object
    style: dict
    module: str = ""
    def render(self):
        return charts.style_figure(self.factory(),self.style,copy_figure=False)

class FigureMap(Mapping):
    def __init__(self,jobs):self.jobs=jobs;self.lookup={j.name:j for j in jobs}
    def __len__(self):return len(self.jobs)
    def __iter__(self):return iter(self.lookup)
    def __getitem__(self,name):return self.lookup[name].render()
    def items(self):
        for job in self.jobs:yield job.name,job.render()

@dataclass
class ReportPlan:
    jobs: list
    tables: dict
    module_tables: dict = field(default_factory=dict)
    def figures(self):return FigureMap(self.jobs)

class WellProvider:
    def __init__(self,frames,settings,mapping,cfg):
        self.frames=frames;self.settings=settings;self.mapping=mapping;self.cfg=cfg;self.held=None
    def get(self,well):
        from atlas.engine.modules import well_analysis
        if self.held is None or self.held[0]!=well:
            value=dict(well_analysis.analyze(self.frames,self.settings,self.mapping,well,self.cfg.get('kind','withdrawal'),self.cfg.get('periods'),self.cfg.get('delta'),self.cfg.get('threshold',10),self.cfg.get('method'),self.cfg.get('asof')))
            if 'gdi' in self.frames:
                from atlas.engine.core.performance import select_wells
                raw=getattr(self.frames,'project',None)
                original=select_wells(raw.raw('gdi') if raw is not None else self.frames['gdi'],[well])
                original=original[original.date.le(value['asof'])]
                if self.cfg.get('method') is not None:original=original[original.method.eq(self.cfg['method'])]
                if self.cfg.get('periods') and not value['daily'].empty:
                    mask=pd.Series(False,index=original.index)
                    for _,g in value['daily'].groupby('period'):mask|=original.date.between(g.date.min(),g.date.max())
                    original=original[mask]
                value['gdi_raw']=original
            self.held=(well,value)
        return self.held[1]
    def figure(self,well,name):
        from atlas.engine.modules import well_charts
        parameters={**self.settings,'dashboard_gdi':self.cfg.get('gdi',{}),'dashboard_alignment':self.cfg.get('alignment','well')}
        fig=well_charts.build(self.get(well),name,parameters)
        if self.cfg.get('_module'):fig.update_layout(meta={**fig.layout.meta,'module':self.cfg['_module']})
        return fig


def object_figure(d):
    import plotly.graph_objects as go
    import numpy as np
    d=d.sort_values('date');fig=charts.base('Пластовое давление объекта','Дата','Пластовое давление, кгс/см²')
    fig.update_layout(meta={'module':'object_pressure','wells':[]});fig.update_xaxes(type='date')
    fig.add_trace(go.Scatter(x=d.date,y=d.pressure,mode='lines+markers',name='Пластовое давление объекта',line={'color':'#DC3545','dash':'solid'},meta={'module':'object_pressure','metric':'pressure','selectable':True},customdata=np.column_stack([d['_point_id'] if '_point_id' in d else ['']*len(d)])))
    return fig


def _plan(frames,mapping,settings,options,raw_frames=None):
    jobs=[];tables={};wells=options.get('wells',[]);raw_frames=raw_frames or frames;style=options.get('style',settings.get('chart_style',{}))
    def add(name,fn,*args,**kwargs):jobs.append(FigureJob(name,partial(fn,*args,**kwargs),style))
    for module in options.get('modules',list(frames)):
        cfg=options.get(module,{});ws=[w for w in cfg.get('wells',wells) if w in wells]
        if module=='well_dashboard':
            from atlas.engine.modules import well_charts
            provider=WellProvider(frames,settings,mapping,cfg);combined={}
            for well in ws:
                analysis=provider.get(well)
                for name in well_charts.available(analysis):
                    if cfg.get('charts') is not None and name not in cfg['charts']:continue
                    add('Анализ №'+well+' · '+well_charts.LABELS[name],provider.figure,well,name)
                for title,data in well_charts.tables(analysis).items():
                    topic=title.rsplit('_',1)[0]
                    if topic=='Суточные' and not options.get('raw'):continue
                    data=data.copy(deep=False);data.attrs={};data=data.assign(Скважина=well)
                    combined.setdefault(topic,[]).append(data)
            tables.update({'Анализ_'+topic:pd.concat(parts,ignore_index=True) for topic,parts in combined.items()});provider.held=None;continue
        if module=='histograms':
            nested=plan(frames,mapping,settings,{**options,'modules':['production'],'production':{**cfg,'view':'hist'}},raw_frames)
            def histogram_job(factory):
                fig=factory();fig.update_layout(meta={**fig.layout.meta,'module':'histograms'});return fig
            jobs.extend(FigureJob(j.name,partial(histogram_job,j.factory),j.style) for j in nested.jobs)
            tables.update({'Гистограммы_'+k:v for k,v in nested.tables.items()});continue
        if module not in frames or frames[module].empty:continue
        if module=='production' and cfg.get('panels'):
            for i,panel in enumerate(cfg['panels']):
                p=plan(frames,mapping,settings,{**options,'modules':['production'],'production':panel},raw_frames)
                jobs.extend(FigureJob('Панель '+str(i+1)+' · '+j.name,j.factory,j.style) for j in p.jobs)
                tables.update({'Панель '+str(i+1)+'_'+name:table for name,table in p.tables.items() if name!='Исключенные_точки'})
            continue
        if not ws and module!='object_pressure':continue
        if module=='production':
            d=production.periods(frames[module],settings['season_start'],settings['season_end'])
            for kind,ps in cfg.get('periods',{}).items():
                if not ps:continue
                chosen=production.rank_wells(d,kind,ps,ws,cfg.get('direction','number'));split=cfg.get('split','well');view=cfg.get('view','mixed')
                averages=production.averages(d,kind,ps,chosen);present=set(averages.loc[~averages.missing,'well']);chosen=[w for w in chosen if w in present]
                if split=='group_total':
                    selected_groups=cfg.get('groups',ordered(mapping.get(w,{}).get('group','Без группы') for w in chosen))
                    for group in selected_groups:
                        table,group_wells=group_analysis.daily(d,mapping,group,kind,ps)
                        if table.empty:continue
                        add(('Отбор' if kind=='withdrawal' else 'Закачка')+' · сумма '+group,group_analysis.figure,d,mapping,group,kind,ps,cfg.get('overlay',[]),cfg.get('metric','daily'),interactive=False)
                        tables['Группа_'+group+'_'+kind]=table
                    continue
                if split=='well':sets={w:[w] for w in chosen}
                elif split=='all':sets={'Все выбранные':chosen}
                elif split=='subgroup':sets=production.partitions(d,mapping,kind,ps,chosen,cfg.get('group_mode','manual'),cfg.get('size',8),cfg.get('direction','number'))
                else:sets={group:[w for w in chosen if mapping.get(w,{}).get('group','Без группы')==group] for group in ordered(mapping.get(w,{}).get('group','Без группы') for w in chosen)}
                for label,part in sets.items():
                    title=('Отбор' if kind=='withdrawal' else 'Закачка')+' · '+label
                    if view in ('curve','time','mixed'):add(title,charts.production_curve,d,kind,ps,part,'date' if view=='time' else 'cumulative',title=charts.season_title(part[0],kind,ps) if cfg.get('season_titles') and len(part)==1 else charts.well_title(part,label if split not in ('well','all') else None),interactive=False)
                    if view in ('hist','mixed'):
                        from atlas.engine.core.config import histogram_size
                        size=histogram_size(cfg.get('hist_size','Авто'),len(part))
                        for offset in range(0,len(part),size):
                            piece=part[offset:offset+size];add(title+' · средние '+str(offset//size+1),charts.histogram,d,kind,ps,piece,cfg.get('histaxis','well'),charts.well_title(piece,label if split not in ('well','all') else None))
                tables[kind+'_средние']=averages
                if options.get('raw'):
                    tables[kind+'_данные']=exclusions.public_table(d[d.kind.eq(kind)&d.period.isin(ps)&d.well.isin(chosen)]);tables[kind+'_кривые']=exclusions.public_table(production.curve_data(d,kind,ps,chosen))
        elif module=='gdi':
            selected=gdi.select_studies(frames[module],ws,cfg.get('n',3),cfg.get('seasons'));original=gdi.select_studies(raw_frames[module],ws,cfg.get('n',3),cfg.get('seasons'))
            for well in ordered(selected.well):add('ГДИ · '+well,charts.gdi_chart,selected,well,settings['r2_threshold'],cfg.get('orientation','standard'),cfg.get('curves',True),cfg.get('db_curves',True),cfg.get('crosshair',True),raw_df=original,show_excluded=cfg.get('show_excluded',True))
            tables['ГДИ']=gdi.analyze(selected,settings['r2_threshold']);tables['Сравнение_ГДИ']=gdi.comparisons(selected)
            if options.get('raw'):tables['ГДИ_данные']=exclusions.public_table(selected)
        elif module=='response':
            d=frames[module];d=d[d.well.isin(ws)&d.horizon.isin(cfg.get('horizons',ordered(d.horizon)))];span=cfg.get('dates',[])
            if len(span)==2:d=d[d.date.between(pd.Timestamp(span[0]),pd.Timestamp(span[1]))]
            working=cfg.get('working',settings.get('working_horizons',[]));mode=cfg.get('mode','all')
            # «control» — контрольные горизонты: все скважины горизонта на одном графике, только уровень;
            # «working» — рабочие горизонты: график на каждую скважину, уровень и давление на двух шкалах.
            sets_=[(d,cfg.get('split','horizon'),cfg.get('view','separate'),'')] if mode=='all' else []
            if mode in ('control','both'):sets_.append((d[~d.horizon.isin(working)],'horizon','level','контроль · '))
            if mode in ('working','both'):sets_.append((d[d.horizon.isin(working)],'well',cfg.get('working_view','combined'),'рабочий · '))
            for dj,split,view,tag in sets_:
                if dj.empty:continue
                sets={'Все выбранные':dj} if split=='all' else {str(label):part for label,part in dj.groupby('well' if split=='well' else 'horizon')};metrics=['level','pressure'] if view=='separate' else [view]
                for label,part in sets.items():
                    for metric in metrics:
                        if metric!='combined' and (metric not in part or not part[metric].notna().any()):continue
                        if metric=='combined' and not any(col in part and part[col].notna().any() for col in ('level','pressure')):continue
                        name=tag+label+' · '+{'level':'уровень','pressure':'давление','combined':'уровень и давление'}[metric]
                        add(name,charts.response_chart,part,working,metric,title=charts.response_title(ordered(part.well),label,split),interactive=False,color_map=charts.well_colors(raw_frames[module].well),object_pressure=frames.get('object_pressure'),manometer_wells=settings.get('manometer_wells',[]),by_well=split=='well',pressure_horizons=ordered(raw_frames[module].loc[raw_frames[module].pressure.notna(),'horizon']) if 'pressure' in raw_frames[module] else [],level_band=cfg.get('level_band','overlay'))
            tables['Реагирование']=response.statistics(d)
            if options.get('raw'):tables['Замеры']=exclusions.public_table(d)
        elif module=='object_pressure':add('Давление объекта',object_figure,frames[module]);tables['Давление_объекта']=exclusions.public_table(frames[module])
        else:
            from atlas.engine.modules import well_charts
            d=frames[module];tables[module]=exclusions.public_table(d[d.well.isin(ws)]);provider=WellProvider(frames,settings,mapping,{**cfg,'_module':module})
            names={'operations':['hours','water'],'water':['water_log'],'bottom':['bottom'],'construction':['construction']}.get(module,[])
            for well in ws:
                analysis=provider.get(well)
                for name in names:
                    if name in well_charts.available(analysis):add('№'+well+' · '+well_charts.LABELS[name],provider.figure,well,name)
            provider.held=None
    if settings.get('excluded_points') and options.get('apply_exclusions',True):tables['Исключенные_точки']=exclusions.journal(settings)
    return ReportPlan(jobs,tables)


def plan(frames,mapping,settings,options,raw_frames=None):
    jobs=[];tables={};by_module={}
    for module in options.get('modules',list(frames)):
        if module=='pressure_match':
            from atlas.engine.modules import pressure_match
            part=pressure_match.report_plan(frames.get(module),settings,mapping,options.get(module,{}))
        else:part=_plan(frames,mapping,settings,{**options,'modules':[module]},raw_frames)
        for job in part.jobs:job.module=module
        jobs.extend(part.jobs);by_module[module]=part.tables
        for name,data in part.tables.items():tables[name if name not in tables else module+'_'+name]=data
    return ReportPlan(jobs,tables,by_module)


def build(frames,mapping,settings,options,raw_frames=None):
    result=plan(frames,mapping,settings,options,raw_frames)
    return dict(result.figures().items()),result.tables
