"""Справка о выполнении плана КР (.docx) → набор ``krs_plan`` напрямую из общего импорта (без книги КРС_для_Атласа.xlsx).

Тот же разбор, что в «Работе с исходными данными» (all_scripts, ``pxg_core/krs_plan.py``): таблицы капремонта (КР/ИС) и текущего ремонта (ТР);
цвет — выделение текста на номере скважины в столбце плана (зелёный — выполнено, жёлтый — в процессе, красный — не делают); даты фактические;
статус «Утвержден» — ремонт ещё будет, другой — в плане уже нет (подсказка: «Ремонт будет» и «В таблицу 7.1» исправляются вручную);
Э — эксплуатационная, Н — наблюдательная, П — поглотительная. Содержимое справки наружу не передаётся.
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import pandas as pd

PLAN_COLUMNS = ["Год", "Скважина", "Тип скважины", "Вид", "Шифры работ", "Коды работ", "Квартал", "Цвет в справке", "Состояние",
                "Дата начала", "Дата окончания", "Статус справки", "Ремонт будет", "В таблицу 7.1", "Проверить", "Файл"]
STATE_DONE, STATE_PROGRESS, STATE_CANCEL, STATE_PLAN = "Выполнено", "В процессе", "Не делают", "Не начато"
COLOR_STATE = {"green": STATE_DONE, "yellow": STATE_PROGRESS, "red": STATE_CANCEL}      # значения w:highlight в Word
COLOR_NAME = {"green": "зелёный", "yellow": "жёлтый", "red": "красный"}
APPROVED = "Утвержден"
WELL_TYPES = {"Э": "эксплуатационная", "Н": "наблюдательная", "П": "поглотительная"}

CODE_START = re.compile(r"(?:КР|ИС|ТР)\s*\d+(?:\.\d+)?")
WELL_TOKEN = re.compile(r"(?<![\d.])(\d{1,4})(?:\s*\(\s*([А-ЯЭ])\s*\))?(?![\d.])")
DATE = r"(\d{1,2})\.(\d{2})\.(\d{4}|\d{2})"
SKV_BLOCK = re.compile(r"[CС]кв\s*№?\s*(\d+)", re.I)
TR_RANGE = re.compile(r"(?<![\d.])(\d{1,4})\s*[-–]\s*" + DATE + r"\s*г?\.?\s*[-–]\s*" + DATE)
STATUS = re.compile(r"[Сс]кв\s*№?\s*(\d+)\s*стат\w*\s*/?\s*([^/\n]+)")


def _date(d: str, m: str, y: str) -> str:
    y = int(y)
    return "%02d.%02d.%d" % (int(d), int(m), y + 2000 if y < 100 else y)


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Cell:
    """Ячейка Word: абзацы как списки (текст, выделение)."""
    def __init__(self, paragraphs: List[List[Tuple[str, Optional[str]]]]):
        self.paragraphs = paragraphs

    @property
    def text(self) -> str:
        return "\n".join("".join(t for t, _ in p) for p in self.paragraphs)


def _run_text(r) -> str:
    out = []
    for el in r:
        if el.tag == W + "t":
            out.append(el.text or "")
        elif el.tag == W + "tab":
            out.append("\t")
        elif el.tag == W + "br":
            out.append("\n")
    return "".join(out)


def _cell(tc) -> Cell:
    paras = []
    for p in tc.findall(W + "p"):
        runs = []
        for r in p.iter(W + "r"):
            h = r.find(W + "rPr/" + W + "highlight")
            runs.append((_run_text(r), h.get(W + "val") if h is not None else None))
        paras.append(runs)
    return Cell(paras)


def read_docx_tables(path) -> Tuple[List[str], List[List[List[Cell]]]]:
    """Абзацы вне таблиц и таблицы (строки → ячейки), стандартной библиотекой: python-docx (lxml) на РЕД ОС 7.3 не нужен."""
    with zipfile.ZipFile(path if isinstance(path, str) else io.BytesIO(path)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    paras = ["".join(_run_text(r) for r in p.iter(W + "r")) for p in body.findall(W + "p")]
    tables = []
    for tbl in body.findall(W + "tbl"):
        rows = []
        for tr in tbl.findall(W + "tr"):
            cells = []
            for tc in tr.findall(W + "tc"):
                v = tc.find(W + "tcPr/" + W + "vMerge")
                cont = v is not None and v.get(W + "val") != "restart"
                cells.append(Cell([[]]) if cont else _cell(tc))
            rows.append(cells)
        tables.append(rows)
    return paras, tables


def split_codes(text: str) -> Tuple[List[str], str]:
    """Шифры в ячейке: список кодов («КР 1.094») и общий текст с названиями."""
    text = " ".join((text or "").split())
    hits = list(CODE_START.finditer(text))
    codes = [re.sub(r"\s+", " ", m.group(0)) for m in hits]
    parts = [text[m.start():(hits[i + 1].start() if i + 1 < len(hits) else len(text))].strip(" ;.") for i, m in enumerate(hits)]
    return codes, ". ".join(parts) if parts else text


def wells_with_colors(cell) -> List[Tuple[int, str, Optional[str]]]:
    """[(скважина, тип Э/Н/П или '', имя выделения)] — цвет берётся по первому символу номера."""
    out = []
    for p in cell.paragraphs:
        chars = []
        for txt, name in p:
            chars += [(ch, name) for ch in txt]
        text = "".join(ch for ch, _ in chars)
        for m in WELL_TOKEN.finditer(text):
            out.append((int(m.group(1)), m.group(2) or "", chars[m.start()][1]))
    return out


def parse_notes(text: str) -> Tuple[str, Dict[int, dict], List[str]]:
    """Примечания → (квартал, {скважина: {start, end}}, непонятое)."""
    text = (text or "").replace("\n", " / ")
    q = re.search(r"(\d)\s*квартал", text)
    quarter = q.group(1) if q else ""
    out: Dict[int, dict] = {}
    for m in TR_RANGE.finditer(text):
        out[int(m.group(1))] = {"start": _date(*m.group(2, 3, 4)), "end": _date(*m.group(5, 6, 7))}
    blocks = list(SKV_BLOCK.finditer(text))
    for i, b in enumerate(blocks):
        seg = text[b.end():(blocks[i + 1].start() if i + 1 < len(blocks) else len(text))]
        rec = out.setdefault(int(b.group(1)), {})
        s = re.search(r"Начата\s+ремонтом\s*/?\s*" + DATE, seg)
        e = re.search(r"(?:Дата\s+окончания|Окончена\s+ремонтом)\s*/?\s*" + DATE, seg)
        if s:
            rec["start"] = _date(*s.group(1, 2, 3))
        if e:
            rec["end"] = _date(*e.group(1, 2, 3))
    return quarter, out, []


def parse_status(text: str) -> Dict[int, str]:
    """Столбцы «план/факт» справа → {скважина: статус}. «Исключена/исключены по корректировке» тоже статус (не «Утвержден»)."""
    text = (text or "").replace("\n", " / ")
    out: Dict[int, str] = {}
    for m in STATUS.finditer(text):
        raw = m.group(2).strip(" .")
        low = raw.lower()
        out[int(m.group(1))] = (APPROVED if "утвержд" in low else "На доработку" if "доработ" in low else "В план КР" if "в план" in low else raw)
    for m in re.finditer(r"([^/]*?)исключен\w*\s+по\s+корректировке", text, re.I):
        for w in re.findall(r"\d{1,4}", m.group(1).split("/")[-1]):
            out.setdefault(int(w), "Исключена по корректировке")
    return out


def _year(paras: List[str]) -> Optional[int]:
    for p in paras:
        m = re.search(r"плана[^.]*?\bв\s+(20\d\d)\s*г", p, re.I)
        if m:
            return int(m.group(1))
    return None


def parse_sprav(content: bytes, name: str = "") -> Tuple[pd.DataFrame, List[Tuple[str, str]]]:
    paras, tables = read_docx_tables(content)
    year = _year(paras)
    notes: List[Tuple[str, str]] = []
    if year is None:
        notes.append(("предупреждение", "В справке не найден год плана (заголовок «… в 2026г»): год возьмите из дат, проверьте"))
    rows: List[dict] = []
    fname = name.replace("\\", "/").rsplit("/", 1)[-1]
    for table in tables:
        for cells in table:
            if len(cells) < 6 or not re.fullmatch(r"\d+", cells[1].text.strip() or "x"):
                continue                      # шапка и чужие строки
            codes, names = split_codes(cells[0].text)
            kind = (codes[0].split(" ")[0] if codes else ("ТР" if "текущ" in cells[0].text.lower() else ""))
            quarter, dates, _ = parse_notes(cells[5].text)
            extra = " / ".join(c.text for c in cells[6:])
            status = parse_status(extra)
            done = {w for w, _t, _c in wells_with_colors(cells[4])}
            for w, typ, hl in wells_with_colors(cells[2]):
                reasons: List[str] = []
                color = COLOR_NAME.get(hl or "", "")
                state = COLOR_STATE.get(hl or "", STATE_PLAN)
                d = dates.get(w, {})
                if w in done and state != STATE_DONE:
                    reasons.append("в столбце выполненных, но цвет в плане «%s»" % (color or "нет"))
                    state = STATE_DONE
                if d.get("end") and state in (STATE_PLAN, STATE_PROGRESS):
                    reasons.append("есть дата окончания, цвет в плане «%s»" % (color or "нет"))
                    state = STATE_DONE
                elif d.get("start") and not d.get("end") and state == STATE_DONE and w not in done:
                    reasons.append("зелёный, но даты окончания нет")
                if state == STATE_PLAN and d.get("start") and not d.get("end"):
                    state = STATE_PROGRESS
                if not hl:
                    reasons.append("нет цвета в справке")
                st = status.get(w, "")
                will = "Нет" if (st and st != APPROVED) or state == STATE_CANCEL else "Да"
                if state == STATE_CANCEL:
                    reasons.append("красный: не делают")
                if st and st != APPROVED:
                    reasons.append("статус «%s»: в плане уже нет" % st)
                if typ and typ not in WELL_TYPES:
                    reasons.append("тип «%s» не распознан" % typ)
                rows.append({"Год": year or (int(d["start"][-4:]) if d.get("start") else None), "Скважина": w,
                             "Тип скважины": WELL_TYPES.get(typ, typ), "Вид": kind, "Шифры работ": names, "Коды работ": "; ".join(codes),
                             "Квартал": quarter, "Цвет в справке": color, "Состояние": state, "Дата начала": d.get("start", ""),
                             "Дата окончания": d.get("end", ""), "Статус справки": st, "Ремонт будет": will,
                             "В таблицу 7.1": "Да" if will == "Да" else "Нет", "Проверить": "; ".join(reasons), "Файл": fname})
    plan = pd.DataFrame(rows, columns=PLAN_COLUMNS)
    return plan, notes


def split_tr(plan: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(КР и ИС, текущий ремонт ТР): ТР — отдельный лист книги, в таблицу 7.1 и в БД капремонтов не идёт."""
    tr = plan["Вид"].eq("ТР")
    return plan[~tr].reset_index(drop=True), plan[tr].reset_index(drop=True)


def merge_manual(plan: pd.DataFrame, prev: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Ручные значения «Ремонт будет» и «В таблицу 7.1» из прежней БД главнее пересчёта (скважина+год+шифры)."""
    if prev is None or prev.empty or plan.empty:
        return plan
    key = ["Год", "Скважина", "Коды работ"]
    old = prev.set_index(key)
    plan = plan.copy()
    for i, r in plan.iterrows():
        k = (r["Год"], r["Скважина"], r["Коды работ"])
        if k in old.index:
            o = old.loc[k]
            o = o.iloc[0] if isinstance(o, pd.DataFrame) else o
            for col in ("Ремонт будет", "В таблицу 7.1"):
                if col in o and str(o[col]) in ("Да", "Нет") and str(o[col]) != r[col]:
                    plan.at[i, col] = o[col]
                    plan.at[i, "Проверить"] = (str(r["Проверить"]) + "; " if r["Проверить"] else "") + "%s: оставлено ручное значение" % col
    return plan


KIND = 'krs_plan'


def looks_like(tables: dict) -> bool:
    """Справка КР: таблица, где в первом столбце шифры «КР 1.094…/ИС/ТР», во втором — число скважин по плану, столбцов не меньше шести."""
    for raw in tables.values():
        if raw is None or raw.empty or raw.shape[1] < 6:
            continue
        for _, r in raw.head(60).iterrows():
            first, second = str(r.iloc[0] if pd.notna(r.iloc[0]) else ''), str(r.iloc[1] if pd.notna(r.iloc[1]) else '').strip()
            if CODE_START.search(first) and re.fullmatch(r'\d+', second):
                return True
    return False


def read(name: str, content: bytes):
    """(набор krs_plan, замечания): тот же вид строк, что у листа «План КР»."""
    from . import krs_import
    if not str(name).lower().endswith('.docx'):
        raise ValueError('нужен файл Word со справкой о выполнении плана КР (.docx)')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            z.getinfo('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError('файл не похож на документ Word') from e
    plan, notes = parse_sprav(content, name)
    return krs_import.read_plan(plan), [f'{kind}: {text}' for kind, text in notes] + [
        f'Скв. {r["Скважина"]}: {r["Проверить"]}' for _, r in plan.iterrows() if r['Проверить']][:50]


def summary(plan: pd.DataFrame) -> str:
    tr = int(plan.kind.eq('ТР').sum())
    return f'справка КР: строк {len(plan)} (капремонт {len(plan) - tr}, текущий ремонт {tr}), скважин {plan.well.nunique()}'
