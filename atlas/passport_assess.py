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
DEP_STRONG_DATES = 2     # дат замера Рпл с превышением предела депрессии, с которых улика сильная
THRESHOLD_KEYS = ('dep_min_dates', 'elpro_high_share', 'elpro_drop')


def thresholds_of(settings: dict[str, Any] | None) -> dict[str, float]:
    """Пороги улик: умолчания, поверх них значения, которые инженер применил вручную после перебора порогов (``settings.passport_thresholds``)."""
    from atlas import passport_elpro
    out = {'dep_min_dates': float(DEP_STRONG_DATES), 'elpro_high_share': passport_elpro.HIGH_SHARE, 'elpro_drop': passport_elpro.DROP}
    for k, v in ((settings or {}).get('passport_thresholds') or {}).items():
        if k in out:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
    return out
def weights_of(settings: dict[str, Any] | None) -> dict[str, float]:
    """Веса, применённые инженером вручную после автоперебора (``settings.passport_weights``): множители механизмов и ``weak`` — баллы слабой улики."""
    out: dict[str, float] = {}
    for k, v in ((settings or {}).get('passport_weights') or {}).items():
        if k in MECHANISMS or k == 'weak':
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
    return out


# Таблица «механизм → операция» по умолчанию: что подсказывать при сильной и слабой улике. Инженер правит её в проекте (settings.well_operations);
# изменённая строка главнее подсказки, которую даёт автоматика по конкретному случаю.
DEFAULT_OPERATIONS: dict[str, dict[str, str]] = {
    'sand': {'strong': 'КР: замена фильтра / армирование ПЗП', 'weak': 'Специальное ГДИ или промывка'},
    'bottom_fill': {'strong': 'Промывка / КР по заполнению забоя', 'weak': 'Шаблонирование силами геологической службы или ГДИ'},
    'depression': {'strong': 'Снизить режим отбора, провести ГДИ', 'weak': 'Контролировать депрессию на следующем сезоне'},
    'throttle': {'strong': 'Проверить режим, шлейф и сопротивление КРУ', 'weak': 'Проверить режим и шлейф'},
    'gdi_old': {'strong': 'Провести ГДИ', 'weak': 'Провести ГДИ'},
}


def operations_of(settings: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    """Таблица операций: умолчания, поверх них правки инженера из ``settings.well_operations`` (пустой текст возвращает умолчание)."""
    mine = (settings or {}).get('well_operations') or {}
    return {m: {lvl: str((mine.get(m) or {}).get(lvl) or text) for lvl, text in levels.items()} for m, levels in DEFAULT_OPERATIONS.items()}


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


def sand_priority_at(sand_text: Any, works: list[dict[str, Any]], year: int) -> dict[str, Any] | None:
    """Приоритет КР по ревизиям КРУ на 1 января ``year`` (логика «Анализа ревизии КРУ»): число ревизий с песком после последнего ремонта,
    который сбрасывает счёт (замена фильтра, армирование ПЗП); 1 ревизия → 3, 2 → 2, 3 и больше → 1. Ревизия сезона «2023-2024» известна с весны 2024.
    Нет ни одной ревизии с песком — None."""
    from atlas.passport_tiles import sand_seasons, short_type
    resets = [w['year'] for w in works if w.get('year') is not None and short_type(str(w.get('type') or '')) in ('фильтр', 'армиров.')]
    after = max([y for y in resets if y < year], default=None)
    seen = [s for s in sand_seasons(sand_text) if int(s[5:]) < year and (after is None or int(s[5:]) > after)]
    if not seen:
        return None
    return {'value': float(max(1, 4 - len(seen))), 'reason': f'ревизий с песком после последнего ремонта со сбросом: {len(seen)} ({", ".join(seen)})'}


def collect(*, bottom_m: float | None, bottom_date: Any, bottom_row: Any, filter_bottom_m: float | None, krs: dict[str, Any], seasons: list[dict[str, Any]],
            gdi: list[dict[str, Any]], elpro: list[dict[str, Any]], today: Any, depression: list[dict[str, Any]] | None = None, dep_min_dates: float = DEP_STRONG_DATES) -> list[wa.Evidence]:
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
        many = last_dep['n_over'] >= dep_min_dates        # одна дата выше предела может быть случайностью замера: это слабая улика
        detail = (f'выше предела {last_dep["n_over"]} из {last_dep["n"]} дат замера Рпл ({last_dep["share_over"] * 100:.0f} %), максимум '
                  f'{last_dep["dep_max"]:.2f} на {last_dep["p_date"]}') if over else f'максимум {last_dep["dep_max"]:.2f} на {last_dep["p_date"]}, близко к пределу'
        out.append(wa.Evidence('depression', 'strong' if many else 'weak', f'Сезон {last_dep["period"]}: депрессия {detail} при пределе {last_dep["limit"]:g} '
                               f'кгс/см²; {last_dep["note"]}.', '', 1.0, 'Снизить режим отбора по скважине (риск выноса песка), проверить ГДИ.'))
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


def rows(evidence: list[wa.Evidence], manual: dict[str, Any] | None, edited: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Строки для экрана: уровень авто и итоговый, ручное решение главнее; причина и подсказка операции остаются видны."""
    manual = manual or {}
    edited = edited or {}
    shown = []
    for e in evidence:
        m = manual.get(e.mechanism) or {}
        level = m.get('level') if m.get('level') in wa.LEVELS else e.level
        own = str((edited.get(e.mechanism) or {}).get(level) or '')       # строка таблицы «механизм → операция», правленная инженером
        shown.append({'mechanism': e.mechanism, 'name': MECHANISMS.get(e.mechanism, e.mechanism), 'auto_level': e.level, 'level': level,
                      'manual': bool(m.get('level') in wa.LEVELS), 'note': str(m.get('note') or ''), 'reason': e.reason, 'date': e.data_date,
                      'weight': round(e.weight, 2), 'recommendation': own or e.recommendation})
    for mech, m in manual.items():           # ручное решение по механизму без авто-улики — тоже показывается
        if mech in MECHANISMS and m.get('level') in wa.LEVELS and not any(s['mechanism'] == mech for s in shown):
            shown.append({'mechanism': mech, 'name': MECHANISMS[mech], 'auto_level': 'none', 'level': m['level'], 'manual': True, 'note': str(m.get('note') or ''),
                          'reason': 'Автоматической улики нет, решение инженера.', 'date': '', 'weight': 1.0, 'recommendation': ''})
    order = {'strong': 0, 'weak': 1, 'unknown': 2, 'none': 3}
    return sorted(shown, key=lambda s: order.get(s['level'], 9))


def today_stamp() -> str:
    return datetime.now().strftime('%d.%m.%Y')
