"""Deterministic synthetic data, always labeled as demonstration."""
import numpy as np
import pandas as pd

def demo_frames():
    production=[]; gdi=[]; response=[]; wells=['31','45','70','73','89','132','540','541']
    for year in (2023,2024,2025):
        for kind,start,days in [('withdrawal',f'{year}-11-01',180),('injection',f'{year}-05-01',150)]:
            for i,w in enumerate(wells):
                for t,date in enumerate(pd.date_range(start,periods=days)):
                    if w=='73' and t in (30,31): continue
                    q=(65+18*i)*(1-.35*t/days)*(1+.04*np.sin(t/6+i))*(1+.03*(year-2023))*1000
                    if i%3==0 and 50<t<55: q=0
                    production.append(dict(well=w,date=date,q=round(q,2),kind=kind,season=f'{year}-{year+1}' if kind=='withdrawal' else '',year='',group='ГСП 2' if i<3 else 'ГСП 9',subgroup=str(i//3+1),file='Демонстрация',sheet=kind,_row=t+2))
        for i,w in enumerate(wells):
            a=.7+i*.1; b=.012*(1-.04*(year-2023)); pres=75.+i*.4
            for j,q in enumerate([45.,90.,140.,190.,230.]):
                dp2=a*q+b*q*q
                gdi.append(dict(well=w,date=pd.Timestamp(f'{year}-12-10'),q=q,p_res=pres,p_bh=np.sqrt(pres*pres-dp2),dp2=dp2,
                    a_db=a*1.01,b_db=b,method='Установившиеся отборы',study='',season=f'{year}-{year+1}',group='ГСП 2' if i<3 else 'ГСП 9',subgroup='',file='Демонстрация',sheet='ГДИ',_row=j+2))
    for i,w in enumerate(wells):
        horizon=['Окский','Бобриковский','Турнейский'][i%3]
        for t,date in enumerate(pd.date_range('2023-01-01',periods=44,freq='MS')):
            response.append(dict(well=w,date=date,horizon=horizon,level=35+i*4+6*np.sin(t/4+i),pressure=70+i/2+2*np.cos(t/5),
                group='ГСП 2' if i<3 else 'ГСП 9',subgroup='',file='Демонстрация',sheet='Реагирование',_row=t+2))
    return {k:pd.DataFrame(v) for k,v in [('production',production),('gdi',gdi),('response',response)]}


def well_demo_frames():
    """Full well-history demo; it never fills real projects with invented measurements."""
    frames=demo_frames();p=frames['production'];operations=[];bottom=[];construction=[];water=[]
    wells=p.well.drop_duplicates().tolist()
    for i,well in enumerate(wells):
        d=p[p.well.eq(well)&p.kind.eq('withdrawal')]
        for _,r in d.iterrows():
            wet=r.date>=pd.Timestamp('2025-12-15') and i%3==0
            operations.append({'well':well,'date':r.date,'kind':r.kind,'work_hours':22. if r.q>0 else 0.,
                'gas_volume_m3':r.q,'water_volume_m3':1.2 if wet and r.q>0 else 0.,'water_flag':'Да' if wet else 'Нет',
                'p_res':75+i*.4,'p_bh':55+i*.3,'p_wellhead':48+i*.2,'p_line':43.,'temperature':18.,
                'season':r.season,'group':r.group,'subgroup':r.subgroup,'comment':'Синтетический пример'})
        for date,depth in [('2023-11-01',1300),('2024-11-01',1297),('2025-11-01',1292),('2026-02-01',1285)]:
            bottom.append({'well':well,'date':pd.Timestamp(date),'bottom_m':depth+i*2,'tool_diameter_mm':58.,'method':'Шаблонировка','comment':'Синтетический пример'})
        for element,top,low,diam,inner in [('Эксплуатационная колонна',0,1300,146,128),('НКТ',0,1240,73,62),('Перфорация',1260,1290,np.nan,np.nan),('Пакер',1220,1220,128,np.nan)]:
            construction.append({'well':well,'date':pd.Timestamp('2023-11-01'),'element':element,'top_m':top,'bottom_m':low+i*2 if low>0 else low,'diameter_mm':diam,'inner_diameter_mm':inner,'comment':'Синтетический пример'})
        for date in pd.date_range('2025-11-01','2026-04-01',freq='MS'):
            wet=date>=pd.Timestamp('2026-01-01') and i%3==0
            water.append({'well':well,'date':date,'water_flag':'Да' if wet else 'Нет','water_rate':1.2 if wet else 0.,'salinity_g_l':80. if wet else np.nan,'comment':'Синтетический пример'})
    for name,rows in [('operations',operations),('water',water),('bottom',bottom),('construction',construction)]:
        d=pd.DataFrame(rows)
        for col in ('season','year','group','subgroup','method','study'):
            if col not in d:d[col]='Без группы' if col=='group' else ''
        d['file']='Демонстрация';d['sheet']=name;d['_row']=range(2,len(d)+2);frames[name]=d
    return frames
