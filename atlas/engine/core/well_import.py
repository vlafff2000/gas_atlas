"""Explicit well history schemas. Unknown observations stay unknown."""
import numpy as np
import pandas as pd

ALIASES={
 'work_hours':['Часы работы','Отработано часов','work_hours'],
 'gas_volume_m3':['Объем газа','Суточный объем газа','gas_volume_m3'],
 'water_volume_m3':['Объем воды','Суточный объем воды','water_volume_m3'],
 'water_rate':['Расход воды','water_rate'],
 'water_flag':['Обводненность','Водопроявление','Наличие воды','water_flag'],
 'salinity_g_l':['Минерализация','salinity_g_l'],
 'bottom_m':['Текущий забой','Отбитый забой','Низ интервала','bottom_m'],
 'top_m':['Верх интервала','top_m'],
 'tool_diameter_mm':['Диаметр шаблона','tool_diameter_mm'],
 'element':['Элемент','Тип элемента','element'],
 'diameter_mm':['Наружный диаметр','Диаметр','diameter_mm'],
 'inner_diameter_mm':['Внутренний диаметр','inner_diameter_mm'],
 'p_wellhead':['Устьевое давление','p_wellhead'],
 'p_line':['Давление в шлейфе','p_line'],
 'temperature':['Температура','temperature'],
 'status':['Состояние','Статус','status'],
 'comment':['Комментарий','Примечание','comment']}
REQUIRED={'operations':{'well','date'},'water':{'well','date'},
          'bottom':{'well','date','bottom_m'},'construction':{'well','date','element','top_m','bottom_m'}}
NUMERIC=['work_hours','gas_volume_m3','water_volume_m3','water_rate','salinity_g_l','bottom_m','top_m',
         'tool_diameter_mm','diameter_mm','inner_diameter_mm','p_wellhead','p_line','temperature']

def detect(mapping):
    if not {'well','date'}<=mapping.keys():return None
    if {'element','top_m','bottom_m'}<=mapping.keys():return 'construction'
    if 'bottom_m' in mapping:return 'bottom'
    if ('work_hours' in mapping or 'gas_volume_m3' in mapping or 'water_volume_m3' in mapping) and 'q' not in mapping:return 'operations'
    if ('water_rate' in mapping or 'water_flag' in mapping) and 'q' not in mapping and 'work_hours' not in mapping:return 'water'
    return None

def normalize(df,module,reasons,numeric):
    for col in NUMERIC:
        if col not in df:continue
        supplied=df[col].notna()&df[col].astype(str).str.strip().ne('')
        df[col]=numeric(df[col])
        reasons.loc[supplied&df[col].isna()]='Некорректное число в поле '+col
    for col in NUMERIC:
        if col in df and col!='temperature':reasons.loc[df[col].lt(0)]='Отрицательное значение в поле '+col
    if 'water_flag' in df:
        flags=df.water_flag.fillna('').astype(str).str.strip().str.lower().str.replace('ё','е',regex=False).str.replace(r'\.0$','',regex=True)
        values={'да':'Да','yes':'Да','true':'Да','1':'Да','есть':'Да','нет':'Нет','no':'Нет','false':'Нет','0':'Нет',
                'неизвестно':'Неизвестно','unknown':'Неизвестно','':'Неизвестно'}
        reasons.loc[~flags.isin(values)]='Обводненность: допустимы Да, Нет, Неизвестно или пустое значение'
        df['water_flag']=flags.map(values).fillna('Неизвестно')
    if module=='operations':
        if 'work_hours' not in df:df['work_hours']=np.nan
        reasons.loc[df.work_hours.notna()&~df.work_hours.between(0,24)]='Часы работы должны быть числом от 0 до 24 либо пустыми'
        for col in ('gas_volume_m3','water_volume_m3','p_res','p_bh','p_wellhead','p_line','temperature'):
            if col not in df:df[col]=np.nan
        if 'water_flag' not in df:df['water_flag']='Неизвестно'
        present=df[['work_hours','gas_volume_m3','water_volume_m3','p_res','p_bh','p_wellhead','p_line','temperature']].notna().any(axis=1)|df.water_flag.isin(['Да','Нет'])
        reasons.loc[~present]='Нет ни одного показателя суточной эксплуатации'
    elif module=='water':
        if 'water_flag' not in df:df['water_flag']='Неизвестно'
        if 'water_rate' not in df:df['water_rate']=np.nan
        reasons.loc[df.water_flag.eq('Неизвестно')&df.water_rate.isna()]='Нужен расход воды либо явный признак Да/Нет'
    elif module=='bottom':
        reasons.loc[df.bottom_m.isna()|df.bottom_m.le(0)]='Текущий забой должен быть положительной глубиной в метрах'
    elif module=='construction':
        df['element']=df.element.fillna('').astype(str).str.strip()
        reasons.loc[df.element.eq('')]='Не указан элемент конструкции'
        reasons.loc[df.top_m.isna()|df.bottom_m.isna()|df.top_m.lt(0)|df.bottom_m.lt(df.top_m)]='Интервал: 0 ≤ верх ≤ низ, глубины в метрах'
        for col in ('diameter_mm','inner_diameter_mm'):
            if col not in df:df[col]=np.nan
            reasons.loc[df[col].le(0)]='Диаметр должен быть положительным либо пустым'
        reasons.loc[df.inner_diameter_mm.notna()&df.diameter_mm.notna()&df.inner_diameter_mm.gt(df.diameter_mm)]='Внутренний диаметр больше наружного'
    return df
