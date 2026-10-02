from __future__ import annotations
import warnings
import numpy as np
import pandas as pd
from functools import lru_cache

KEYS=['well','date','method','study']

def fit(q,dp2):
    q=np.asarray(q,dtype=float); y=np.asarray(dp2,dtype=float)
    mask=np.isfinite(q)&np.isfinite(y)&(q>0)&(y>0)
    q=q[mask]; y=y[mask]
    if len(q)<2 or len(np.unique(q))<2:
        return None,None,None
    return _fit_cached(tuple(q),tuple(y))

@lru_cache(maxsize=4096)
def _fit_cached(q,y):
    from scipy.optimize import OptimizeWarning
    from .legacy_fit import LegacyFit
    q=np.asarray(q);y=np.asarray(y)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',OptimizeWarning)
        return LegacyFit().fit_trend_line(q,y)

def r_squared(q,y,a,b):
    if a is None or b is None or len(q)<2: return None
    total=float(np.sum((y-y.mean())**2))
    return float(1-np.sum((y-a*q-b*q*q)**2)/total) if total else 0.0

def free_flow(a,b,p_res):
    """Formal root at P_bh=0, stable for b near zero. Pressure units match input."""
    if any(v is None or not np.isfinite(v) for v in (a,b,p_res)) or a<0 or b<0 or p_res<=0 or a+b==0:
        return None
    dp2=p_res*p_res
    return float(2*dp2/(a+np.sqrt(a*a+4*b*dp2))) if b>0 else float(dp2/a)

def analyze_study(d,threshold=.95):
    valid=d.q.gt(0)&d.dp2.gt(0)&np.isfinite(d.q)&np.isfinite(d.dp2)
    q=d.loc[valid,'q'].to_numpy(float); y=d.loc[valid,'dp2'].to_numpy(float)
    ac,bc,rc=fit(q,y); ad=bd=None; notes=[]
    for col in ('a_db','b_db'):
        if col in d and d[col].dropna().nunique()>1: notes.append(f'Разные значения {col} внутри исследования')
    if all(c in d and d[c].notna().any() for c in ('a_db','b_db')):
        ad=float(d.a_db.dropna().iloc[0]); bd=float(d.b_db.dropna().iloc[0])
        if not np.isfinite(ad+bd) or min(ad,bd)<0 or ad+bd==0:
            notes.append('Некорректные коэффициенты БД'); ad=bd=None
    rd=r_squared(q,y,ad,bd)
    if ad is not None and rd is not None and rd>=threshold: a,b,r,source=ad,bd,rd,'БД'
    elif ac is not None and (ad is None or rc>=threshold): a,b,r,source=ac,bc,rc,'Расчет'
    elif ad is not None: a,b,r,source=ad,bd,rd,'БД (низкое качество)'
    else: a=b=r=None; source='Недостаточно данных'
    if len(np.unique(q))<2: notes.append('Нужны минимум два разных положительных Q')
    elif len(q)==2: notes.append('Только две точки: R² не подтверждает надежность двух коэффициентов')
    if r is not None and r<threshold: notes.append(f'R² ниже {threshold:g}')
    pres=None
    if 'p_res' in d:
        pv=d.p_res.dropna()
        if len(pv):
            pres=float(pv.median())
            if pv.max()-pv.min()>.01: notes.append('Qсв рассчитан по медиане Рпл; Рпл меняется внутри исследования')
    qfree=free_flow(a,b,pres) if r is not None and r>=threshold and len(np.unique(q))>=2 else None
    if pres is None: notes.append('Нет Рпл: Qсв не определяется')
    return dict(a=a,b=b,r2=r,source=source,a_calc=ac,b_calc=bc,r2_calc=rc,
                a_db=ad,b_db=bd,r2_db=rd,points=len(d),fit_points=len(q),
                q_observed=float(d.q.max()),q_free=qfree,p_res=pres,note='; '.join(notes))

def prepare(df):
    d=df.copy()
    for c in ('method','study','season'):
        if c not in d: d[c]=''
        d[c]=d[c].fillna('').astype(str)
    return d

def analyze(df,threshold=.95):
    d=prepare(df); results=[]
    for keys,g in d.groupby(KEYS,sort=True,dropna=False):
        result=dict(zip(KEYS,keys)); result.update(analyze_study(g,threshold)); results.append(result)
    return pd.DataFrame(results)

def select_studies(df,wells,n=0,seasons=None):
    from app.core.performance import select_wells
    d=prepare(select_wells(df,wells))
    if seasons: d=d[d.season.isin(seasons)]
    if n:
        # All methods and explicit study IDs from the last N dates stay distinct.
        selected=d[['well','date']].drop_duplicates().sort_values('date').groupby('well').tail(n)
        d=d.merge(selected,on=['well','date'],how='inner')
    return d

def compare_pair(new,old):
    """Same 10% point threshold as source, with paired Q/ΔP² sorting fixed."""
    def clean(d):
        d=d[d.q.gt(0)&d.dp2.gt(0)]
        return d.groupby('q',as_index=False).dp2.mean().sort_values('q')
    new=clean(new); old=clean(old)
    if len(new)<2 or len(old)<2: return 'Недостаточно данных',None
    lo=max(new.q.min(),old.q.min()); hi=min(new.q.max(),old.q.max())
    if lo>=hi: return 'Нет общего диапазона Q',None
    q=np.linspace(lo,hi,50)
    yn=np.interp(q,new.q,new.dp2); yo=np.interp(q,old.q,old.dp2)
    mean=float(np.mean([yn.mean(),yo.mean()])); delta=float((yn-yo).mean()/mean) if mean else None
    if delta is None: return 'Недостаточно данных',None
    return ('Без изменений' if abs(delta)<.1 else 'Улучшение' if delta<0 else 'Ухудшение'),delta*100

def comparisons(df):
    out=[]; d=prepare(df)
    # Do not compare different methods or combine different studies into one fit.
    for (well,method,study),g in d.groupby(['well','method','study'],dropna=False):
        ds=sorted(g.date.unique())
        if len(ds)<2: continue
        last=g[g.date.eq(ds[-1])]
        for dt in reversed(ds[:-1]):
            old=g[g.date.eq(dt)]
            if old.loc[old.q.gt(0)&old.dp2.gt(0),'q'].nunique()>=2: break
        status,delta=compare_pair(last,old)
        out.append({'Скважина':well,'Метод':method,'Исследование':study,'Новое':ds[-1],
                    'Предыдущее':dt,'Изменение ΔP², %':delta,'Результат':status})
    return pd.DataFrame(out)

def compare_three(df):
    rows=[]; d=prepare(df)
    for (well,method,study),g in d.groupby(['well','method','study'],dropna=False):
        dates=sorted(g.date.unique())[-3:]
        if len(dates)<3: continue
        old,previous,new=[g[g.date.eq(x)] for x in dates]
        n_p,_=compare_pair(new,previous); p_o,_=compare_pair(previous,old); n_o,_=compare_pair(new,old)
        status='Смешанная динамика'
        if n_p==p_o=='Улучшение': status='Последовательное улучшение'
        elif n_p==p_o=='Ухудшение': status='Последовательное ухудшение'
        elif n_p==p_o==n_o=='Без изменений': status='Стабильно'
        elif any('данных' in v or 'диапазона' in v for v in (n_p,p_o,n_o)): status='Недостаточно сопоставимых данных'
        rows.append({'Скважина':well,'Метод':method,'Исследование':study,'Раннее':dates[0],'Среднее':dates[1],'Последнее':dates[2],
                     'Последнее / среднее':n_p,'Среднее / раннее':p_o,'Последнее / раннее':n_o,'Динамика':status})
    return pd.DataFrame(rows)


def outlier_suggestions(df,threshold_percent=15):
    """Leave-one-out screening only. The engineer explicitly confirms exclusions."""
    rows=[]
    for keys,group in prepare(df).groupby(KEYS,sort=True,dropna=False):
        valid=group[group.q.gt(0)&group.dp2.gt(0)&np.isfinite(group.q)&np.isfinite(group.dp2)]
        if len(valid)<4:continue
        q=valid.q.to_numpy(float);y=valid.dp2.to_numpy(float)
        for i,(_,row) in enumerate(valid.iterrows()):
            keep=np.arange(len(valid))!=i
            a,b,r=fit(q[keep],y[keep])
            if a is None or r is None or r<.90:continue
            predicted=a*q[i]+b*q[i]**2
            if predicted<=0:continue
            percent=abs(y[i]-predicted)/predicted*100
            residual=np.abs(y[keep]-(a*q[keep]+b*q[keep]**2))/np.maximum(a*q[keep]+b*q[keep]**2,1e-12)*100
            if percent>=threshold_percent and percent>=3*max(float(np.median(residual)),1.):
                rows.append({**dict(zip(KEYS,keys)),'id':row.get('_point_id',''),'q':q[i],'dp2':y[i],
                    'expected_dp2':predicted,'deviation_percent':percent,'r2_without_point':r,
                    'reason':'Отклонение от подбора по остальным точкам; требуется проверка инженера'})
    return pd.DataFrame(rows)
