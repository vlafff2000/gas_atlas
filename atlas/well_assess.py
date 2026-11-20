"""Ядро комплексной оценки скважины: улики с датой и свежестью, без интерфейса (вариант C плана ``well-assessment/plan.md``).

Принципы: каждая улика — факт с датой, уровнем и причиной словами; замер до последнего КР не описывает скважину после ремонта и в оценку
текущего состояния не идёт; пропуск данных — «неизвестно», не «хорошо». Результат — подсказка, любую улику инженер переписывает вручную.
Здесь пока одна улика — «недоход до низа фильтра» (правило Egor 2026-11-20); остальные добавляются тем же видом ``Evidence``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

TAU_DAYS = 365          # свежесть замера затухает за год: вес = exp(-возраст / TAU)
HARD_DAYS = 730         # старше двух лет — только справочно
OVERLAP_TOL_M = 1.0     # недоход до низа фильтра меньше метра — разброс замера
DROP = 0.85             # показатель после замера ≤ 85 % от показателя до замера — снижение
STABLE = 0.90           # не ниже 90 % — стабильно
GDI_WORSE = 1.10        # Δp² при одном расходе выросла на 10 % — ГДИ хуже
NEAR_DAYS = 400         # «ГДИ рядом»: не дальше года (с запасом) от замера забоя
LEVELS = ('none', 'weak', 'strong', 'unknown')
SOURCES = {'gis_report': 'отчёт ГИС (шаблон / доход прибора)', 'geo_template': 'шаблонирование силами геологической службы', 'other': 'другой источник',
           'unknown': 'источник неизвестен'}      # источники БД шаблонирования, их нужно различать: у них разный смысл недохода


@dataclass
class Evidence:
    """Одна улика: механизм, уровень (нет / слабая / сильная / неизвестно), причина, дата данных, вес свежести и подсказка операции."""
    mechanism: str
    level: str
    reason: str
    data_date: str = ''
    weight: float = 1.0
    recommendation: str = ''


def _day(value: Any) -> date | None:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ('%d.%m.%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(value)[:10], fmt).date()
        except ValueError:
            continue
    return None


def freshness(measured: Any, today: Any, last_kr_year: int | None = None) -> float:
    """Вес замера 0…1: до последнего КР или старше двух лет — 0, иначе плавное затухание за год."""
    from math import exp
    m, t = _day(measured), _day(today)
    if m is None or t is None:
        return 0.0
    if last_kr_year is not None and m.year < last_kr_year:
        return 0.0
    age = (t - m).days
    return 0.0 if age < 0 or age > HARD_DAYS else exp(-age / TAU_DAYS)


def _span(period: str) -> tuple[date, date] | None:
    """Окно сезона отбора «2024-2025»: с 1 октября по 30 апреля (границы условные, нужны только чтобы разнести сезоны до и после замера)."""
    try:
        a, b = str(period).split('-')[:2]
        return date(int(a), 10, 1), date(int(b), 4, 30)
    except (ValueError, TypeError):
        return None


def _ratio(after: list[float], before: list[float]) -> float | None:
    a, b = sum(after) / len(after) if after else None, sum(before) / len(before) if before else None
    return a / b if a is not None and b else None


def season_split(seasons: list[dict[str, Any]], measured: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Сезоны отбора целиком до замера и целиком после него (сезон, в который попал замер, пропускается); по два ближайших с каждой стороны."""
    before, after = [], []
    for r in seasons:
        if r.get('kind') != 'withdrawal':
            continue
        span = _span(r['period'])
        if span is None:
            continue
        (before if span[1] < measured else after if span[0] > measured else []).append((span[0], r))
    before.sort(key=lambda x: x[0])
    after.sort(key=lambda x: x[0])
    return [r for _, r in before[-2:]], [r for _, r in after[:2]]


def gdi_trend(gdi: list[dict[str, Any]], measured: date) -> str | None:
    """ГДИ рядом с замером: 'worse' / 'same' по Δp² при одном расходе (меньшем из двух Qmax) у ближайших надёжных исследований до и после; нет пары — None."""
    rows = []
    for g in gdi:
        d = _day(g.get('date'))
        if d and g.get('reliable') and g.get('a') is not None and g.get('b') is not None and g.get('q_max') and abs((d - measured).days) <= NEAR_DAYS:
            rows.append((d, g))
    pre = [g for d, g in sorted(rows, key=lambda x: x[0]) if d <= measured]
    post = [g for d, g in sorted(rows, key=lambda x: x[0]) if d > measured]
    if not pre or not post:
        return None
    a, b = pre[-1], post[0]
    q = min(a['q_max'], b['q_max'])
    dp_a, dp_b = a['a'] * q + a['b'] * q * q, b['a'] * q + b['b'] * q * q
    if dp_a <= 0:
        return None
    return 'worse' if dp_b / dp_a >= GDI_WORSE else 'same'


def bottom_evidence(bottom_m: float | None, bottom_date: Any, filter_bottom_m: float | None, last_kr_year: int | None, seasons: list[dict[str, Any]],
                    gdi: list[dict[str, Any]], source: str, today: Any) -> Evidence | None:
    """Недоход отбитого забоя до низа фильтра/перфорации и что с ним делать (правило Egor 2026-11-20).

    Нет перекрытия — None (улики нет). КР после замера — старый замер не учитывается. Иначе сравниваем сезоны отбора до и после замера
    (накопленный объём, средний и максимальный суточный расход) и ГДИ рядом: комплексное снижение — перекрытие фильтра реально;
    стабильная работа при забое из отчёта ГИС — вероятно прибор не прошёл (центраторы), нужно шаблонирование силами геологов. Если забой уже
    отбит шаблоном геологической службы, прибор не причина: недоход считается реальным (``source`` — ключ из ``SOURCES``)."""
    if bottom_m is None or filter_bottom_m is None or filter_bottom_m - bottom_m <= OVERLAP_TOL_M:
        return None
    m = _day(bottom_date)
    gap = filter_bottom_m - bottom_m
    stamp = m.strftime('%d.%m.%Y') if m else ''
    weight = freshness(bottom_date, today, last_kr_year)
    head = f'Забой {bottom_m:g} м выше низа фильтра {filter_bottom_m:g} м на {gap:.1f} м'
    if m is None:
        return Evidence('bottom_fill', 'unknown', head + ': дата замера неизвестна, свежесть не оценить.', '', 0.0, 'Уточнить дату замера забоя или провести шаблонирование.')
    if weight == 0.0:
        why = 'после замера был КР' if last_kr_year is not None and m.year < last_kr_year else 'замер старше двух лет'
        return Evidence('bottom_fill', 'unknown', f'{head} ({stamp}), но {why}: в оценку текущего состояния не идёт.', stamp, 0.0, 'Нужен свежий замер забоя.')
    before, after = season_split(seasons, m)
    if not before or not after:
        return Evidence('bottom_fill', 'unknown', f'{head} ({stamp}); по сезонам до и после замера нет сравнения.', stamp, weight,
                        'Шаблонирование или ГДИ как самая дешёвая проверка.')
    ratios = [_ratio([r[k] for r in after if r.get(k) is not None], [r[k] for r in before if r.get(k) is not None])
              for k in ('volume', 'mean_rate', 'max_rate')]
    ratios = [x for x in ratios if x is not None]
    trend = gdi_trend(gdi, m)
    names = 'накопленный объём, средний и максимальный суточный расход'
    if len(ratios) >= 2 and sum(x <= DROP for x in ratios) >= 2:
        extra = ', ГДИ рядом тоже хуже' if trend == 'worse' else ''
        return Evidence('bottom_fill', 'strong', f'{head} ({stamp}); после замера снижение ({names}: к сезонам до замера {", ".join(f"{x * 100:.0f} %" for x in ratios)}){extra}: '
                        'перекрытие фильтра вероятно реальное.', stamp, weight, 'Промывка забоя / КР по причине заполнения.')
    if len(ratios) >= 2 and all(x >= STABLE for x in ratios) and trend != 'worse':
        stable = f'работа стабильна ({names} без падения)'
        if source == 'geo_template':
            return Evidence('bottom_fill', 'strong', f'{head} ({stamp}); забой отбит шаблоном геологической службы, прибор не причина, {stable}: '
                            'недоход реальный, хотя добыча пока держится.', stamp, weight, 'Промывка забоя / КР по причине заполнения.')
        if source == 'other':
            return Evidence('bottom_fill', 'weak', f'{head} ({stamp}); {stable}, источник забоя — {SOURCES[source]}.', stamp, weight, 'ГДИ или шаблонирование для подтверждения.')
        src = 'отбит из отчёта ГИС' if source == 'gis_report' else 'источник замера забоя неизвестен'
        return Evidence('bottom_fill', 'weak', f'{head} ({stamp}); {stable}, {src}: недоход вероятно из-за прибора '
                        '(центраторы и другие элементы), не из-за перекрытия.', stamp, weight, 'Шаблонирование силами геологической службы (малый лом доходит до искусственного забоя).')
    return Evidence('bottom_fill', 'unknown', f'{head} ({stamp}); сезоны до и после замера дают смешанную картину.', stamp, weight,
                    'ГДИ и шаблонирование для уточнения.')
