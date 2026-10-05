from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]
STORAGE = Path(os.environ.get('GAS_ATLAS_STORAGE', ROOT / 'storage')).resolve()
VERSION = '5.8.0-py3820'
MODULES = {'production': 'Производительность скважин', 'histograms':'Гистограммы по эксплуатации скважин', 'gdi': 'ГДИ', 'response': 'Графики реагирования', 'object_pressure':'Давление объекта',
           'operations':'Суточная эксплуатация', 'water':'Контроль воды', 'bottom':'Замеры забоя',
           'construction':'Конструкция', 'well_dashboard':'Поскважинный анализ', 'pressure_match':'Кроссплот давлений', 'plan':'План по группам', 'ggh':'ГГХ'}
COLORS = ['#dc3545', '#2563eb', '#169b62', '#ed8b23', '#9955cc', '#149ba5', '#bd548d', '#8c7542']
DEFAULT_SETTINGS = {'season_start': 11, 'season_end': 4, 'r2_threshold': 0.95,
                    'working_horizons': [], 'pressure_unit': 'кгс/см²', 'panels': {},
                    'manometer_wells':[], 'object_pressure_horizons':[],
                    'chart_style':{'grid':True,'legend':True,'autoscale':True}}

def natural_key(value):
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(value))]

def ordered(values):
    return sorted(set(str(v) for v in values), key=natural_key)
