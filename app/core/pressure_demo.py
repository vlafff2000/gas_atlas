"""Demonstration pressure books for the crossplot (fact + models + fonds), always labeled as demonstration.

The books are ordinary Excel files in the layouts the quick import recognizes, so a variant can be downloaded and
loaded through the import like real data. ``frame`` runs the same books through ``pressure_import`` — the demo data
saved into a demonstration project is exactly what the import would produce.
"""
import hashlib
import io
import numpy as np
import pandas as pd

# variant: (title, description, objects); object: (name, exploitation wells, observation wells, scenarios, layout)
# scenario: (sheet name, bias kgf/cm², noise, amplitude factor)
VARIANTS={
    'basic':('Один объект: факт и две модели',
        'Матрица «дата × скважина», 8 эксплуатационных и 3 наблюдательные скважины, 2019–2025.',
        [('ПХГ Демонстрационное',['31','45','70','73','89','132','540','541'],['601','602','603'],
          [('Модель базовая',0.,1.5,1.),('Модель 2025',2.5,3.,1.15)],'wide')]),
    'objects':('Три объекта: сценарии, фонды, пропуски',
        'Три книги, по три сценария; одна книга в строках «скважина / дата / давление»; есть пропуски и нулевые замеры.',
        [('ПХГ Северное',['11','12','14','15','17','21','22','25','27','30'],['91','92'],
          [('Модель базовая',0.,1.5,1.),('Модель уточненная',-.8,1.,1.),('Модель прогноз',3.5,3.5,1.25)],'wide'),
         ('ПХГ Южное',['101','103','104','106','108','110'],['190','191','192'],
          [('Модель базовая',1.,2.,.9),('Модель уточненная',.3,1.2,1.),('Модель прогноз',-4.,4.,.8)],'long'),
         ('ПХГ Западное',['201','202','205','207','209','211','212','215'],['290'],
          [('Модель базовая',-1.5,2.5,1.1),('Модель уточненная',-.5,1.5,1.),('Модель прогноз',2.,3.,1.2)],'wide')]),
    'large':('Крупный объект: 150 скважин',
        'Одна книга, 140 эксплуатационных и 10 наблюдательных скважин, ежемесячно 2016–2025, две модели (около 17 000 пар).',
        [('ПХГ Крупное',[str(1000+i) for i in range(140)],[str(1900+i) for i in range(10)],
          [('Модель базовая',0.,2.,1.),('Модель 2025',1.5,2.5,1.1)],'wide')]),
}
DEFAULT='basic'
START={'basic':'2019-01-01','objects':'2018-01-01','large':'2016-01-01'}

def variants():
    return [{'value':k,'label':v[0],'description':v[1],'books':[o[0]+'.xlsx' for o in v[2]]} for k,v in VARIANTS.items()]

def _variant(name):
    if name not in VARIANTS:raise KeyError('Нет такого демонстрационного варианта')
    return VARIANTS[name]

def _object_tables(variant,index,obj):
    """Fact (sparse for exploitation wells, monthly for observation ones), models and fonds of one object."""
    name,wells,observation,scenarios,_=obj
    rng=np.random.default_rng(1000*index+len(variant))
    months=pd.date_range(START[variant],'2025-12-01',freq='MS');t=np.arange(len(months))
    # Storage cycle: injection April–October raises the pressure, withdrawal lowers it; slow drift over years.
    season=np.sin(2*np.pi*(months.month.values-5)/12)
    every=wells+observation;truth={};fact={};models={s[0]:{} for s in scenarios}
    for j,w in enumerate(every):
        watch=w in observation
        base=78+6*np.sin(j*1.7)+(-6 if watch else 0);amp=(9 if watch else 14)*(1+.15*np.cos(j))
        p=base+amp*season-.04*t+rng.normal(0,.6,len(t));truth[w]=p
        measured=np.ones(len(t),bool) if watch else rng.random(len(t))<.45
        values=np.where(measured,np.round(p+rng.normal(0,1.,len(t)),2),np.nan)
        if not watch and j%4==1:values[rng.integers(0,len(t),2)]=0.   # zero readings: skipped by «Без нулевых давлений»
        fact[w]=values
        for sheet,bias,noise,factor in scenarios:
            m=base+amp*factor*season-.04*t+bias+rng.normal(0,noise,len(t))
            if j%7==3:m=m+rng.normal(0,noise*2)                           # a few wells the model fits poorly
            models[sheet][w]=np.round(m,2)
    fonds=pd.DataFrame({'Скважина':every,'Тип скважины':['Наблюдательная' if w in observation else 'Эксплуатационная' for w in every]})
    return months,fact,models,fonds

def _sheet(months,values,layout):
    if layout=='wide':
        table=pd.DataFrame({'Дата':months});table=pd.concat([table,pd.DataFrame(values)],axis=1)
        return table
    rows=pd.DataFrame([(w,d,v) for w,col in values.items() for d,v in zip(months,col) if not np.isnan(v)],
        columns=['Скважина','Дата','Давление, кгс/см2'])
    return rows.sort_values(['Скважина','Дата'],kind='stable').reset_index(drop=True)

def books(variant=DEFAULT):
    """[(file name, xlsx bytes)] — one book per object: «Факт», a sheet per model, «Фонд»."""
    out=[]
    for i,obj in enumerate(_variant(variant)[2]):
        months,fact,models,fonds=_object_tables(variant,i,obj);layout=obj[4]
        buffer=io.BytesIO()
        with pd.ExcelWriter(buffer,engine='openpyxl') as writer:
            _sheet(months,fact,layout).to_excel(writer,sheet_name='Факт',index=False)
            for sheet,values in models.items():_sheet(months,values,layout).to_excel(writer,sheet_name=sheet,index=False)
            fonds.to_excel(writer,sheet_name='Фонд',index=False)
        out.append((obj[0]+'.xlsx',buffer.getvalue()))
    return out

def frame(variant=DEFAULT):
    """The crossplot table of a variant, built from its books by the quick import (same as loading them by hand)."""
    from app.core import pressure_import as pq
    files={};cache={}
    for name,content in books(variant):
        sha=hashlib.sha256(content+name.encode()).hexdigest();files[sha]=(name,content);cache[sha]=pq.parse_file(name,content)
    rows=pq.build_rows(files,cache,{},'Демонстрационный объект')
    data,_,errors,_,_=pq.assemble(rows,cache,'first')
    if errors:raise ValueError('; '.join(errors))
    return data
