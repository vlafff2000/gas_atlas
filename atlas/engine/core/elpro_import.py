"""Импорт данных ЭЛПРО («Параметры работы ГСП (за месяц)») в одну длинную таблицу по дням и скважинам.

Логика перенесена из all_scripts (``pxg_core/элпро.py``, PR #141): три вида файлов, все с расширением .xlsx —
SpreadsheetML 2003 (XML; ГСП-1,2,3 и ГСП-8), настоящий xlsx «Month_…» (ГСП-4,5,7,9, давление в кПа) и
уже собранная «БД_ЭЛПРО.xlsx» (лист «Данные»). Внутри разбора столбцы русские, как в all_scripts;
``to_db`` переводит результат в имена таблицы Атласа (``DatasetKind.ELPRO``).

Единицы: давление — кгс/см² (кПа и ГСП-8 в МПа приводятся), расход — тыс. м³/сут («м3/ч» принимается как м³ за сутки).
Прочерк — пропуск, ноль — простой. Группы — единой схемой имён («ГСП-1» = «ГСП 1»).
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .loader import canonical_gsp

KPA_PER_KGF = 98.0665          # 1 кгс/см² в кПа
MPA_TO_KGF = 10.1972           # 1 МПа в кгс/см²
# Группы, у которых давление в файлах ЭЛПРО в МПа, хотя в шапке стоит «кгс/см²» (подтвердил Egor, 2026-10-15)
PRESSURE_MPA_GROUPS = {"ГСП-8"}
SS = "{urn:schemas-microsoft-com:office:spreadsheet}"
BLOCK = 5                      # P, T, Y, Q, В работе
COLUMNS = ["Дата", "Режим", "ГСП", "Скважина", "№ п/п", "Начало сезона", "P газа, кгс/см²", "T газа, °C",
           "Y кру, %", "Q газа, тыс. м³/сут", "В работе, ч", "Файл"]
# «№ п/п» входит в ключ: в файлах ЭЛПРО один номер скважины может стоять в двух строках (разные значения)
KEY = ["Дата", "ГСП", "Скважина", "Режим", "№ п/п"]
# Имена таблицы Атласа (как у остальных наборов: латиница) и порядок столбцов
DB_COLUMNS = {"Дата": "date", "Режим": "kind", "ГСП": "group", "Скважина": "well", "№ п/п": "np",
              "Начало сезона": "season", "P газа, кгс/см²": "p", "T газа, °C": "t", "Y кру, %": "y",
              "Q газа, тыс. м³/сут": "q", "В работе, ч": "hours", "Файл": "file"}
DB_KEY = ["date", "group", "well", "kind", "np"]
MODES = {"Отбор": "withdrawal", "Закачка": "injection"}
NO_GROUP = "Без группы"

_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_MONTH_RE = re.compile(r"(20\d{2})_?(\d{2})")
_GSP_FILE_RE = re.compile(r"GSP\s*(\d+)", re.I)
_GSP_LABEL_RE = re.compile(r"^ГСП\s*-?\s*(\d+)$")
_GSP_TITLE_RE = re.compile(r"ГСП\s*-\s*(\d+)")
_MODE_RE = re.compile(r"(отбор|закачк)", re.I)


@dataclass
class FileInfo:
    """Сведения о разобранном файле: для статистики, сверки покрытия и предупреждений."""
    name: str
    fmt: str                                   # «XML» (SpreadsheetML), «xlsx» или «БД ЭЛПРО»
    month: Optional[date] = None               # месяц отчёта по имени файла
    groups: List[str] = field(default_factory=list)
    rows: int = 0
    wells: int = 0
    empty: int = 0                             # строки «скважина × день» без единого значения (прочерки)
    blocks: int = 0                            # дни в шапках (0 — файл не ЭЛПРО)
    outside: int = 0                           # строки за дни следующего месяца, не загружены
    range_bad: int = 0                         # значения вне допустимого диапазона, заменены пропуском
    q_unit: str = ""                           # «m3» — Q подписан м3/ч (принято как м³ за сутки)
    warnings: List[str] = field(default_factory=list)


# ---------- чтение сетки ячеек ----------

def _grids_xml(path: str) -> List[Tuple[str, List[list]]]:
    root = ET.parse(path).getroot()
    out = []
    for ws in root.iter(SS + "Worksheet"):
        grid: List[list] = []
        table = ws.find(SS + "Table")
        if table is None:
            continue
        for r in table.findall(SS + "Row"):
            ri = r.get(SS + "Index")
            if ri:
                while len(grid) < int(ri) - 1:
                    grid.append([])
            cells: list = []
            for c in r.findall(SS + "Cell"):
                ci = c.get(SS + "Index")
                if ci:
                    while len(cells) < int(ci) - 1:
                        cells.append(None)
                d = c.find(SS + "Data")
                cells.append(None if d is None else (d.text or "").strip())
                for _ in range(int(c.get(SS + "MergeAcross") or 0)):
                    cells.append("")
            grid.append(cells)
        out.append((ws.get(SS + "Name") or "", grid))
    return out


def _grids_xlsx(path: str) -> List[Tuple[str, List[list]]]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    finally:
        wb.close()


def read_grids(path: str) -> Tuple[str, List[Tuple[str, List[list]]]]:
    """Возвращает (формат, [(лист, сетка)]). Формат узнаётся по содержимому, не по расширению."""
    with open(path, "rb") as f:
        head = f.read(64)
    if head[:2] == b"PK":
        return "xlsx", _grids_xlsx(path)
    if b"<" in head:
        return "XML", _grids_xml(path)
    raise ValueError("неизвестный формат файла")


# ---------- разбор ----------

def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _num(v) -> float:
    """Число или NaN. «-», пусто и текст ошибок («#DIV/0!») — пропуск."""
    if isinstance(v, bool):
        return np.nan
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", "."))
        except ValueError:
            return np.nan
    return np.nan


def _as_date(v) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        m = _DATE_RE.search(v)
        if m:
            try:
                return date(int(m[3]), int(m[2]), int(m[1]))
            except ValueError:
                return None
    return None


def _well(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and float(v).is_integer():
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\d+(\.0+)?", v.strip()):
        return int(float(v))
    return None


def _name_month(name: str) -> Optional[date]:
    m = _MONTH_RE.search(name)
    return date(int(m[1]), int(m[2]), 1) if m else None


def _blocks(header: list) -> List[Tuple[int, date, Optional[str]]]:
    """Дни шапки: (столбец начала блока, дата, режим). Блоки идут подряд через BLOCK столбцов."""
    out = []
    for j in range(2, len(header)):
        d = _as_date(header[j])
        if d is None:
            continue
        cells = " ".join(_text(x) for x in header[j:j + BLOCK])
        m = _MODE_RE.search(cells)
        mode = None
        if m:
            mode = "Отбор" if m[1].lower().startswith("отбор") else "Закачка"
        out.append((j, d, mode))
    return out


def _parse_grid(sheet: str, grid: List[list], info: FileInfo, default_group: Optional[str],
                unit_p: str, unit_q: str) -> List[dict]:
    recs: List[dict] = []
    group = default_group
    blocks: List[Tuple[int, date, Optional[str]]] = []
    active = False
    seen_blocks = 0
    season: Optional[date] = None
    season_mode: Optional[str] = None
    for row in grid:
        c0 = _text(row[0]) if row else ""
        if not row:
            continue
        if c0 in ("Скважина", "Время"):
            blocks = _blocks(row)
            active = bool(blocks)
            seen_blocks += len(blocks)
            if not blocks:
                info.warnings.append("%s: шапка без дат, блок пропущен" % sheet)
            continue
        if re.search(r"(Сезон работы|Начало сезона)", " ".join(_text(x) for x in row[:7])):
            for x in row[:8]:
                d = _as_date(x)
                if d and season is None:
                    season = d
                if isinstance(x, str) and _MODE_RE.search(x) and season_mode is None:
                    season_mode = "Отбор" if x.lower().find("отбор") >= 0 else "Закачка"
            continue
        if re.search(r"Режим работы", " ".join(_text(x) for x in row[:7])):
            for x in row[:8]:
                if isinstance(x, str) and _MODE_RE.search(x):
                    season_mode = "Отбор" if x.lower().find("отбор") >= 0 else "Закачка"
            continue
        m = _GSP_LABEL_RE.match(c0)
        if m:
            group = "ГСП-%d" % int(m[1])
            if group not in info.groups:
                info.groups.append(group)
            continue
        if c0.startswith("для скважин") or c0.startswith("По "):
            active = False
            continue
        if not active or len(row) < 2:
            continue
        well = _well(row[1])
        if well is None:
            continue
        for j, d, bmode in blocks:
            mode = bmode or season_mode
            if mode is None:
                info.warnings.append("%s: скв. %d, %s — режим не указан, день пропущен" % (sheet, well, d))
                continue
            vals = [_num(row[k]) if k < len(row) else np.nan for k in range(j, j + BLOCK)]
            if np.isnan(vals).all():
                info.empty += 1
                continue
            if unit_p == "kpa":
                vals[0] = vals[0] / KPA_PER_KGF
            elif group in PRESSURE_MPA_GROUPS:
                vals[0] = vals[0] * MPA_TO_KGF
            if unit_q == "m3":
                vals[3] = vals[3] / 1000
            recs.append({
                "Дата": pd.Timestamp(d), "Режим": mode, "ГСП": group, "Скважина": well, "№ п/п": c0,
                "Начало сезона": pd.Timestamp(season) if season else pd.NaT,
                "P газа, кгс/см²": vals[0], "T газа, °C": vals[1], "Y кру, %": vals[2],
                "Q газа, тыс. м³/сут": vals[3], "В работе, ч": vals[4],
                "Файл": info.name,
            })
    info.blocks = seen_blocks
    return recs


def _units(grid_rows: List[list]) -> Tuple[str, str]:
    """Единицы давления и расхода: кПа (xlsx ЭЛПРО) или кгс/см² (XML); Q «м3/ч» или «т. м³»."""
    head = [_text(x) for r in grid_rows[:15] for x in r[:8]]
    unit_p = "kpa" if "кПа" in head else "kgf"
    unit_q = "m3" if any(h.replace("³", "3") == "м3/ч" for h in head) else "tm3"
    return unit_p, unit_q


def _is_db(grids) -> bool:
    """«БД_ЭЛПРО.xlsx» — уже собранная база (лист «Данные» с шапкой как в COLUMNS), не сырой файл ЭЛПРО."""
    return any(name == "Данные" and grid and set(COLUMNS[:4]) <= {_text(x) for x in grid[0]}
               for name, grid in grids)


def read_db(path: str, name: str) -> Tuple[pd.DataFrame, FileInfo]:
    """Готовая база ЭЛПРО: лист «Данные», столбцы как в COLUMNS. Строки проверяются так же, как сырые файлы."""
    info = FileInfo(name=name, fmt="БД ЭЛПРО", month=None)
    raw = pd.read_excel(path, sheet_name="Данные")
    missing = [c for c in COLUMNS[:4] if c not in raw.columns]
    if missing:
        info.warnings.append("%s: в базе нет столбцов %s" % (name, ", ".join(missing)))
        return pd.DataFrame(columns=COLUMNS), info
    df = raw.reindex(columns=COLUMNS)
    df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce")
    df = df[df["Дата"].notna()].copy()
    df["Скважина"] = df["Скважина"].map(_well)
    df = df[df["Скважина"].notna()].copy()
    df["Скважина"] = df["Скважина"].astype(int)
    df["Режим"] = df["Режим"].map(lambda v: "Отбор" if str(v).lower().startswith("отбор") else "Закачка")
    df["ГСП"] = df["ГСП"].fillna("").astype(str)
    df["№ п/п"] = df["№ п/п"].fillna("").astype(str)
    df["Файл"] = df["Файл"].fillna(name).astype(str) if "Файл" in df else name
    info.blocks = len(df)
    info.groups = sorted(set(df["ГСП"]) - {""})
    return df, info


def read_file(path: str) -> Tuple[pd.DataFrame, FileInfo]:
    """Разбор одного файла. Пустой результат — не ошибка: файл попадёт в статистику с нулём записей."""
    name = os.path.basename(path)
    info = FileInfo(name=name, fmt="", month=_name_month(name))
    fmt, grids = read_grids(path)
    if fmt == "xlsx" and _is_db(grids):
        return read_db(path, name)
    info.fmt = fmt
    recs: List[dict] = []
    for sheet, grid in grids:
        if not grid:
            continue
        # номер ГСП из заголовка «Параметры работы ГСП - 4»; в XML заголовок общий («ГСП-1,2,3»), там берутся подписи секций
        titles = {int(m[1]) for r in grid[:3] for x in r[:4] for m in [_GSP_TITLE_RE.search(_text(x))] if m}
        title = titles.pop() if len(titles) == 1 and not any("," in _text(x) for r in grid[:3] for x in r[:4]) else None
        fname_gsp = _GSP_FILE_RE.search(name)
        if fname_gsp and title and int(fname_gsp[1]) != title:
            info.warnings.append("%s: номер ГСП в имени (%s) и в заголовке (%d) не совпадают" % (name, fname_gsp[1], title))
        default = "ГСП-%d" % title if title else ("ГСП-%d" % int(fname_gsp[1]) if fname_gsp else None)
        unit_p, unit_q = _units(grid)
        info.q_unit = unit_q if unit_q == "m3" else info.q_unit
        if default and default not in info.groups:
            info.groups.append(default)
        recs += _parse_grid(sheet, grid, info, default, unit_p, unit_q)
    if not info.blocks:
        info.warnings.append("%s: шапка с датами не найдена — файл не похож на ЭЛПРО, пропущен" % name)
        return pd.DataFrame(columns=COLUMNS), info
    df = pd.DataFrame(recs, columns=COLUMNS)
    if info.month is not None and not df.empty:
        # в файле за месяц может стоять блок дня следующего месяца (например 01.12 в файле за ноябрь):
        # такой день берётся из файла своего месяца, здесь он не нужен и может быть неполным
        own = (df["Дата"].dt.year == info.month.year) & (df["Дата"].dt.month == info.month.month)
        info.outside = int((~own).sum())
        if info.outside:
            info.warnings.append("%s: строки за дни вне месяца отчёта не загружены: %d (даты %s)" % (
                name, info.outside, ", ".join(sorted(df.loc[~own, "Дата"].dt.strftime("%d.%m.%Y").unique())[:3])))
        df = df[own].reset_index(drop=True)
    if not df.empty:
        # физически невозможные значения (давление < 0 или > 400 кгс/см², расход < 0 или > 5000 тыс. м³/сут)
        # — ошибки в исходнике (например, 1e+24 в ячейке); они становятся пропуском и считаются
        bad_p = ((df["P газа, кгс/см²"] < 0) | (df["P газа, кгс/см²"] > 400)).fillna(False)
        bad_q = ((df["Q газа, тыс. м³/сут"] < 0) | (df["Q газа, тыс. м³/сут"] > 5000)).fillna(False)
        info.range_bad = int(bad_p.sum() + bad_q.sum())
        if info.range_bad:
            df.loc[bad_p, "P газа, кгс/см²"] = np.nan
            df.loc[bad_q, "Q газа, тыс. м³/сут"] = np.nan
            info.warnings.append("%s: значения вне диапазона заменены пропуском: давление %d, расход %d"
                                 % (name, int(bad_p.sum()), int(bad_q.sum())))
        # подозрительные, но не отбрасываемые значения: Y вне 0–100 %, T ниже нуля — только предупреждение
        bad_y = int(((df["Y кру, %"] < 0) | (df["Y кру, %"] > 100)).sum())
        bad_t = int((df["T газа, °C"] < 0).sum())
        if bad_y or bad_t:
            info.warnings.append("%s: подозрительные значения (оставлены): Y вне 0–100 %% — %d, T < 0 — %d"
                                 % (name, bad_y, bad_t))
        # номер скважины в двух строках с разными значениями — не дубль, сохраняем обе, но сообщаем
        multi = df.groupby(["Дата", "ГСП", "Режим", "Скважина"])["№ п/п"].nunique()
        twice = sorted({int(w) for (_, _, _, w), n in multi.items() if n > 1})
        if twice:
            info.warnings.append("%s: номера скважин стоят в двух строках с разными «№ п/п»: %s — проверить в ЭЛПРО"
                                 % (name, ", ".join(map(str, twice[:20]))))
        dup = df.duplicated(KEY, keep="first")
        if dup.any():
            info.warnings.append("%s: одинаковые строки «день × ГСП × скважина × режим × № п/п»: %d (оставлена первая)"
                                 % (name, int(dup.sum())))
            df = df[~dup].reset_index(drop=True)
    info.wells = int(df["Скважина"].nunique()) if not df.empty else 0
    info.rows = len(df)
    return df, info


# ---------- сборка по файлам ----------

def build(paths: Sequence[str]) -> Tuple[pd.DataFrame, List[FileInfo], pd.DataFrame, List[str]]:
    """Файлы → одна таблица (русские имена), файлы, покрытие (ГСП × месяц) и предупреждения."""
    frames, infos, warn = [], [], []
    for p in paths:
        try:
            df, info = read_file(p)
        except Exception as exc:  # битый файл не останавливает пакет
            info = FileInfo(name=os.path.basename(p), fmt="", month=_name_month(os.path.basename(p)))
            info.warnings.append("%s: не прочитан (%s)" % (info.name, exc))
            df = pd.DataFrame(columns=COLUMNS)
        frames.append(df)
        infos.append(info)
        warn += info.warnings
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    data["Дата"] = pd.to_datetime(data["Дата"])
    m3 = [i.name for i in infos if i.q_unit == "m3"]
    if m3:
        warn.insert(0, "Q подписан «м3/ч» в %d файлах: принято как м³ за сутки (значения сопоставимы с «т. м³» в XML). "
                       "Подтвердить по БД расходов" % len(m3))
    data = data.sort_values(["Дата", "ГСП", "Режим", "Скважина"]).reset_index(drop=True)
    return data, infos, coverage(data, infos), warn


def to_db(data: pd.DataFrame) -> pd.DataFrame:
    """Таблица Атласа: латинские имена, режим «withdrawal»/«injection», группы «ГСП 4» (единая схема), пустая группа — «Без группы»."""
    out = data.reindex(columns=COLUMNS).rename(columns=DB_COLUMNS)
    out["kind"] = out["kind"].map(MODES).fillna("withdrawal")
    group = out["group"].fillna("").astype(str).str.strip()
    out["group"] = canonical_gsp(group.where(group.ne(""), NO_GROUP)).astype(str)
    out["well"] = out["well"].astype(int).astype(str)
    out["np"] = out["np"].fillna("").astype(str)
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    return out.reset_index(drop=True)


def keep_first(db: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """Одна строка на скважину, сутки, группу и режим: та, что с меньшим «№ п/п». Лишние строки не учитываются.

    Пока решение Егора (2026-10-15): вторые строки с другими значениями не складываются и не усредняются,
    пока источник не подтвердит номер. Возвращает (таблица, число отброшенных строк)."""
    key = ['date', 'group', 'well', 'kind']
    ordered = db.assign(_np=pd.to_numeric(db['np'], errors='coerce')).sort_values(key + ['_np'], kind='stable')
    keep = ~ordered.duplicated(key, keep='first')
    return ordered.loc[keep].drop(columns='_np').reset_index(drop=True), int((~keep).sum())


def merge(old: pd.DataFrame | None, new: pd.DataFrame, policy: str = "new") -> Tuple[pd.DataFrame, int]:
    """Дозапись в прежнюю базу по ключу (день, группа, скважина, режим, № п/п).

    ``new`` — совпадения заменяются новыми строками; ``old`` — прежними. Возвращает (таблица, число совпадений)."""
    if old is None or old.empty:
        return new, 0
    old = old.drop(columns=["_point_id"], errors="ignore").reindex(columns=new.columns)
    old["date"] = pd.to_datetime(old["date"])
    keys_new = new.set_index(DB_KEY).index
    keys_old = old.set_index(DB_KEY).index
    same = keys_old.isin(keys_new)
    matched = int(same.sum())
    if policy == "old":
        return pd.concat([old, new[~new.set_index(DB_KEY).index.isin(keys_old)]], ignore_index=True), matched
    return pd.concat([old[~same], new], ignore_index=True), matched


def coverage(data: pd.DataFrame, infos: List[FileInfo]) -> pd.DataFrame:
    """Покрытие (ГСП × месяц отчёта). Ожидаемый месяц — тот, за который есть файл формата этой группы.

    Статус: «есть» — в файле месяца группа с данными; «ПРОПУСК: файла нет» — файла за месяц нет;
    «ПРОПУСК: в файле нет данных» — файл есть, а по группе все значения прочерки.
    """
    fmt_months: dict = {}
    group_fmt: dict = {}
    file_group: set = set()
    for info in infos:
        if info.month is None:
            continue
        fmt_months.setdefault(info.fmt, set()).add(info.month)
        for g in info.groups:
            group_fmt.setdefault(g, set()).add(info.fmt)
            file_group.add((g, info.month))
    counts: dict = {}
    if not data.empty:
        month_of = {i.name: i.month for i in infos}
        for (g, name), grp in data.groupby(["ГСП", "Файл"]):
            mo = month_of.get(name)
            if mo is not None:
                counts[(g, mo)] = (int(grp["Скважина"].nunique()), ", ".join(sorted(grp["Режим"].unique())),
                                   int(grp["Дата"].nunique()))
    rows = []
    for g in sorted(group_fmt, key=lambda s: int(re.search(r"\d+", s)[0])):
        months = set()
        for f in group_fmt[g]:
            months |= fmt_months.get(f, set())
        for mo in sorted(months):
            if (g, mo) not in file_group:
                status, wells, modes, days = "ПРОПУСК: файла нет", 0, "", 0
            else:
                wells, modes, days = counts.get((g, mo), (0, "", 0))
                status = "есть" if wells else "ПРОПУСК: в файле нет данных"
            rows.append({"ГСП": g, "Месяц": mo.strftime("%m.%Y"), "Скважин": wells, "Дней с данными": days,
                         "Режим": modes, "Статус": status})
    return pd.DataFrame(rows, columns=["ГСП", "Месяц", "Скважин", "Дней с данными", "Режим", "Статус"])
