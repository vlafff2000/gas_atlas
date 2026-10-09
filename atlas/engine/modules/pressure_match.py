"""Pressure adaptation: observed/model pairs, source-compatible percentiles and thresholds.

The Python reference uses abs(model-fact), np.percentile (linear), population
standard deviation, excludes missing/zero/negative pressures and defines the
recent window from 1 April of (latest source year - 3). The HTML reference uses
strict abs(model-fact) < per-group threshold. Those conventions are explicit.
"""
import csv
import io
import re
import warnings
from functools import partial
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from atlas.engine.core.config import ordered
from atlas.engine.core.performance import cached_chart
from atlas.engine.modules import charts,production

LABELS={'cross':'Кроссплот факт / модель','time':'Давления во времени','error_time':'Отклонения во времени',
 'overall_box':'Общие ящики с усами: все данные / 3 года','box':'Ящики с усами по скважинам','fond_box':'Ящики с усами по фондам','object_box':'Сравнение объектов и сценариев',
 'hist':'Гистограммы распределения отклонений','cdf':'Доля точек в пределах отклонения','percentiles':'Процентили по объектам и сценариям'}
FONDS=['Эксплуатационные','Наблюдательные','Неизвестный']
ALIASES={'well':r'скваж|^well|^скв|^номер|^№','date':r'дат|date|time|врем',
 'value':r'давлен|pressure|^p$|^p_|wbp|wb hp|bhp|^факт|^модел|^fact|^model'}

def well_id(value):
    s=str(value).strip().strip('"\'');s=re.sub(r'\.0$','',s)
    match=re.search(r"['\"]([^'\"]+)['\"]",s)
    if match:s=match.group(1)
    elif re.search(r'wbp|bhp|скв|well',s,re.I):
        matches=re.findall(r'(\d+[A-Za-zА-Яа-я]?)',s)
        if matches:s=matches[-1]
    return s.lstrip('№#').strip()

def per_unique(values,function):
    """Apply a slow per-value function once per distinct value (millions of rows, a few hundred wells / dates)."""
    codes,uniques=pd.factorize(values)
    mapped=pd.Series([function(v) for v in uniques],dtype=object).to_numpy()
    result=np.empty(len(codes),dtype=object);ok=codes>=0
    result[ok]=mapped[codes[ok]] if len(mapped) else None;result[~ok]='nan'
    return result

def dates(values):
    """Parse once per distinct value: a date column repeats the same few thousand dates for every well."""
    if pd.api.types.is_datetime64_any_dtype(values):return pd.to_datetime(values).dt.normalize()
    codes,uniques=pd.factorize(values)
    parsed=_dates_series(pd.Series(uniques,dtype=object)).to_numpy('datetime64[ns]')
    result=np.full(len(codes),np.datetime64('NaT','ns'),dtype='datetime64[ns]');ok=codes>=0
    if len(parsed):result[ok]=parsed[codes[ok]]
    return pd.Series(result,index=values.index)

def _dates_series(values):
    if pd.api.types.is_datetime64_any_dtype(values):return pd.to_datetime(values).dt.normalize()
    text=values.astype(str).str.strip();iso=text.str.match(r'^\d{4}-\d{2}-\d{2}')
    result=pd.Series(pd.NaT,index=values.index,dtype='datetime64[ns]')
    result.loc[iso]=pd.to_datetime(text[iso],errors='coerce')
    rest=~iso
    if rest.any():
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)  # mixed free-form date strings are parsed one by one on purpose
            result.loc[rest]=pd.to_datetime(text[rest],errors='coerce',dayfirst=True)
    # Excel serial dates are accepted only within a plausible calendar range.
    numeric=pd.to_numeric(values,errors='coerce');serial=rest&numeric.between(20000,80000)
    result.loc[serial]=pd.to_datetime(numeric[serial],unit='D',origin='1899-12-30',errors='coerce')
    return result.dt.normalize()

def numeric_slow(values):
    return pd.to_numeric(values.astype(str).str.replace('\u00a0','',regex=False).str.replace(' ','',regex=False).str.replace(',','.',regex=False),errors='coerce')

def numeric(values):
    """Plain numbers go through the fast path; only text cells (decimal commas, spaces) take the string route."""
    fast=pd.to_numeric(values,errors='coerce')
    text=fast.isna()&values.notna()
    if text.any():fast=fast.copy();fast[text]=numeric_slow(values[text])
    from atlas.engine.core.config import NODATA
    return fast.mask(fast.isin(NODATA))      # −999,25 и подобное — «нет данных»

def read_tables(content,name):
    from atlas.engine.core.tabular import read_content,headed
    return {sheet:headed(raw) for sheet,raw in read_content(content,name)[1].items()}

def detect_columns(table):
    columns=list(table.columns);match=lambda key:next((c for c in columns if re.search(ALIASES[key],str(c),re.I)),None)
    # «скв 74», «well 89» в заголовке — это сама скважина (широкая таблица), а не колонка «Скважина».
    well=next((c for c in columns if re.search(ALIASES['well'],str(c),re.I) and not re.search(r'^(скв\w*\.?|well)[\s:№#_.-]*\d',str(c),re.I)),None)
    date,value=match('date'),match('value')
    if date is None and columns:date=columns[0]
    if value is None and well is not None:
        value=next((c for i,c in enumerate(columns) if c not in (well,date) and numeric(table.iloc[:,i]).notna().any()),None)
    return {'date':date,'well':well,'value':value,'format':'long' if well is not None and value is not None else 'wide'}

def normalize(table,cfg=None):
    cfg={**detect_columns(table),**(cfg or {})};date=cfg['date']
    if date not in table:raise ValueError('Выберите колонку даты.')
    if cfg['format']=='long':
        if cfg['well'] not in table or cfg['value'] not in table:raise ValueError('Выберите колонки скважины и давления.')
        d=pd.DataFrame({'date':dates(table[date]),'well':per_unique(table[cfg['well']],well_id),'value':numeric(table[cfg['value']]),'_row':table[cfg['row_column']].values if cfg.get('row_column') in table else np.arange(len(table))+cfg.get('row_offset',2)})
    else:
        cols=[c for c in table if c!=date and not str(c).startswith('Unnamed:')]
        parts=[];parsed=dates(table[date]);source_rows=table[cfg['row_column']].values if cfg.get('row_column') in table else np.arange(len(table))+cfg.get('row_offset',2)
        for c in cols:
            parts.append(pd.DataFrame({'date':parsed,'well':well_id(c),'value':numeric(table[c]),'_row':source_rows}))
        d=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=['date','well','value','_row'])
    d=d[d.date.notna()&d.well.notna()&d.well.ne('')&~d.well.isin(['nan','None'])]
    return d.reset_index(drop=True)

def normalize_fonds(table):
    raw=[list(table.columns)]+table.values.tolist();result={}
    for i,row in enumerate(raw[:6]):
        wells=[j for j,c in enumerate(row) if re.search(r'скваж|well|^скв',str(c),re.I)]
        types=[j for j,c in enumerate(row) if re.search(r'тип|type|фонд|fond',str(c),re.I)]
        if not wells or not types:continue
        for wcol,tcol in zip(wells,types):
            for values in raw[i+1:]:
                w,f=values[wcol],values[tcol]
                if pd.isna(w) or pd.isna(f):continue
                text=str(f).strip();kind='Наблюдательные' if re.search('наблюд|пьезо',text,re.I) else 'Эксплуатационные' if re.search('действ|ликвид|эксплуата',text,re.I) else text
                result[well_id(w)]=kind
        break
    return result

def pair(fact,model,object_name,scenario,fonds=None,duplicate='first'):
    keys=['well','date'];fact=fact.copy();model=model.copy();diagnostics=[]
    for name,d in [('Факт',fact),('Модель',model)]:
        count=int(d.duplicated(keys,keep=False).sum())
        if count:diagnostics.append({'Объект':object_name,'Сценарий':scenario,'Источник':name,'Проблема':'Повторные скважина/дата','Строк':count,'Правило':duplicate})
    if duplicate=='error' and (fact.duplicated(keys).any() or model.duplicated(keys).any()):raise ValueError('Повторные скважина/дата. Выберите правило обработки дубликатов.')
    def unique(d):
        if duplicate=='mean':return d.groupby(keys,as_index=False).agg(value=('value','mean'),_row=('_row','min'))
        return d.drop_duplicates(keys,keep=duplicate if duplicate in ('first','last') else 'first')
    fact,model=unique(fact),unique(model)
    merged=fact.rename(columns={'value':'fact'}).merge(model.rename(columns={'value':'model','_row':'_model_row'}),on=keys,how='outer',validate='one_to_one',indicator=True)
    counts=merged['_merge'].value_counts()
    for mode,label in [('left_only','Нет модели на дату замера'),('right_only','Нет факта на дату модели')]:
        if counts.get(mode,0):diagnostics.append({'Объект':object_name,'Сценарий':scenario,'Источник':'Сопоставление','Проблема':label,'Строк':int(counts[mode]),'Правило':'Сохраняется как неполная пара'})
    merged=merged.drop(columns='_merge').assign(object=object_name,scenario=scenario,fond=lambda d:d.well.map(fonds or {}).fillna('Неизвестный'),group='Без группы',subgroup='')
    return merged,diagnostics

def filter_data(data,settings,mapping,cfg=None):
    cfg=cfg or {};d=data.copy();d.attrs={}
    if d.empty:return d,{}
    d=d[d.well.notna()&d.well.astype(str).ne('nan')].copy()  # projects saved by v5.8.x UI builds may hold rows without a well
    if d.empty:return d,{}
    d['date']=pd.to_datetime(d.date)
    # Reference script takes the latest source date before invalid pressures are discarded.
    starts=d.groupby('object').date.max().map(lambda date:pd.Timestamp(year=date.year-3,month=4,day=1))
    if cfg.get('recent_starts'):starts=pd.Series({obj:pd.Timestamp(cfg['recent_starts'].get(obj,value)) for obj,value in starts.items()})
    d['recent_start']=d.object.map(starts);d['recent']=d.date.ge(d.recent_start)
    recent_start=', '.join(sorted(set(str(v.date()) for v in starts)))
    d['object_group']=d.object.map(cfg.get('object_groups',{})).fillna('Без категории')
    d['group']=per_unique(d.well,lambda w:mapping.get(w,{}).get('group','Без группы'))
    for col,field in [('object','objects'),('scenario','scenarios'),('fond','fonds'),('well','wells'),('group','groups')]:
        if cfg.get(field) is not None:d=d[d[col].isin(cfg[field])]
    span=cfg.get('dates')
    if span and len(span)==2:d=d[d.date.between(pd.Timestamp(span[0]),pd.Timestamp(span[1]))]
    if cfg.get('recent'):d=d[d.recent]
    stats={'selected':len(d),'recent_start':recent_start}
    bad=~(np.isfinite(d.fact)&np.isfinite(d.model));stats['missing']=int(bad.sum());d=d[~bad]
    negative=d.fact.lt(0)|d.model.lt(0);stats['negative']=int(negative.sum());d=d[~negative]
    zero=d.fact.eq(0)|d.model.eq(0);stats['zeros']=int(zero.sum())
    if cfg.get('exclude_zeros',True):d=d[~zero]
    d['signed_error']=d.model-d.fact;d['error']=d.signed_error.abs()
    d['relative_error']=d.error/d.fact.abs().where(d.fact.ne(0))*100
    thresholds=cfg.get('group_thresholds',{})
    d['threshold']=per_unique(d.group,lambda g:float(thresholds.get(g,cfg.get('threshold',10)))).astype(float)
    measure=d.relative_error if cfg.get('threshold_mode')=='relative' else d.error
    d['within']=measure.le(d.threshold) if cfg.get('inclusive',False) else measure.lt(d.threshold)
    d['valid_threshold']=measure.notna()
    month=d.date.dt.month;start=settings.get('season_start',11);end=settings.get('season_end',4)
    withdrawal=(month.ge(start)|month.le(end)) if start>end else month.between(start,end)
    d['kind']=np.where(withdrawal,'withdrawal','injection')
    # Season labels depend on the date only: compute them for the distinct dates, then map back.
    days=d[['date']].drop_duplicates().assign(season='',year='',kind='withdrawal')
    label=production.periods(days,start,end).set_index('date').period
    d['period']=np.where(withdrawal,'Отбор '+d.date.map(label).astype(str),'Закачка '+d.date.dt.year.astype(str))
    if cfg.get('periods') is not None:d=d[d.period.isin(cfg['periods'])]
    stats['used']=len(d)
    return d.sort_values(['object','scenario','well','date']).reset_index(drop=True),stats

def statistics(d,percentiles=(80,85,90)):
    if d.empty:return {'Точек':0}
    error=d.error.to_numpy();signed=d.signed_error.to_numpy();q1,q3=np.percentile(error,[25,75]);iqr=q3-q1
    valid=d.valid_threshold;within=d.loc[valid,'within']
    result={'Точек':len(d),'Среднее отклонение':float(np.mean(error)),'Медиана':float(np.median(error)),
     'Минимум':float(np.min(error)),'Максимум':float(np.max(error)),'Стандартное отклонение':float(np.std(error)),
     'Смещение модели':float(np.mean(signed)),'RMSE':float(np.sqrt(np.mean(signed**2))),
     'Разброс ошибки (σ, со знаком, n−1)':float(np.std(signed,ddof=1)) if len(signed)>1 else np.nan,
     'MAPE, %':float(d.relative_error.mean()),'В пределах порога, %':float(within.mean()*100) if len(within) else np.nan,
     'Точек для порога':int(valid.sum()),'Q1':float(q1),'Q3':float(q3),
     'Нижний ус':float(max(error.min(),q1-1.5*iqr)),'Верхний ус':float(min(error.max(),q3+1.5*iqr)),
     'Выбросов IQR':int(((error<q1-1.5*iqr)|(error>q3+1.5*iqr)).sum())}
    for p in percentiles:
        value=float(np.percentile(error,p));result['P{:g}'.format(p)]=value
        result['Доля ≤ P{:g}, %'.format(p)]=float((error<=value).mean()*100)
    return result

def tables(d,cfg=None):
    cfg=cfg or {};ps=cfg.get('percentiles',[80,85,90]);out={}
    out['Общая статистика']=pd.DataFrame([statistics(d,ps)])
    for title,cols in [('По скважинам',['object','scenario','well','fond']),('По фондам',['object','scenario','fond']),('По сезонам',['object','scenario','period','fond']),('Сводная объектов',['object','scenario']),('По группам',['object','scenario','group'])]:
        rows=[]
        for key,g in d.groupby(cols,dropna=False,sort=False):
            key=key if isinstance(key,tuple) else (key,);rows.append({**dict(zip(cols,key)),**statistics(g,ps)})
        out[title]=pd.DataFrame(rows)
    out['Последние 3 года']=pd.DataFrame([{**dict(zip(['object','scenario','fond'],key)),**statistics(g,ps)} for key,g in d[d.recent].groupby(['object','scenario','fond'],sort=False)])
    out['Данные кросс-плота']=d.drop(columns=[c for c in d if c.startswith('_')],errors='ignore')
    return out

BOX_EXACT_LIMIT=1500

def add_box(fig,values,label,name,color=None,outliers=True,**extra):
    """Box with whiskers. Large groups send exact quartiles instead of every raw value (tens of MB otherwise)."""
    values=np.asarray(values,dtype=float);values=values[np.isfinite(values)]
    marker={'marker_color':color} if color else {}
    if len(values)<=BOX_EXACT_LIMIT:
        fig.add_trace(go.Box(y=values,x=[label]*len(values),name=name,boxpoints='outliers' if outliers else False,quartilemethod='linear',**marker,**extra));return
    q1,median,q3=np.percentile(values,[25,50,75]);iqr=q3-q1;low,high=q1-1.5*iqr,q3+1.5*iqr
    inside=values[(values>=low)&(values<=high)]
    fig.add_trace(go.Box(x=[label],q1=[q1],median=[median],q3=[q3],lowerfence=[inside.min()],upperfence=[inside.max()],mean=[values.mean()],name=name,**marker,**extra))
    out=values[(values<low)|(values>high)]
    if outliers and len(out):
        out=out[np.linspace(0,len(out)-1,min(len(out),300)).astype(int)] if len(out)>300 else out
        fig.add_trace(go.Scatter(x=[label]*len(out),y=out,mode='markers',name=name+' · выбросы',showlegend=False,marker={'size':4,**({'color':color} if color else {})},hoverinfo='y',meta={'selectable':False}))

def downsample_sorted(values,limit=2000):
    values=np.sort(values)
    if len(values)<=limit:return values,np.arange(1,len(values)+1)/len(values)*100
    index=np.unique(np.linspace(0,len(values)-1,limit).astype(int))
    return values[index],(index+1)/len(values)*100

@cached_chart
def figure(d,name,cfg=None,title=None):
    cfg=cfg or {};unit=cfg.get('unit','бар');single=len(d.well.unique())==1 if not d.empty else False
    fig=charts.base(title or ('Скважина №'+str(d.well.iloc[0])+' · ' if single else '')+LABELS[name],
         'Фактическое давление, '+unit if name=='cross' else 'Дата' if name in ('time','error_time') else 'Отклонение, '+unit,
         'Модельное давление, '+unit if name=='cross' else 'Давление, '+unit if name=='time' else 'Отклонение, '+unit)
    fig.update_layout(meta={'module':'pressure_match','wells':ordered(d.well),'chart':name},height=580)
    if d.empty:return fig
    mode=cfg.get('color','scenario');column={'well':'well','group':'group','scenario':'scenario','object':'object','object_group':'object_group'}.get(mode,'scenario');palette=charts.well_colors(d[column])
    if name=='cross':
        limit=cfg.get('screen_limit');shown=d.sample(limit,random_state=0).sort_index() if limit and len(d)>limit else d
        trace=go.Scattergl if limit and len(d)>5000 else go.Scatter
        for label,g in shown.groupby(column,sort=False):
            custom=np.column_stack([g.get('_point_id',pd.Series('',index=g.index)),g.well,g.date.dt.strftime('%d.%m.%Y'),g.scenario,g.error,g.threshold])
            fig.add_trace(trace(x=g.fact,y=g.model,mode='markers',name=str(label),marker={'color':palette[label],'size':6 if len(shown)<20000 else 4},customdata=custom,
                meta={'module':'pressure_match','selectable':True},hovertemplate='Скв. %{customdata[1]} · %{customdata[3]}<br>%{customdata[2]}<br>Факт: %{x:.3f}<br>Модель: %{y:.3f}<br>|ΔP|: %{customdata[4]:.3f}<br>Порог: %{customdata[5]:.3f}<extra></extra>'))
        if len(shown)<len(d):fig.add_annotation(text='Показана выборка {:,} из {:,} точек; статистика и таблицы — по всем.'.format(len(shown),len(d)).replace(',',' '),xref='paper',yref='paper',x=0,y=1.04,showarrow=False,font={'size':11})
        lo=max(0,min(d.fact.min(),d.model.min()));hi=max(d.fact.max(),d.model.max());x=np.array([lo,hi if hi>lo else lo+1])
        for label,y,color,dash in [('Идеальное совпадение',x,'#64748B','solid')]:fig.add_trace(go.Scatter(x=x,y=y,mode='lines',name=label,line={'color':color,'dash':dash}))
        if cfg.get('bands',True):
            for threshold in sorted(set(d.threshold)):
                for sign in (-1,1):
                    y=x*(1+sign*threshold/100) if cfg.get('threshold_mode')=='relative' else x+sign*threshold
                    fig.add_trace(go.Scatter(x=x,y=y,mode='lines',name='±{:g} {}'.format(threshold,'%' if cfg.get('threshold_mode')=='relative' else unit),showlegend=sign==1,legendgroup='threshold_'+str(threshold),line={'color':'#D97706','dash':'dash'}))
        if cfg.get('percentile_lines',False):
            for p in cfg.get('percentiles',[80,85,90]):
                delta=np.percentile(d.error,p)
                for sign in (-1,1):fig.add_trace(go.Scatter(x=x,y=x+sign*delta,mode='lines',name='P{:g} = {:.3g}'.format(p,delta),showlegend=sign==1,line={'dash':'dot','color':'#8B5CF6'}))
        fig.update_yaxes(scaleanchor='x',scaleratio=1)
    elif name in ('time','error_time'):
        fig.update_xaxes(type='date');fig.update_layout(hovermode='x unified')
        labels=ordered(str(v) for v in d.scenario);colors=charts.well_colors(labels)
        # One fact trace per object/well; joining scenarios never multiplies measured values.
        if name=='time':
            for (obj,well),g in d.drop_duplicates(['object','well','date']).groupby(['object','well']):
                fig.add_trace(go.Scatter(x=g.date,y=g.fact,mode='lines+markers',name='Факт'+(' · №'+well if not single else '')+(' · '+obj if d.object.nunique()>1 else ''),line={'color':'#64748B','dash':'solid'},connectgaps=False))
        for (obj,scenario,well),g in d.groupby(['object','scenario','well'],sort=False):
            label=str(scenario)+(' · №'+well if not single else '')+(' · '+obj if d.object.nunique()>1 else '')
            fig.add_trace(go.Scatter(x=g.date,y=g.model if name=='time' else g.signed_error,mode='lines+markers',name=label,line={'color':colors[scenario],'dash':'solid'},connectgaps=False))
        if name=='error_time':fig.update_yaxes(title='Модель − факт, '+unit)
    elif name=='overall_box':
        rows=[('Все данные',d),('Последние 3 года',d[d.recent])]
        for fond in ordered(d.fond):rows.extend([(fond,d[d.fond.eq(fond)]),(fond+' · 3 года',d[d.fond.eq(fond)&d.recent])])
        for label,g in rows:
            if not g.empty:add_box(fig,g.error,label,label,outliers=cfg.get('outliers',True))
        fig.update_xaxes(title='Период и фонд',type='category')
    elif name in ('box','fond_box','object_box'):
        col={'box':'well','fond_box':'fond','object_box':'object'}[name]
        medians=d.groupby(col).error.median();categories=sorted(medians.index,key=lambda c:medians[c]);palette=charts.well_colors(categories)
        colors=charts.well_colors(d[column]) if mode in ('group','object_group') else None
        parts={}
        for (category,scenario),g in d.groupby([col,'scenario'],sort=True):parts.setdefault(category,[]).append((scenario,g))
        for category in categories:
            for scenario,g in parts[category]:
                label=(str(category)+' · ' if not (single and col=='well') else '')+str(scenario)
                color=colors[g[column].iloc[0]] if colors else palette[category]
                add_box(fig,g.error,str(category),label,color,cfg.get('outliers',True),meta={'selectable':False})
        fig.update_layout(boxmode='group');fig.update_xaxes(title={'box':'Скважина (по медиане)','fond_box':'Фонд','object_box':'Объект'}[name],type='category',categoryorder='array',categoryarray=categories)
    elif name=='hist':
        edges=np.histogram_bin_edges(d.error.to_numpy(),bins=int(cfg.get('bins',20)));centers=(edges[:-1]+edges[1:])/2
        for label,g in d.groupby(column,sort=False):
            counts,_=np.histogram(g.error,bins=edges)
            fig.add_trace(go.Bar(x=centers,y=counts,name=str(label),width=np.diff(edges)*.9,marker_color=palette[label]))
        fig.update_layout(barmode='group');fig.update_yaxes(title='Количество точек');fig.update_xaxes(type='linear')
    elif name=='cdf':
        for label,g in d.groupby(column,sort=False):
            values,share=downsample_sorted(g.error.to_numpy());fig.add_trace(go.Scatter(x=values,y=share,name=str(label),mode='lines',line={'color':palette[label],'dash':'solid'}))
        fig.update_yaxes(title='Доля точек с отклонением ≤ X, %',range=[0,100]);fig.update_xaxes(rangemode='tozero')
    elif name=='percentiles':
        for (obj,scenario),g in d.groupby(['object','scenario'],sort=False):
            ps=cfg.get('percentiles',[80,85,90]);fig.add_trace(go.Bar(x=['P{:g}'.format(p) for p in ps],y=np.percentile(g.error,ps),name=obj+' · '+scenario))
        fig.update_xaxes(title='Процентиль',type='category');fig.update_layout(barmode='group')
    axes=cfg.get('axes',{})
    for axis in ('x','y'):
        values={k:axes[axis+'_'+k] for k in ('range','dtick') if axis+'_'+k in axes}
        if values:getattr(fig,'update_'+axis+'axes')(**values)
    fig.update_layout(showlegend=cfg.get('legend',True))
    return fig

def report_plan(data,settings,mapping,cfg):
    from atlas.engine.core.reporting import FigureJob,ReportPlan
    if data is None:return ReportPlan([],{}, {})
    d,_=filter_data(data,settings,mapping,cfg);jobs=[];style=settings.get('chart_style',{})
    split=cfg.get('split','all');sets=[('Все выбранные',d)] if split=='all' else [(str(key),g) for key,g in d.groupby('well' if split=='well' else 'group',sort=False)]
    for label,g in sets:
        for name in cfg.get('charts',list(LABELS)):
            jobs.append(FigureJob(label+' · '+LABELS[name],partial(figure,g,name,cfg),style,'pressure_match'))
    return ReportPlan(jobs,tables(d,cfg))
