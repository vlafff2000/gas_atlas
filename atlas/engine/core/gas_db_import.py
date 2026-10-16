"""«БД по учету газа» (База ПХГ, лист «БД») → таблица суточных данных по объекту для Атласа.

Одна строка — сутки режима (отбор или закачка). Берём три величины: суточный объём по объекту (тыс. м³/сут),
вынос пластовой жидкости по объекту (м³, только в сутки с замером) и дату. Названия столбцов ищутся по подстроке,
как в all_scripts (pxg_base/modules/Нормировка_базы_расходов_на_ПЗРГ.py): столбец должен найтись ровно один раз,
иначе файл не принимается — лучше ошибка, чем тихий выбор не того параметра.

Вход: xlsx с листом «БД». Значения по объекту — приоритетные: это основной источник суточных объёмов.
Главные колонки базы пишутся под каноническими именами (словарь pxg_core/имена_бд_газа.py в all_scripts; здесь
те же строки). Старые выгрузки с исходными названиями читаются по подстроке, как раньше.
"""
from __future__ import annotations

import pandas as pd

SHEET = 'БД'
WITHDRAW_TOTAL = 'Всего по ПЗРГ - за сутки по ПХГ'      # отбор, тыс. м³/сут
INJECT_TOTAL = 'Закачано в ПХГ за СУТКИ, тыс.м3/сут'     # закачка, тыс. м³/сут
WATER = 'Пластовая жидкость (м3) / Всего по ПХГ'        # вынос воды по объекту, м³ (сутки с замером)
# канонические имена главных колонок «БД по учету газа» (те же, что в all_scripts, pxg_core/имена_бд_газа.py)
CANON_WITHDRAW = 'Отбор из ПХГ, тыс. м³/сут'
CANON_INJECT = 'Закачка в ПХГ, тыс. м³/сут'
CANON_WATER = 'Добыча пластовой воды, м³/сут'
KIND_OF = {'отбор': 'withdrawal', 'закачка': 'injection'}
COLUMNS = ['kind', 'date', 'gas', 'water']


def _one(columns, part: str, canonical: str = '') -> str:
    if canonical and canonical in list(columns):
        return canonical
    hits = [c for c in columns if part in str(c)]
    if len(hits) != 1:
        raise ValueError(f'В «БД по учету газа» столбец «{part}» найден {len(hits)} раз: проверьте лист «БД»')
    return hits[0]


def build(path) -> pd.DataFrame:
    """Таблица (kind, date, gas, water) по суткам. ``gas`` — тыс. м³/сут, ``water`` — м³ или NaN (нет замера)."""
    db = pd.read_excel(path, sheet_name=SHEET)
    total_w = _one(db.columns, WITHDRAW_TOTAL, CANON_WITHDRAW)
    total_i = _one(db.columns, INJECT_TOTAL, CANON_INJECT)
    water_col = _one(db.columns, WATER, CANON_WATER)
    mode = db['Режим'].astype(str).str.strip().str.lower()
    gas = pd.Series(float('nan'), index=db.index)
    gas[mode.eq('отбор')] = pd.to_numeric(db.loc[mode.eq('отбор'), total_w], errors='coerce')
    gas[mode.eq('закачка')] = pd.to_numeric(db.loc[mode.eq('закачка'), total_i], errors='coerce')
    out = pd.DataFrame({
        'kind': mode.map(KIND_OF),
        'date': pd.to_datetime(db['Дата'], errors='coerce').dt.normalize(),
        'gas': gas,
        'water': pd.to_numeric(db[water_col], errors='coerce'),
    })
    out = out[out['kind'].notna() & out['date'].notna()]
    return out.drop_duplicates(['kind', 'date'], keep='last').sort_values(['kind', 'date']).reset_index(drop=True)
