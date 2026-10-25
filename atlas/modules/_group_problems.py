"""Проблемные скважины группы: вскрытие КРУ по сезонам и динамика отдачи по ГДИ (без интерфейса).

КРУ — перенос ядра «Авторского надзора» (``revision_report.analyse``): единица учёта — пара ГСП + номер скважины.
ГДИ — ``gdi_trend.histories`` и ``rating`` без изменений: рейтинг первого и последнего надёжного исследования.
Здесь только выбор групп и подсказки; подсказка всегда показывает причину, решение — за инженером.
"""
from __future__ import annotations

import pandas as pd

from ..engine.modules import revision_report as rr
from .gdi import select
from .gdi_trend import histories, rating

KRU_COLUMNS = ['gsp', 'well', 'seasons', 'known', 'streak', 'first', 'last', 'hint']
GDI_LAST_N = 6          # последние даты исследований по скважине, как в «Динамике коэффициентов ГДИ» по умолчанию


def gsps_of(groups: list[str] | None) -> set[str] | None:
    """Группы проекта («ГСП 1», «ГСП-1») → названия ГСП из вскрытия КРУ («ГСП-1»); пусто — все."""
    if not groups:
        return None
    return {rr.gsp_name(g) for g in groups if rr.gsp_name(g)}


def kru_table(dataset: rr.Dataset, groups: list[str] | None, min_streak: int) -> pd.DataFrame:
    """Скважины с вскрытием КРУ: сколько сезонов, сколько сезонов подряд (лет подряд), первый и последний сезон.
    Подсказка — если серия подряд не короче ``min_streak``; это не вывод о причине."""
    wanted = gsps_of(groups)
    rows = []
    for r in rr.analyse(dataset)['wells']:
        if wanted is not None and r['gsp'] not in wanted:
            continue
        hint = ''
        if r['streak'] >= min_streak:
            hint = f'вскрывалась {r["streak"]} сезона подряд (порог {min_streak})'
        rows.append({'gsp': r['gsp'], 'well': r['well'], 'seasons': r['k'], 'known': r['n'], 'streak': r['streak'],
                     'first': r['first'], 'last': r['last'], 'hint': hint})
    out = pd.DataFrame(rows, columns=KRU_COLUMNS)
    return out.sort_values(['streak', 'seasons', 'gsp'], ascending=[False, False, True]).reset_index(drop=True)


def gdi_table(gdi: pd.DataFrame, wells: list[str], r2: float, change: float) -> pd.DataFrame:
    """Рейтинг по ГДИ для скважин выбранных групп (пусто — все): изменение расхода при общем ΔP² и вердикт."""
    if gdi.empty:
        return pd.DataFrame()
    chosen = select(gdi, wells, [], GDI_LAST_N)
    history = histories(chosen, r2, []) if not chosen.empty else pd.DataFrame()
    if history.empty:
        return pd.DataFrame()
    return rating(history, change)
