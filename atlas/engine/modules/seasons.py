"""Автоопределение сезонов отбора и закачки по накопленному расходу объекта (когда в таблице нет колонок «Сезон»/«Год»).

Сезон вида — непрерывный отрезок дней, когда накопленный объём этого вида растёт. Пока кривая идёт горизонтально
(расхода нет или он ничтожен) — это нейтральный период или сезон противоположного вида. Для каждого вида кривая
считается отдельно, поэтому рост закачки при плоском отборе (и наоборот) отделяет сезоны сам, без отдельного правила.
Чистая математика над датами и расходом: интерфейса и настроек здесь нет.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TYPICAL_QUANTILE = 0.75  # «типичный» расход сезона — верхняя четверть положительных дней, а не максимум-выброс
DEFAULT_GAP_DAYS = 3     # пауза от этого числа суток — кандидат в нейтральный период
DEFAULT_SHARE = 10.0     # день активен, если расход не меньше этой доли (%) типичного
RESUME_DAYS = 14         # пауза короче этого, после которой тот же вид снова идёт устойчиво (а противоположный не начался), — остановка внутри сезона
MIN_SEASON_DAYS = 14     # сезон короче этого — случайный всплеск, а не сезон

KINDS = ('withdrawal', 'injection')


def _active_runs(dates: pd.Series, q: pd.Series, gap_days: int, share: float):
    """Непрерывные отрезки с расходом, как индексы суточного календаря: (календарь, расход по дням, [[с, по], …])."""
    q = pd.Series(np.asarray(q, dtype=float))
    dates = pd.Series(pd.to_datetime(np.asarray(dates)).normalize())
    keep = (q > 0).to_numpy()
    if not keep.any():
        return None, None, []
    total = q[keep].groupby(dates[keep].to_numpy()).sum()
    calendar = pd.date_range(total.index.min(), total.index.max())
    daily = total.reindex(calendar, fill_value=0.0)
    active = (daily >= daily[daily > 0].quantile(TYPICAL_QUANTILE) * share / 100.0).to_numpy()
    edges = np.flatnonzero(np.diff(np.concatenate(([0], active.astype(int), [0]))))
    runs: list[list[int]] = []
    for a, b in zip(edges[::2], edges[1::2]):
        if runs and int(a) - runs[-1][1] - 1 < gap_days:      # пропуск короче порога — не пауза
            runs[-1][1] = int(b) - 1
        else:
            runs.append([int(a), int(b) - 1])
    return calendar, daily.to_numpy(), runs


def detect_runs(dates: pd.Series, q: pd.Series, gap_days: int = DEFAULT_GAP_DAYS, share: float = DEFAULT_SHARE,
                other: list[tuple[pd.Timestamp, pd.Timestamp]] | None = None) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Сезоны одного вида: [(первый день, последний день)] по суммарному суточному расходу объекта.

    ``other`` — отрезки с расходом противоположного вида. Пауза короче ``RESUME_DAYS`` между отрезками одного вида,
    в которую противоположный вид не начинался, — остановка внутри сезона: сезон продолжается. Если после паузы
    расход не вернулся устойчиво (отрезок короче ``MIN_SEASON_DAYS``), это всплеск, а не сезон."""
    calendar, values, runs = _active_runs(dates, q, gap_days, share)
    if not runs:
        return []
    spans = [(calendar[a], calendar[b]) for a, b in runs]
    other = other or []
    merged: list[list[pd.Timestamp]] = []
    for a, b in spans:
        if merged:
            gap = (a - merged[-1][1]).days - 1
            if gap < RESUME_DAYS and (b - a).days + 1 >= MIN_SEASON_DAYS \
                    and not any(oa <= a and ob >= merged[-1][1] for oa, ob in other):
                merged[-1][1] = b
                continue
        merged.append([a, b])
    out = []
    for a, b in merged:
        if (b - a).days + 1 < MIN_SEASON_DAYS:
            continue
        i, j = calendar.get_loc(a), calendar.get_loc(b)
        days = np.flatnonzero(values[i:j + 1] > 0)    # границы — по реальному расходу
        out.append((calendar[i + days[0]], calendar[i + days[-1]]))
    return out


def run_label(kind: str, start: pd.Timestamp) -> str:
    """Подпись сезона как в 5.8: отбор «2023-2024» (по началу сезона), закачка — год начала."""
    if kind == 'injection':
        return str(start.year)
    first = start.year if start.month >= 7 else start.year - 1
    return f'{first}-{first + 1}'


def neutral_label(anchor: pd.Timestamp) -> str:
    """«Нейтральный период Весна 2026» (март–август) или «… Осень 2025» (сентябрь–февраль; январь–февраль — осень прошлого года)."""
    if 3 <= anchor.month <= 8:
        return f'Нейтральный период Весна {anchor.year}'
    return f'Нейтральный период Осень {anchor.year if anchor.month >= 9 else anchor.year - 1}'


def labeler(df: pd.DataFrame, gap_days: int = DEFAULT_GAP_DAYS, share: float = DEFAULT_SHARE):
    """Функция ``(date, kind) -> подпись`` для строк таблицы эксплуатации; вне сезонов — нейтральный период."""
    raw = {}
    for kind in KINDS:
        part = df[df.kind.eq(kind)]
        calendar, _, runs = _active_runs(part.date, part.q, gap_days, share) if len(part) else (None, None, [])
        raw[kind] = [(calendar[a], calendar[b]) for a, b in runs]
    runs = {}
    for kind, opposite in zip(KINDS, KINDS[::-1]):
        part = df[df.kind.eq(kind)]
        found = detect_runs(part.date, part.q, gap_days, share, raw[opposite]) if len(part) else []
        runs[kind] = (np.array([a for a, _ in found], dtype='datetime64[ns]'),
                      np.array([b for _, b in found], dtype='datetime64[ns]'),
                      [run_label(kind, a) for a, _ in found])

    def label(date: pd.Series, kind: pd.Series) -> pd.Series:
        at = date.dt.normalize().to_numpy().astype('datetime64[ns]')
        names = np.empty(len(date), dtype=object)
        for k, (starts, ends, titles) in runs.items():
            rows = kind.eq(k).to_numpy()
            before = np.searchsorted(ends, at, side='left') - 1       # последний сезон, закончившийся до даты
            nxt = np.searchsorted(starts, at, side='right') - 1
            inside = (nxt >= 0) & (at <= ends[np.maximum(nxt, 0)]) if len(titles) else np.zeros(len(at), bool)
            anchor = np.where(before >= 0, ends[np.maximum(before, 0)] + np.timedelta64(1, 'D'), at) if len(titles) else at
            for i in np.flatnonzero(rows):
                names[i] = titles[nxt[i]] if inside[i] else neutral_label(pd.Timestamp(anchor[i]))
        return pd.Series(names, index=date.index)

    return label


# ---------- расписание периодов из текстового файла ----------

_SCHEDULE_KINDS = {'inj': 'injection', 'injection': 'injection', 'закачка': 'injection',
                   'prod': 'withdrawal', 'withdrawal': 'withdrawal', 'отбор': 'withdrawal',
                   'none': 'none', 'neutral': 'none', 'нейтраль': 'none', 'нейтральный': 'none'}


def _parse_date(token: str, number: int) -> pd.Timestamp:
    date = pd.to_datetime(token, format='%d.%m.%Y', errors='coerce')
    if pd.isna(date):
        date = pd.to_datetime(token, format='%Y-%m-%d', errors='coerce')
    if pd.isna(date):
        raise ValueError(f'Строка {number}: дата «{token}» не распознана (ожидается ДД.ММ.ГГГГ).')
    return date


def parse_schedule(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Текст расписания → (периоды, пики).

    Период: «ДД.ММ.ГГГГ inj|none|prod» — дата начала; длится до дня перед следующей строкой, последний — до конца данных.
    Пик: «ДД.ММ.ГГГГ ДД.ММ.ГГГГ peak» — первый и последний день пикового окна внутри сезона, периоды он не разбивает.
    Периоды: [(ГГГГ-ММ-ДД, 'injection'|'none'|'withdrawal')]; пики: [(начало, конец)] по возрастанию.
    Пустые строки и строки с «#» пропускаются. Ошибка — ``ValueError`` с номером строки (текст для пользователя)."""
    phases, peaks = {}, []
    for number, line in enumerate(str(text).splitlines(), 1):
        line = line.split('#', 1)[0].strip().lstrip('\ufeff')
        if not line:
            continue
        parts = line.replace(';', ' ').replace('\t', ' ').split()
        if len(parts) == 3 and parts[2].lower() in ('peak', 'пик'):
            first, last = _parse_date(parts[0], number), _parse_date(parts[1], number)
            if last < first:
                raise ValueError(f'Строка {number}: конец пика раньше начала.')
            peaks.append((first, last))
            continue
        if len(parts) != 2:
            raise ValueError(f'Строка {number}: нужна дата и тип через пробел («28.06.2021 inj») или «дата дата peak».')
        date = _parse_date(parts[0], number)
        kind = _SCHEDULE_KINDS.get(parts[1].lower())
        if kind is None:
            raise ValueError(f'Строка {number}: тип «{parts[1]}» неизвестен (inj — закачка, prod — отбор, none — нейтральный период).')
        if date in phases:
            raise ValueError(f'Строка {number}: дата {parts[0]} повторяется.')
        phases[date] = kind
    if not phases and not peaks:
        raise ValueError('В файле нет ни одной даты.')
    fmt = lambda d: d.strftime('%Y-%m-%d')  # noqa: E731
    return [(fmt(d), phases[d]) for d in sorted(phases)], [(fmt(a), fmt(b)) for a, b in sorted(peaks)]


def schedule_labeler(schedule):
    """Функция ``(date, kind) -> подпись | NaN`` по расписанию. Закачка и отбор — подписи сезонов, none — нейтральный период.
    Даты до первой строки и строки другого вида в чужом периоде остаются без подписи (решает обычное правило)."""
    starts = np.array([d for d, _ in schedule], dtype='datetime64[ns]')
    kinds = [k for _, k in schedule]
    titles = [neutral_label(pd.Timestamp(d)) if k == 'none' else run_label(k, pd.Timestamp(d)) for d, k in schedule]

    def label(date: pd.Series, kind: pd.Series) -> pd.Series:
        at = date.dt.normalize().to_numpy().astype('datetime64[ns]')
        i = np.searchsorted(starts, at, side='right') - 1
        names = np.full(len(at), np.nan, dtype=object)
        row_kind = kind.to_numpy()
        for n in np.flatnonzero(i >= 0):
            if kinds[i[n]] in ('none', row_kind[n]):
                names[n] = titles[i[n]]
        return pd.Series(names, index=date.index)

    return label


# ---------- пиковые режимы ----------

DEFAULT_PEAK_FACTOR = 2.0
PEAK_GAP_DAYS = 3        # окна пика ближе этого друг к другу склеиваются


def detect_peaks(df: pd.DataFrame, gap_days: int = DEFAULT_GAP_DAYS, share: float = DEFAULT_SHARE,
                 factor: float = DEFAULT_PEAK_FACTOR) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Пиковые окна внутри сезонов: дни, когда суточный расход объекта не меньше ``factor`` × медианы дней этого сезона."""
    raw = {}
    for kind in KINDS:
        part = df[df.kind.eq(kind)]
        calendar, _, runs = _active_runs(part.date, part.q, gap_days, share) if len(part) else (None, None, [])
        raw[kind] = [(calendar[a], calendar[b]) for a, b in runs]
    out = []
    for kind, opposite in zip(KINDS, KINDS[::-1]):
        part = df[df.kind.eq(kind) & (df.q > 0)]
        if part.empty:
            continue
        daily = part.groupby(part.date.dt.normalize()).q.sum()
        for first, last in detect_runs(part.date, part.q, gap_days, share, raw[opposite]):
            season = daily[first:last]
            hot = season[season >= factor * season.median()]
            window = None
            for day in hot.index:
                if window and (day - window[1]).days - 1 < PEAK_GAP_DAYS:
                    window[1] = day
                else:
                    window and out.append(tuple(window))
                    window = [day, day]
            window and out.append(tuple(window))
    return sorted(out)


def peaks_for(df: pd.DataFrame, settings) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Пиковые окна проекта: заданные в расписании (``peak_windows``) плюс найденные по расходу при ``auto_peaks``."""
    found = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in (settings.get('peak_windows') or [])]
    if settings.get('auto_peaks') and len(df):
        found += detect_peaks(df, settings.get('season_gap_days', DEFAULT_GAP_DAYS) if settings.get('auto_seasons') else DEFAULT_GAP_DAYS,
                              settings.get('season_rate_share', DEFAULT_SHARE),
                              float(settings.get('peak_factor', DEFAULT_PEAK_FACTOR)))
    return sorted(set(found))
