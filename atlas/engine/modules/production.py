from __future__ import annotations
import re
import numpy as np
import pandas as pd
from atlas.engine.core.config import COLORS, ordered, natural_key

def period_rule(settings):
    """Правило сезонов из настроек проекта; ключ кэша представлений.
    (начало, конец) — как в 5.8; с автоопределением или расписанием — (начало, конец, пауза сут | None, порог % | None, расписание | None)."""
    rule=(settings.get('season_start',11),settings.get('season_end',4))
    auto,schedule=settings.get('auto_seasons'),settings.get('season_schedule')
    if auto or schedule:
        from atlas.engine.modules import seasons
        gap=settings.get('season_gap_days',seasons.DEFAULT_GAP_DAYS) if auto else None
        share=settings.get('season_rate_share',seasons.DEFAULT_SHARE) if auto else None
        rule+=(gap,share,tuple(tuple(x) for x in schedule) if schedule else None)
    return rule

def periods_for(df,settings):
    """``periods`` по настройкам проекта; автоопределение сезонов и расписание периодов включают ``auto_seasons`` и ``season_schedule`` (в 5.8 их нет)."""
    return periods(df,*period_rule(settings))

def periods(df,start=11,end=4,gap_days=None,share=None,schedule=None):
    """Сезон каждой строки. С ``gap_days``/``share`` сезоны без явных «Сезон»/«Год» ищутся по накопленному расходу объекта;
    ``schedule`` (даты начала периодов) главнее всего остального."""
    extended=gap_days is not None or schedule is not None
    rule=(start,end,gap_days,share,schedule) if extended else (start,end)
    if df.attrs.get('_atlas_period_rule')==rule and 'period' in df:return df
    if df.empty: return df.assign(period=pd.Series(dtype=str))
    d=df.copy()
    # The rule is row-wise over (date year, month, kind, season, year): evaluate it once per distinct
    # combination (hundreds) instead of string operations on every row (seconds on a million rows).
    keys=pd.DataFrame({'date':d.date} if extended else {'y':d.date.dt.year,'m':d.date.dt.month},index=d.index)
    for c in ('kind','season','year'):
        if c in d: keys[c]=d[c]
    codes=keys.groupby(list(keys.columns),sort=False,dropna=False).ngroup().to_numpy()
    _,first=np.unique(codes,return_index=True)
    auto=sched=None
    if extended:
        from atlas.engine.modules import seasons
        if gap_days is not None:auto=seasons.labeler(d,gap_days,share)
        if schedule is not None:sched=seasons.schedule_labeler(schedule)
    d['period']=_period_values(d.iloc[first],start,end,auto,sched)[codes]
    return d

def _period_values(d,start,end,auto=None,sched=None):
    """Season label per row (the 5.8 rule as written; ``periods`` applies it to distinct rows)."""
    year=d.date.dt.year; month=d.date.dt.month
    if start>end:
        y=np.where(month.ge(start),year,year-1)
        derived=pd.Series(y,index=d.index).astype(str)+'-'+pd.Series(y+1,index=d.index).astype(str)
        derived=derived.where(month.ge(start)|month.le(end),'Вне сезона '+year.astype(str))
    else: derived=year.astype(str).where(month.between(start,end),'Вне сезона '+year.astype(str))
    season=d.get('season',pd.Series('',index=d.index)).fillna('').astype(str).str.replace(r'[–—]','-',regex=True).str.replace(r'\s','',regex=True)
    supplied_year=d.get('year',pd.Series('',index=d.index)).fillna('').astype(str).str.replace(r'\.0$','',regex=True)
    inj=supplied_year.where(supplied_year.str.fullmatch(r'\d{4}'),year.astype(str))
    if auto is not None:     # явные «Сезон»/«Год» главнее; остальное — по накопленному расходу
        found=auto(d.date,d.kind)
        derived,inj=found,supplied_year.where(supplied_year.str.fullmatch(r'\d{4}'),found)
    out=pd.Series(np.where(d.kind.eq('injection'),inj,season.where(season.ne(''),derived)),index=d.index)
    if sched is not None:     # расписание дат из файла главнее колонок и автоопределения
        given=sched(d.date,d.kind)
        out=out.where(given.isna(),given)
    return out.to_numpy()

def period_colors(df,kind):
    from atlas.engine.core.performance import index_for
    index=index_for(df)
    if index is not None:return index.colors.get(kind,{})
    values=df[df.kind.eq(kind)].groupby('period').date.max().sort_values(ascending=False).index
    return {p:COLORS[i%len(COLORS)] for i,p in enumerate(values)}

def curve_data(df,kind,selected_periods,wells):
    """X uses entire object for each selected period, irrespective of selected wells."""
    from atlas.engine.core.performance import index_for
    index=index_for(df)
    if index is not None:return _indexed_curves(df,index,kind,selected_periods,wells)
    out=[]
    base=df[df.kind.eq(kind)&df.period.isin(selected_periods)]
    for period,bucket in base.groupby('period',sort=False):
        if (bucket.date.max()-bucket.date.min()).days>3660:
            raise ValueError(f'Период {period} охватывает более 10 лет. Проверьте поле Сезон.')
        calendar=pd.date_range(bucket.date.min(),bucket.date.max())
        cumulative=bucket.groupby('date').q.sum().reindex(calendar,fill_value=0).cumsum()/1e6
        for well,g in bucket[bucket.well.isin(wells)].groupby('well',sort=False):
            g=g.set_index('date').reindex(calendar)
            excluded=g['_excluded'].fillna(False).astype(bool) if '_excluded' in g else pd.Series(False,index=g.index)
            part=pd.DataFrame({'date':calendar,'well':well,'period':period,
                'cumulative':cumulative.to_numpy(),'q':g.q.fillna(0).where(~excluded,np.nan).to_numpy()/1000,
                'missing':(g.q.isna()&~excluded).to_numpy()})
            for c in ('file','sheet','_row','_point_id'): part[c]=g[c].fillna('').to_numpy() if c in g else ''
            out.append(part)
    return pd.concat(out,ignore_index=True) if out else pd.DataFrame()

def averages(df,kind,selected_periods,wells):
    from atlas.engine.core.performance import index_for
    index=index_for(df)
    if index is not None:
        a=index.stats.loc[kind].copy() if kind in index.stats.index.get_level_values('kind') else pd.DataFrame(columns=['total','active','zero','records'])
        a=a.reindex(pd.MultiIndex.from_product([wells,selected_periods],names=['well','period']))
        a['missing']=a.records.isna();a['volume']=a.total/1e6
        a['value']=(a.total/a.active.replace(0,np.nan)/1000).fillna(0).where(~a.missing,np.nan)
        return a.reset_index().drop(columns=['total','records'])
    d=df[df.kind.eq(kind)&df.period.isin(selected_periods)&df.well.isin(wells)].copy()
    d['positive']=d.q.gt(0); d['zero']=d.q.eq(0)
    if d.empty: return pd.DataFrame(columns=['well','period','value','active','zero','volume','missing'])
    a=d.groupby(['well','period']).agg(total=('q','sum'),active=('positive','sum'),zero=('zero','sum'),records=('q','size'))
    a=a.reindex(pd.MultiIndex.from_product([wells,selected_periods],names=['well','period']))
    a['missing']=a.records.isna(); a['volume']=a.total/1e6
    a['value']=(a.total/a.active.replace(0,np.nan)/1000).fillna(0).where(~a.missing,np.nan)
    return a.reset_index().drop(columns=['total','records'])

def rank_wells(df,kind,selected_periods,wells,direction='desc'):
    if direction=='number': return ordered(wells)
    from atlas.engine.core.performance import index_for
    index=index_for(df)
    if index is not None:
        a=averages(df,kind,selected_periods,wells).groupby('well')[['volume','active']].sum()
        means=a.volume*1e6/a.active.replace(0,np.nan)
        return sorted(wells,key=lambda w:(float(means.get(w,0) if pd.notna(means.get(w,0)) else 0)*(1 if direction=='asc' else -1),natural_key(w)))
    d=df[df.kind.eq(kind)&df.period.isin(selected_periods)&df.well.isin(wells)&df.q.gt(0)]
    means=d.groupby('well').q.mean()
    if direction=='number': return ordered(wells)
    return sorted(wells,key=lambda w:((means.get(w,0))*(1 if direction=='asc' else -1),natural_key(w)))

def group_mapping(frames,saved):
    result={}
    for name,df in sorted(frames.items(),key=lambda kv:str(getattr(kv[0],'value',kv[0]))=='production'):      # группа из эксплуатации главнее ГДИ и др.
        if 'group' in df and 'well' in df:
            for row in df[['well','group','subgroup']].drop_duplicates('well',keep='last').itertuples(index=False):
                if row.group!='Без группы' or row.well not in result:
                    result[row.well]={'group':row.group,'subgroup':row.subgroup}
    for w,entry in saved.items(): result.setdefault(w,{}).update(entry)
    return result

def partitions(df,mapping,kind,ps,wells,mode='auto',size=8,direction='desc'):
    result={}
    for w in rank_wells(df,kind,ps,wells,direction):
        g=mapping.get(w,{}).get('group') or 'Без группы'
        if mode=='manual':
            key=g+' / '+(mapping.get(w,{}).get('subgroup') or 'Без подгруппы')
            result.setdefault(key,[]).append(w)
        else: result.setdefault(g,[]).append(w)
    if mode=='auto':
        result={f'{g} / {i//size+1}':ws[i:i+size] for g,ws in result.items() for i in range(0,len(ws),size)}
    return result


def _indexed_curves(df,index,kind,selected_periods,wells):
    out=[];chosen=set(wells)
    for period in index.periods.get(kind,[]):
        if period not in selected_periods:continue
        bucket=index.buckets[(kind,period)]
        if bucket is None:raise ValueError(f'Период {period} охватывает более 10 лет. Проверьте поле Сезон.')
        calendar,cumulative,available=bucket
        for well in available:
            if well not in chosen:continue
            g=df.iloc[index.groups[(kind,period,well)]].set_index('date').reindex(calendar)
            excluded=g['_excluded'].fillna(False).astype(bool) if '_excluded' in g else pd.Series(False,index=g.index)
            part=pd.DataFrame({'date':calendar,'well':well,'period':period,'cumulative':cumulative,
                'q':g.q.fillna(0).where(~excluded,np.nan).to_numpy()/1000,'missing':(g.q.isna()&~excluded).to_numpy()})
            for c in ('file','sheet','_row','_point_id'):part[c]=g[c].fillna('').to_numpy() if c in g else ''
            out.append(part)
    return pd.concat(out,ignore_index=True) if out else pd.DataFrame()
