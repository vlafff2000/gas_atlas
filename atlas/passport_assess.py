"""Блок «Оценка состояния» паспорта: улики ядра ``well_assess`` и данных паспорта + ручное решение инженера.

Расчётов здесь нет: сбор входов из карточки, перевод улик в строки таблицы и наложение ручных решений. Автоматика — подсказка, строка с
ручным решением главнее и помечается; пересчёт её не затирает (хранится в ``settings.well_assess``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from atlas import well_assess as wa

MECHANISMS = {'depression': 'Превышение предельной депрессии', 'bottom_fill': 'Заполнение забоя', 'sand': 'Вынос песка (ревизии КРУ)', 'throttle': 'Ограничение устья / КРУ', 'gdi_old': 'Устаревшее ГДИ'}
LEVEL_NAMES = {'none': 'нет', 'weak': 'слабая', 'strong': 'сильная', 'unknown': 'неизвестно'}
GDI_OLD_YEARS = 5.0


def bottom_source(row: Any) -> str:
    """Источник замера забоя по тексту столбцов метода/источника БД шаблонирования; нет текста — ``unknown``."""
    if row is None:
        return 'unknown'
    text = ' '.join(str(row.get(c, '') or '') for c in ('method', 'origin', 'source', 'comment')).lower().strip()
    if not text or text == 'nan':
        return 'unknown'
    # «Комментарий» листа «Замеры забоя» БД шаблонирования: «<вид>; <источник данных>; …». Свои Excel = шаблонирование геологической службы,
    # «БД ГИС из отчётов» / «Отчёт ГИС» = отчёты ГИС; конструкции из Word и решения инженера — прочее.
    if 'геолог' in text or 'excel' in text or ('шаблон' in text and 'гис' not in text):
        return 'geo_template'
    return 'gis_report' if 'гис' in text else 'other'


def _last_kr_year(works: list[dict[str, Any]]) -> int | None:
    years = [w['year'] for w in works if w.get('year') is not None and 'ТР' not in str(w.get('type') or '').upper().split()]
    return max(years) if years else None


def collect(*, bottom_m: float | None, bottom_date: Any, bottom_row: Any, filter_bottom_m: float | None, krs: dict[str, Any], seasons: list[dict[str, Any]],
            gdi: list[dict[str, Any]], elpro: list[dict[str, Any]], today: Any, depression: list[dict[str, Any]] | None = None) -> list[wa.Evidence]:
    """Улики по скважине в порядке важности: забой, песок и ревизии, ЭЛПРО, возраст ГДИ."""
    out: list[wa.Evidence] = []
    if bottom_date is not None and pd.isna(bottom_date):
        bottom_date = None
    last_kr = _last_kr_year(krs.get('works') or [])
    bottom = wa.bottom_evidence(bottom_m, bottom_date, filter_bottom_m, last_kr, seasons, gdi, bottom_source(bottom_row), today)
    if bottom:
        out.append(bottom)
    last_dep = next((r for r in reversed(depression or []) if r['status'] in ('превышен', 'близко', 'норма')), None)
    if last_dep and last_dep['status'] != 'норма':
        over = last_dep['status'] == 'превышен'
        out.append(wa.Evidence('depression', 'strong' if over else 'weak',
                               f'Сезон {last_dep["period"]}: депрессия на максимальном расходе {last_dep["dep_max"]:.2f} кгс/см² при пределе {last_dep["limit"]:g} '
                               f'({"предел превышен" if over else "близко к пределу"}); {last_dep["note"]}.', '', 1.0,
                               'Снизить режим отбора по скважине (риск выноса песка), проверить ГДИ.'))
    pr = (krs.get('priority') or {})
    value = pr.get('value')
    if value is not None:
        level = 'strong' if value <= 1 else 'weak'
        out.append(wa.Evidence('sand', level, f'Приоритет КР {value:g} по ревизиям КРУ' + (f': {pr["reason"]}' if pr.get('reason') else ''), '', 1.0,
                               'КР: замена фильтра / армирование ПЗП; при слабых уликах — ГДИ или промывка.'))
    if elpro:
        last = next((r for r in reversed(elpro) if r['verdict'] in ('норма', 'внимание')), None)
        if last and last['verdict'] == 'внимание':
            out.append(wa.Evidence('throttle', 'weak', f'Сезон {last["period"]}: {last["reason"]}.', '', 1.0, 'Проверить режим, шлейф и сопротивление; не КР, пока не подтвердится ГДИ.'))
    good = [wa._day(g.get('date')) for g in gdi if g.get('reliable') and wa._day(g.get('date'))]
    t = wa._day(today)
    if t and (not good or (t - max(good)).days > GDI_OLD_YEARS * 365):
        age = 'надёжных ГДИ нет' if not good else f'последнее надёжное ГДИ {max(good):%d.%m.%Y}'
        out.append(wa.Evidence('gdi_old', 'weak', f'{age}: сравнивать продуктивность не с чем.', f'{max(good):%d.%m.%Y}' if good else '', 1.0, 'Провести ГДИ.'))
    return out


def rows(evidence: list[wa.Evidence], manual: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Строки для экрана: уровень авто и итоговый, ручное решение главнее; причина и подсказка операции остаются видны."""
    manual = manual or {}
    shown = []
    for e in evidence:
        m = manual.get(e.mechanism) or {}
        level = m.get('level') if m.get('level') in wa.LEVELS else e.level
        shown.append({'mechanism': e.mechanism, 'name': MECHANISMS.get(e.mechanism, e.mechanism), 'auto_level': e.level, 'level': level,
                      'manual': bool(m.get('level') in wa.LEVELS), 'note': str(m.get('note') or ''), 'reason': e.reason, 'date': e.data_date,
                      'weight': round(e.weight, 2), 'recommendation': e.recommendation})
    for mech, m in manual.items():           # ручное решение по механизму без авто-улики — тоже показывается
        if mech in MECHANISMS and m.get('level') in wa.LEVELS and not any(s['mechanism'] == mech for s in shown):
            shown.append({'mechanism': mech, 'name': MECHANISMS[mech], 'auto_level': 'none', 'level': m['level'], 'manual': True, 'note': str(m.get('note') or ''),
                          'reason': 'Автоматической улики нет, решение инженера.', 'date': '', 'weight': 1.0, 'recommendation': ''})
    order = {'strong': 0, 'weak': 1, 'unknown': 2, 'none': 3}
    return sorted(shown, key=lambda s: order.get(s['level'], 9))


def today_stamp() -> str:
    return datetime.now().strftime('%d.%m.%Y')
