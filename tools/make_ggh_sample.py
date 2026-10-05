"""Синтетическая книга ГГХ в формате листа «Общий» отчёта (для примера и тестов импорта и выгрузки в Word).

Usage: python tools/make_ggh_sample.py OUT.xlsx [WELLS] [SEED]
Данные выдуманные; в книге есть «неудобные» строки, как в настоящих: число с запятой, повтор даты, строка без даты,
строка «неиспользуемые данные», текст вместо числа.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HEADER = ['№№ скв.', 'Дата отбора', 'Водоносный горизонт', 'Уровень', 'Глубина отбора проб,(м)', 'Способ отбора проб',
          'Газонасыщенность, см³/л', 'СН4', 'С2Н6', 'С3Н8', 'С4Н10+ТУ', 'Сумма УВ', 'Не', 'Н2', 'N2', 'O2', 'СО2', 'СО',
          'Сумма анализа']
HORIZONS = ['Щигровский', 'Ряжский', 'Окско-серпуховский', 'Касимовский']


def make_rows(wells: int = 4, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(wells):
        well, horizon = str(160 + k * 7), HORIZONS[k % len(HORIZONS)]
        for date in pd.date_range('2008-04-15', periods=int(rng.integers(6, 14)), freq='190D'):
            hc = float(rng.uniform(40, 97))
            n2 = float(rng.uniform(1, 100 - hc))
            rest = 100 - hc - n2
            rows.append([well, date.to_pydatetime(), horizon, round(float(rng.uniform(5, 60)), 1), 950, 'твд',
                         int(rng.integers(80, 800)), hc * .9, .05, .02, .01, round(hc, 2), round(float(rng.uniform(0, .1)), 4),
                         round(rest * .4, 2), round(n2, 2), round(rest * .2, 2), round(rest * .4, 2), None, 100.0])
    return pd.DataFrame(rows, columns=HEADER)


def make_book(path, wells: int = 4, seed: int = 1, messy: bool = True) -> None:
    frame = make_rows(wells, seed)
    if messy:
        for column in ('Газонасыщенность, см³/л', 'Уровень'):
            frame[column] = frame[column].astype(object)
        frame.loc[1, 'Газонасыщенность, см³/л'] = '350,5'               # запятая вместо точки
        frame.loc[2, 'Уровень'] = 'перелив'                               # текст вместо числа
        frame = pd.concat([frame, frame.iloc[[3]]], ignore_index=True)    # повтор «скважина + дата»
        frame = pd.concat([frame, pd.DataFrame([['999', pd.NaT] + [None] * 17], columns=HEADER)], ignore_index=True)
        frame = pd.concat([frame, pd.DataFrame([['неиспользуемые данные', pd.Timestamp('2020-01-01')] + [None] * 17],
                                               columns=HEADER)], ignore_index=True)
    with pd.ExcelWriter(path) as xl:
        pd.DataFrame().to_excel(xl, sheet_name='Прил. 6.1', index=False)
        frame.to_excel(xl, sheet_name='Общий', index=False)


if __name__ == '__main__':
    out = Path(sys.argv[1])
    make_book(out, int(sys.argv[2]) if len(sys.argv) > 2 else 4, int(sys.argv[3]) if len(sys.argv) > 3 else 1)
