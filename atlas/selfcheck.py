"""Самопроверка Атласа на данных объекта.

Запуск: ``python -m atlas.selfcheck <папка или файлы> [--out папка]``.

Берёт ваши файлы, загружает их так же, как раздел «Импорт данных», и проверяет результат независимо от кода Атласа:
числа считаются заново из исходных таблиц (pandas), а затем сверяются с тем, что показывает Атлас. Затем проверяются
физические и логические правила (баланс, единицы, повторяемость) и запускаются все модули.

Результат — два файла в папке ``--out``: ``selfcheck_report.json`` (для разбора) и ``selfcheck_report.md`` (для чтения).
В них только счётчики, номера скважин и даты проблемных строк; сами таблицы не копируются.
Исходные файлы не изменяются. Проект создаётся во временной папке и удаляется.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import re
import shutil
import sys
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from . import VERSION

EXTENSIONS = ('.xlsx', '.xlsm', '.csv')
STATUS_ORDER = {'fail': 0, 'error': 1, 'warn': 2, 'info': 3, 'ok': 4, 'skip': 5}
STATUS_LABEL = {'ok': 'Пройдено', 'fail': 'ОШИБКА', 'warn': 'Внимание', 'info': 'Сведения', 'skip': 'Пропущено', 'error': 'Сбой проверки'}


class Report:
    def __init__(self):
        self.checks: list[dict[str, Any]] = []
        self.files: list[dict[str, Any]] = []
        self.started = time.time()

    def add(self, cid: str, title: str, status: str, text: str = '', scope: str = '', **data: Any) -> None:
        self.checks.append({'id': cid, 'title': title, 'status': status, 'text': text, 'scope': scope, 'data': data})

    def run(self, cid: str, title: str, scope: str, fn: Callable[[], Any]) -> None:
        """Выполняет проверку; сбой самой проверки не останавливает остальные."""
        try:
            out = fn()
            if out is None:
                return
            status, text, data = (out + ({},))[:3] if len(out) == 2 else out
            self.add(cid, title, status, text, scope, **(data or {}))
        except Exception as e:  # noqa: BLE001
            self.add(cid, title, 'error', f'{type(e).__name__}: {e}', scope, trace=traceback.format_exc()[-1500:])

    def counts(self) -> dict[str, int]:
        return dict(Counter(c['status'] for c in self.checks))

    def to_json(self) -> dict[str, Any]:
        return {'version': VERSION, 'python': sys.version.split()[0], 'platform': platform.platform(),
                'seconds': round(time.time() - self.started, 1), 'counts': self.counts(), 'files': self.files,
                'checks': self.checks}


def clean(x: Any) -> Any:
    """JSON без NaN/numpy-типов."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [clean(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, (pd.Timestamp,)):
        return x.strftime('%Y-%m-%d')
    return x


# ---------------------------------------------------------------- поиск файлов и независимое чтение
def discover(paths: list[str], recursive: bool = False) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            it = path.rglob('*') if recursive else path.glob('*')
            out += sorted(f for f in it if f.suffix.lower() in EXTENSIONS and not f.name.startswith(('~$', '.~lock')))
        elif path.exists():
            out.append(path)
    seen, uniq = set(), []
    for f in out:
        key = str(f.resolve()).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


def read_raw(path: Path) -> dict[str, pd.DataFrame]:
    """Таблицы файла без заголовков (как есть), независимо от загрузчика Атласа."""
    if path.suffix.lower() == '.csv':
        try:
            return {path.stem: pd.read_csv(path, header=None, sep=None, engine='python', encoding='utf-8-sig', dtype=object)}
        except UnicodeDecodeError:
            return {path.stem: pd.read_csv(path, header=None, sep=None, engine='python', encoding='cp1251', dtype=object)}
    return pd.read_excel(path, sheet_name=None, header=None)


def sheet_layout(raw: pd.DataFrame):
    """Заголовок и колонки полей — теми же правилами распознавания, что у Атласа (только распознавание)."""
    from .engine.core.loader import detect_layout
    head = [[None if (isinstance(v, float) and math.isnan(v)) else v for v in row] for row in raw.head(31).values.tolist()]
    layout = detect_layout(head, 'auto')
    return layout


def numeric(s: pd.Series) -> pd.Series:
    if s.dtype == object:
        s = s.astype(str).str.replace(' ', '').str.replace(' ', '').str.replace(',', '.')
    return pd.to_numeric(s, errors='coerce')


def independent_production(raw: pd.DataFrame, layout: dict[str, Any], sheet: str, unit_factor: float) -> pd.DataFrame | None:
    """Ожидаемая загрузка листа «добыча/закачка»: дубли суток — побеждает строка с расходом, пара «54/80» делится поровну."""
    m, h = layout['mapping'], layout['header']
    if layout['module'] != 'production' or not {'well', 'date', 'q'} <= set(m) or h < 0:
        return None
    body = raw.iloc[h + 1:]
    f = pd.DataFrame({
        'well': body[m['well']].astype(str).str.strip().str.replace(r'\.0$', '', regex=True),
        'date': pd.to_datetime(body[m['date']], errors='coerce', dayfirst=True),
        'q': numeric(body[m['q']]) * unit_factor})
    if 'hours' in m:
        f['hours'] = numeric(body[m['hours']])
    if 'group' in m:
        f['group'] = body[m['group']].astype(str).str.strip()
    f = f[f['well'].ne('') & f['well'].ne('nan') & f['date'].notna() & f['q'].notna()]
    f = f[f['q'] >= 0]
    f = f.sort_values('q', kind='stable').drop_duplicates(['well', 'date'], keep='last')
    comb = f['well'].str.match(r'^\d+(\s*[/;]\s*\d+)+$')
    parts = f[comb].copy()
    if len(parts):
        parts['p'] = parts['well'].str.findall(r'\d+')
        parts['n'] = parts['p'].str.len()
        parts = parts.explode('p')
        parts['well'] = parts['p']
        parts['q'] = parts['q'] / parts['n']
        parts = parts.drop(columns=['p', 'n'])
    f = pd.concat([f[~comb], parts], ignore_index=True)
    return f.groupby(['well', 'date'], as_index=False).agg(q=('q', 'sum'))


# ---------------------------------------------------------------- основной сценарий
class Session:
    def __init__(self, tmp: Path, production_unit: str, gdi_unit: str, quick: bool):
        from .engine.core import config
        from .imports import Imports
        from .projects import Projects
        config.STORAGE = tmp
        self.tmp = tmp
        self.projects = Projects(tmp)
        self.imports = Imports(self.projects)
        self.store = self.projects.store
        self.production_unit = production_unit
        self.gdi_unit = gdi_unit
        self.quick = quick

    def new_project(self, name: str) -> str:
        return self.store.create(name)

    def import_file(self, pid: str, path: Path, policy: str = 'new') -> dict[str, Any]:
        token = self.imports.upload(path.name, path.read_bytes())['token']
        files = [{'token': token}]
        body = {'view': 'simple', 'mode': 'auto', 'production_unit': self.production_unit, 'gdi_unit': self.gdi_unit,
                'files': files}
        info = self.imports.inspect(body)
        out: dict[str, Any] = {'inspect': info}
        if info.get('blocked'):
            out['blocked'] = True
            return out
        pending = self.imports.check(pid, body)
        out['pending'] = pending
        applied = self.imports.apply(pid, {'pending': pending['id'], 'policy': policy, 'accept': True})
        out['applied'] = applied
        return out

    def frames(self, pid: str) -> dict[str, pd.DataFrame]:
        return self.store.load(pid)[1]


def unit_factor(unit: str) -> float:
    return {'м³/сут': 1.0, 'тыс. м³/сут': 1000.0}.get(unit, 1.0)


def file_checks(rep: Report, ses: Session, path: Path) -> dict[str, Any]:
    name = path.name
    entry: dict[str, Any] = {'file': name, 'bytes': path.stat().st_size}
    rep.files.append(entry)
    t0 = time.time()
    pid = ses.new_project(f'check-{len(rep.files)}')
    try:
        res = ses.import_file(pid, path)
    except Exception as e:  # noqa: BLE001
        rep.add('import.fail', 'Файл загружается', 'fail', f'{type(e).__name__}: {e}', name)
        entry['error'] = str(e)
        return {'pid': pid, 'frames': {}}
    entry['seconds'] = round(time.time() - t0, 1)
    rows = res['inspect'].get('rows', [])
    entry['sheets'] = [{'sheet': r['sheet'], 'module': r.get('module'), 'found': r.get('found'), 'use': r.get('use'),
                        'status': r.get('status')} for r in rows]
    recognised = [r for r in rows if r.get('found')]
    if res.get('blocked'):
        if recognised:
            rep.add('import.blocked', 'Книга не блокируется служебными листами', 'fail',
                    'Распознан лист, но книга не загружается («Нет листов для загрузки»).', name,
                    sheets=entry['sheets'])
        else:
            rep.add('import.recognised', 'Файл распознан', 'warn',
                    'Ни один лист не распознан: проверьте заголовки колонок (Скважина, Дата, Расход…).', name,
                    sheets=entry['sheets'])
        return {'pid': pid, 'frames': {}}
    pend, applied = res['pending'], res['applied']
    entry['counts'] = {c['module']: c['rows'] for c in pend.get('counts', [])}
    entry['rejected'] = pend.get('rejected', 0)
    entry['warnings'] = pend.get('warnings', 0)
    entry['duplicates'] = applied.get('duplicates', 0)
    reasons = Counter(r.get('reason', '') for r in pend.get('issue_rows', []))
    entry['issue_reasons'] = dict(reasons.most_common(8))
    rep.add('import.ok', 'Файл загружается', 'ok', f'Загружено: {entry["counts"]}', name, seconds=entry['seconds'])
    if entry['rejected']:
        rep.add('import.rejected', 'Отклонённые строки объяснены', 'warn',
                f'Отклонено строк: {entry["rejected"]} (причины: {entry["issue_reasons"]}).', name)
    if entry['duplicates']:
        rep.add('import.duplicates', 'Повторы строк', 'info', f'Убрано повторов: {entry["duplicates"]}.', name)
    return {'pid': pid, 'frames': ses.frames(pid)}


def production_checks(rep: Report, ses: Session, path: Path, frames: dict[str, pd.DataFrame]) -> None:
    name = path.name
    prod = frames.get('production')
    if prod is None or prod.empty:
        return
    uf = unit_factor(ses.production_unit)
    # --- независимая сверка с исходной таблицей
    if not ses.quick:
        def fidelity():
            raws = read_raw(path)
            exp_parts = []
            for sheet, raw in raws.items():
                try:
                    lay = sheet_layout(raw)
                except Exception:  # noqa: BLE001
                    continue
                e = independent_production(raw, lay, sheet, uf)
                if e is not None and len(e):
                    e['sheet'] = sheet
                    exp_parts.append(e)
            if not exp_parts:
                return 'skip', 'Нет листа добычи/закачки для независимой сверки.'
            exp = pd.concat(exp_parts, ignore_index=True)
            a = prod.copy()
            a['date'] = pd.to_datetime(a['date'])
            tot_a, tot_e = float(a['q'].sum()), float(exp['q'].sum())
            ok_sum = math.isclose(tot_a, tot_e, rel_tol=1e-9, abs_tol=1e-6)
            by_sheet = {}
            for sh, g in exp.groupby('sheet'):
                qa = float(a.loc[a['sheet'] == sh, 'q'].sum()) if 'sheet' in a else float('nan')
                by_sheet[sh] = {'атлас': qa, 'пересчёт': float(g['q'].sum()), 'строк': int(len(g))}
            rows_ok = len(a) == len(exp)
            status = 'ok' if ok_sum and rows_ok else 'fail'
            return status, (f'Сумма расхода: Атлас {tot_a:,.1f}, пересчёт из файла {tot_e:,.1f}; строк: Атлас {len(a)}, '
                            f'пересчёт {len(exp)}.'), {'by_sheet': by_sheet}

        rep.run('prod.fidelity', 'Добыча и закачка совпадают с исходной таблицей', name, fidelity)

        def per_well():
            raws = read_raw(path)
            parts = []
            for sheet, raw in raws.items():
                try:
                    e = independent_production(raw, sheet_layout(raw), sheet, uf)
                except Exception:  # noqa: BLE001
                    e = None
                if e is not None:
                    parts.append(e)
            if not parts:
                return 'skip', 'Нет листа добычи/закачки.'
            exp = pd.concat(parts).groupby('well')['q'].sum()
            got = prod.groupby(prod['well'].astype(str))['q'].sum()
            idx = exp.index.union(got.index)
            diff = (got.reindex(idx).fillna(0) - exp.reindex(idx).fillna(0)).abs()
            bad = diff[diff > 1e-6 * max(1.0, float(exp.abs().max()))]
            if bad.empty:
                return 'ok', f'Суммы по {len(idx)} скважинам совпали.'
            return 'fail', f'Расходятся {len(bad)} скважин: {list(bad.index[:10])}.', {'wells': list(bad.index[:30])}

        rep.run('prod.per_well', 'Суммы по каждой скважине совпадают', name, per_well)

    # --- правила
    def basic():
        q = prod['q']
        issues = []
        if q.isna().any():
            issues.append(f'пустой расход: {int(q.isna().sum())}')
        if (q < 0).any():
            issues.append(f'отрицательный расход: {int((q < 0).sum())}')
        if not np.isfinite(q.fillna(0)).all():
            issues.append('бесконечные значения')
        d = pd.to_datetime(prod['date'], errors='coerce')
        if d.isna().any():
            issues.append(f'пустая дата: {int(d.isna().sum())}')
        if (d > pd.Timestamp.today() + pd.Timedelta(days=1)).any():
            issues.append(f'даты из будущего: {int((d > pd.Timestamp.today() + pd.Timedelta(days=1)).sum())}')
        return ('fail', 'Найдено: ' + '; '.join(issues)) if issues else ('ok', 'Нет пустых, отрицательных и будущих значений.')

    rep.run('prod.basic', 'Расход и даты без явных ошибок', name, basic)

    def uniq():
        dup = prod.duplicated(['kind', 'well', 'date']).sum() if 'kind' in prod else prod.duplicated(['well', 'date']).sum()
        return ('fail', f'Повторов суток после загрузки: {int(dup)}.') if dup else ('ok', 'Одна запись на скважину и сутки.')

    rep.run('prod.unique', 'Нет повторов «скважина + сутки»', name, uniq)

    def combined():
        w = prod['well'].astype(str)
        bad = sorted(set(w[w.str.contains(r'[/;]', regex=True)]))
        return ('fail', f'Составные номера не разделены: {bad[:10]}.') if bad else ('ok', 'Составных номеров скважин нет.')

    rep.run('prod.combined', 'Составные номера («54/80») разделены', name, combined)

    def group_stable():
        if 'group' not in prod:
            return 'skip', 'Нет группы.'
        per_day = prod.groupby(['well', 'date'])['group'].nunique()
        n = int((per_day > 1).sum())
        moved = prod.groupby('well')['group'].nunique()
        share = float((moved > 1).mean())
        if n:
            return 'fail', f'{n} скважино-суток записаны в двух группах.'
        if share > 0.05:
            return 'warn', f'{share:.0%} скважин меняли группу за историю.'
        return 'ok', 'Скважина в одной группе в каждые сутки.'

    rep.run('prod.groups', 'Скважина принадлежит одной группе', name, group_stable)

    def no_group():
        if 'group' not in prod:
            return None
        share = float((prod['group'].astype(str) == 'Без группы').mean())
        if share >= 0.99:
            return 'warn', 'Группы не заполнены: в файле нет колонки «Группа», «Источник» или «ГСП».'
        return 'ok', f'Группы заполнены: {prod["group"].nunique()} шт., без группы {share:.1%}.'

    rep.run('prod.group_filled', 'Группы заполнены', name, no_group)

    def both_kinds():
        if 'kind' not in prod:
            return None
        pos = prod[prod['q'] > 0]
        w = pos[pos['kind'] == 'withdrawal'][['well', 'date']]
        i = pos[pos['kind'] == 'injection'][['well', 'date']]
        n = len(w.merge(i, on=['well', 'date']))
        if not len(w) or not len(i):
            return 'skip', 'Есть только один тип данных.'
        return ('fail', f'{n} скважино-суток с отбором и закачкой одновременно.') if n else \
            ('ok', 'Отбора и закачки в одной скважине в одни сутки нет.')

    rep.run('prod.both', 'Нет одновременных отбора и закачки', name, both_kinds)

    def rates():
        w = prod[prod['q'] > 0]['q']
        if w.empty:
            return 'warn', 'Нет ненулевых расходов.'
        p50, p99, mx = float(w.median()), float(w.quantile(.99)), float(w.max())
        if mx > 3 * p99 + 1e5 or p50 < 1:
            return 'warn', f'Расход выглядит нетипично: медиана {p50:,.0f}, 99-й процентиль {p99:,.0f}, максимум {mx:,.0f} м³/сут.'
        return 'ok', f'Расход (м³/сут): медиана {p50:,.0f}, 99-й процентиль {p99:,.0f}, максимум {mx:,.0f}.'

    rep.run('prod.rates', 'Порядок величин расхода', name, rates)

    def seasons():
        if 'season' not in prod:
            return None
        s = prod['season'].astype(str)
        has = s[~s.isin(['', 'nan', 'None'])]
        if has.empty:
            return 'info', 'Колонка «Сезон» не заполнена: сезоны будут определены по датам.'
        d = pd.to_datetime(prod.loc[has.index, 'date'])
        y0 = has.str.extract(r'^(\d{4})')[0].astype(float)
        bad = ((d.dt.year < y0) | (d.dt.year > y0 + 1)).sum()
        return ('fail', f'{int(bad)} строк вне года своего сезона.') if bad else ('ok', 'Сезоны согласованы с датами.')

    rep.run('prod.season', 'Сезон согласован с датой', name, seasons)

    def open_zero():
        if 'hours' not in prod:
            return 'info', 'Нет колонки «Время работы»: статистика «открыта, расхода нет» недоступна.'
        h = pd.to_numeric(prod['hours'], errors='coerce')
        n_open = int((h > 0).sum())
        n = int(((h > 0) & (prod['q'] == 0)).sum())
        share = n / n_open * 100 if n_open else 0.0
        return 'info', f'Открыта, расхода нет: {n} суток ({share:.1f} % рабочих). Строки сохранены; разбор в «Проверке данных».', \
            {'days': n, 'share': round(share, 2)}

    rep.run('prod.open_zero', 'Сутки «открыта, расхода нет»', name, open_zero)

    def gaps():
        w = prod[prod['kind'] == 'withdrawal'] if 'kind' in prod else prod
        if w.empty or 'season' not in w:
            return None
        total = missing = 0
        for _, g in w[w['q'] > 0].groupby(['well', 'season']):
            d = pd.to_datetime(g['date']).drop_duplicates().sort_values()
            if len(d) < 2:
                continue
            span = (d.iloc[-1] - d.iloc[0]).days + 1
            total += span
            missing += span - len(d)
        if not total:
            return None
        share = missing / total
        return ('warn' if share > 0.02 else 'ok'), f'Суток без записи внутри периодов работы: {missing} из {total} ({share:.1%}).', \
            {'missing': missing, 'total': total}

    rep.run('prod.gaps', 'Пропуски суток внутри периодов', name, gaps)



def gdi_checks(rep: Report, ses: Session, path: Path, frames: dict[str, pd.DataFrame]) -> None:
    name = path.name
    g = frames.get('gdi')
    if g is None or g.empty:
        return

    def dp2():
        x = g.dropna(subset=['p_res', 'p_bh', 'dp2'])
        if x.empty:
            return 'skip', 'Нет давлений.'
        bad = ((x['p_res'] ** 2 - x['p_bh'] ** 2) - x['dp2']).abs() > 1.0
        share = float(bad.mean())
        return ('fail' if share > 0.01 else 'ok'), f'ΔP² ≠ Рпл² − Рзаб² в {int(bad.sum())} из {len(x)} строк.'

    rep.run('gdi.dp2', 'ΔP² = Рпл² − Рзаб²', name, dp2)

    def order():
        x = g.dropna(subset=['p_res', 'p_bh'])
        if x.empty:
            return 'skip', 'Нет давлений.'
        n = int((x['p_bh'] > x['p_res'] + 1e-6).sum())
        return ('fail', f'Рзаб больше Рпл в {n} строках.') if n else ('ok', 'Рзаб не больше Рпл.')

    rep.run('gdi.order', 'Забойное давление не выше пластового', name, order)

    def qpos():
        n = int((g['q'] <= 0).sum())
        mx = float(g['q'].max())
        if n:
            return 'fail', f'Неположительный расход в {n} строках.'
        return ('warn', f'Максимальный расход ГДИ {mx:,.0f}: проверьте единицу (тыс. м³/сут).') if mx > 5000 else \
            ('ok', f'Расход положителен, максимум {mx:,.1f}.')

    rep.run('gdi.q', 'Расход ГДИ положителен и в разумных пределах', name, qpos)

    def fit():
        x = g.dropna(subset=['q', 'dp2'])
        x = x[x['q'] > 0]
        cnt = pos = 0
        for _, s in x.groupby(['well', 'date']):
            if len(s) < 4:
                continue
            q = s['q'].to_numpy(float)
            y = s['dp2'].to_numpy(float) / q
            A = np.vstack([np.ones_like(q), q]).T
            coef = np.linalg.lstsq(A, y, rcond=None)[0]
            cnt += 1
            pos += int(coef[0] > 0 and coef[1] >= 0)
        if cnt < 5:
            return 'skip', f'Исследований с 4+ режимами мало ({cnt}).'
        share = pos / cnt
        return ('warn' if share < .7 else 'ok'), f'Физичные (a>0, b≥0) {pos} из {cnt} исследований ({share:.0%}).'

    rep.run('gdi.fit', 'Индикаторные кривые физичны', name, fit)

    def group():
        share = float((g['group'].astype(str) == 'Без группы').mean())
        return ('warn', 'Группа ГДИ не заполнена (нет колонки «Группа» или «ГСП»).') if share >= 0.99 else \
            ('ok', f'Группа заполнена, без группы {share:.1%}.')

    rep.run('gdi.group', 'Группа заполнена', name, group)


def project_checks(rep: Report, ses: Session, pid: str, frames: dict[str, pd.DataFrame]) -> None:
    """Согласованность наборов между собой и запуск всех модулей на общем проекте."""
    prod, gdi = frames.get('production'), frames.get('gdi')

    def wells_known():
        if prod is None or gdi is None or prod.empty or gdi.empty:
            return None
        gw, pw = set(gdi['well'].astype(str)), set(prod['well'].astype(str))
        missing = sorted(gw - pw)
        share = len(missing) / max(len(gw), 1)
        return ('warn' if share > .1 else 'ok'), f'Скважин ГДИ, которых нет в добыче: {len(missing)} из {len(gw)}.', \
            {'wells': missing[:30]}

    rep.run('proj.wells', 'Скважины ГДИ есть в добыче', '', wells_known)

    def group_names():
        if prod is None or gdi is None or prod.empty or gdi.empty:
            return None
        a, b = set(gdi['group'].astype(str)) - {'Без группы'}, set(prod['group'].astype(str)) - {'Без группы'}
        if not a or not b:
            return 'skip', 'Нет групп для сравнения.'
        return ('ok' if a & b else 'fail'), f'Группы ГДИ: {sorted(a)[:6]}; группы добычи: {sorted(b)[:6]}.'

    rep.run('proj.group_names', 'Названия групп ГДИ и добычи совпадают', '', group_names)

    from . import registry
    from .contract import MissingData
    mods = registry.modules()
    for mid, module in mods.items():
        def run_module(module=module, mid=mid):
            try:
                data = ses.projects.select(pid, module.spec.needs, module.spec.optional)
            except MissingData:
                return 'skip', 'Нет нужных данных в загруженных файлах.'
            params = module.spec.coerce({})
            t = time.time()
            result = module.run(data, params)
            js = clean(result.to_json())
            text = json.dumps(js, ensure_ascii=False, default=str)
            if 'NaN' in text or 'Infinity' in text:
                return 'fail', 'В ответе есть нечисловые значения.'
            sec = round(time.time() - t, 1)
            return 'ok', f'Расчёт {sec} с, таблиц {len(js.get("tables", []))}, графиков {len(js.get("charts", []))}.'

        rep.run(f'module.{mid}', f'Модуль «{module.spec.title}» считается', '', run_module)

    if ses.quick or prod is None or prod.empty:
        return
    prod_module = mods.get('production')
    if prod_module is None:
        return

    def group_sums():
        data = ses.projects.select(pid, prod_module.spec.needs, prod_module.spec.optional)
        groups = [g for g in prod_module.options('groups', data, {}) if g]
        if not groups:
            return 'skip', 'Нет групп.'
        bad, checked = [], 0
        for kind in ('withdrawal', 'injection'):
            if 'kind' in prod and not (prod['kind'] == kind).any():
                continue
            periods = prod_module.options('periods', data, {'kind': kind})
            for per in periods[-3:]:
                params = prod_module.spec.coerce({'mode': 'groups', 'kind': kind, 'groups': groups, 'periods': [per]})
                js = clean(prod_module.run(data, params).to_json())
                for ch in js.get('charts', []):
                    g = str(ch.get('id', '')).replace('production-group-', '')
                    ser = [s for s in ch.get('series', []) if str(s.get('name', '')).startswith('Сумма')]
                    if not ser:
                        continue
                    got = sum(v for v in (ser[0].get('y') or []) if isinstance(v, (int, float)))
                    sub = prod[(prod['kind'] == kind) & (prod['group'].astype(str) == g)]
                    col = 'season' if kind == 'withdrawal' else 'year'
                    lab = sub[col].astype(str).str.replace(r'\.0$', '', regex=True)
                    want = float(sub[lab == str(per)]['q'].sum())
                    checked += 1
                    # график в тыс. м³; допускаем кратность 1, 1e3, 1e6 — но одну и ту же для всех групп
                    ratio = want / got if got else float('nan')
                    if not math.isfinite(ratio) or not any(math.isclose(ratio, f, rel_tol=1e-6) for f in (1, 1e3, 1e6)):
                        bad.append((kind, per, g, round(got, 3), round(want, 1)))
        if not checked:
            return 'skip', 'Нет сезонов для сверки.'
        return ('fail', f'Расходятся {len(bad)} из {checked}: {bad[:5]}.') if bad else \
            ('ok', f'Суммы групп на графиках совпали с исходными ({checked} сверок).')

    rep.run('proj.group_sums', 'Суммы групп на графиках = сумма скважин', '', group_sums)

    def every_well():
        wells_module = mods.get('wells')
        if wells_module is None:
            return None
        data = ses.projects.select(pid, wells_module.spec.needs, wells_module.spec.optional)
        groups = [g for g in prod_module.options('groups', data, {}) if g][:3]
        per = prod_module.options('periods', data, {'kind': 'withdrawal'})[-1:]
        bad, n = [], 0
        for g in groups:
            for w in prod_module.options('wells', data, {'groups': [g]})[:15]:
                params = wells_module.spec.coerce({'groups': [g], 'wells': [w], 'periods': per})
                try:
                    js = clean(wells_module.run(data, params).to_json())
                    text = json.dumps(js, ensure_ascii=False, default=str)
                    if 'NaN' in text:
                        bad.append(w)
                except Exception as e:  # noqa: BLE001
                    bad.append(f'{w}: {e}')
                n += 1
        return ('fail', f'Не считается: {bad[:5]}.') if bad else ('ok', f'Поскважинный анализ: {n} скважин без сбоев.')

    rep.run('proj.every_well', 'Поскважинный анализ считается', '', every_well)


def idempotency(rep: Report, ses: Session, files: list[Path]) -> None:
    def run():
        pid = ses.new_project('idem')
        sizes = []
        for round_ in range(2):
            for f in files:
                res = ses.import_file(pid, f)
                if res.get('blocked'):
                    continue
            fr = ses.frames(pid)
            sizes.append({k: len(v) for k, v in fr.items()})
        return ('ok', f'Повторная загрузка не меняет размеры таблиц: {sizes[0]}.') if sizes[0] == sizes[1] else \
            ('fail', f'Повторная загрузка меняет таблицы: {sizes[0]} → {sizes[1]}.')

    rep.run('proj.idempotent', 'Повторная загрузка ничего не удваивает', '', run)


# ---------------------------------------------------------------- отчёт
def markdown(rep: Report) -> str:
    j = rep.to_json()
    lines = ['# Самопроверка Газового Атласа', '',
             f'Версия {j["version"]}, Python {j["python"]}, время {j["seconds"]} с.', '']
    c = j['counts']
    lines.append('Итого: ' + ', '.join(f'{STATUS_LABEL[k]} — {c[k]}' for k in sorted(c, key=lambda k: STATUS_ORDER[k])) + '.')
    lines.append('')
    lines.append('## Файлы')
    for f in j['files']:
        info = [f'{f["bytes"] / 1e6:.1f} МБ']
        if 'counts' in f:
            info.append('строк: ' + ', '.join(f'{k} {v}' for k, v in f['counts'].items()))
        if f.get('rejected'):
            info.append(f'отклонено {f["rejected"]}')
        if f.get('seconds') is not None:
            info.append(f'{f["seconds"]} с')
        lines.append(f'- **{f["file"]}**: ' + '; '.join(info))
    lines.append('')
    order = sorted(j['checks'], key=lambda c: (STATUS_ORDER[c['status']], c['scope'], c['id']))
    for status in ('fail', 'error', 'warn', 'info'):
        part = [c for c in order if c['status'] == status]
        if not part:
            continue
        lines.append(f'## {STATUS_LABEL[status]} ({len(part)})')
        for ch in part:
            where = f' [{ch["scope"]}]' if ch['scope'] else ''
            lines.append(f'- **{ch["title"]}**{where}: {ch["text"]}')
        lines.append('')
    ok = [c for c in order if c['status'] == 'ok']
    lines.append(f'## Пройдено ({len(ok)})')
    for ch in ok:
        where = f' [{ch["scope"]}]' if ch['scope'] else ''
        lines.append(f'- {ch["title"]}{where}')
    skipped = [c for c in order if c['status'] == 'skip']
    if skipped:
        lines += ['', f'## Пропущено ({len(skipped)})']
        for ch in skipped:
            lines.append(f'- {ch["title"]}: {ch["text"]}')
    return '\n'.join(lines) + '\n'


def run(paths: list[str], out: str | Path = '.', production_unit: str = 'м³/сут', gdi_unit: str = 'тыс. м³/сут',
        quick: bool = False, recursive: bool = False, say: Callable[[str], None] = print) -> Report:
    rep = Report()
    files = discover(paths, recursive)
    if not files:
        rep.add('files.none', 'Файлы найдены', 'fail', 'В указанном месте нет таблиц .xlsx/.xlsm/.csv.')
        return rep
    tmp = Path(tempfile.mkdtemp(prefix='atlas_selfcheck_'))
    try:
        ses = Session(tmp, production_unit, gdi_unit, quick)
        combined = ses.new_project('combined')
        for i, f in enumerate(files, 1):
            say(f'[{i}/{len(files)}] {f.name}')
            got = file_checks(rep, ses, f)
            fr = got['frames']
            if fr:
                production_checks(rep, ses, f, fr)
                gdi_checks(rep, ses, f, fr)
                try:
                    ses.import_file(combined, f)
                except Exception as e:  # noqa: BLE001
                    rep.add('combined.import', 'Файл добавляется в общий проект', 'fail', str(e), f.name)
        say('Общий проект: согласованность и модули')
        cf = ses.frames(combined)
        project_checks(rep, ses, combined, cf)
        if not quick:
            say('Повторная загрузка')
            idempotency(rep, ses, [f for f in files if any(e.get('file') == f.name and e.get('counts') for e in rep.files)])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    outdir = Path(out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / 'selfcheck_report.json').write_text(json.dumps(clean(rep.to_json()), ensure_ascii=False, indent=1),
                                                  encoding='utf-8')
    (outdir / 'selfcheck_report.md').write_text(markdown(rep), encoding='utf-8')
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='atlas.selfcheck', description='Самопроверка Атласа на данных объекта')
    ap.add_argument('paths', nargs='+', help='папка с файлами объекта и/или отдельные файлы')
    ap.add_argument('--out', default='selfcheck_result', help='папка для отчёта (по умолчанию ./selfcheck_result)')
    ap.add_argument('--production-unit', default='м³/сут', choices=('м³/сут', 'тыс. м³/сут'),
                    help='единица расхода добычи, если её нет в заголовке')
    ap.add_argument('--gdi-unit', default='тыс. м³/сут', choices=('м³/сут', 'тыс. м³/сут'))
    ap.add_argument('--quick', action='store_true', help='без независимой сверки и повторной загрузки (быстрее)')
    ap.add_argument('--recursive', action='store_true', help='искать файлы и во вложенных папках')
    args = ap.parse_args(argv)
    rep = run(args.paths, args.out, args.production_unit, args.gdi_unit, args.quick, args.recursive)
    c = rep.counts()
    print('\n' + ', '.join(f'{STATUS_LABEL[k]}: {c[k]}' for k in sorted(c, key=lambda k: STATUS_ORDER[k])))
    print(f'Отчёт: {Path(args.out).resolve() / "selfcheck_report.md"}')
    return 1 if c.get('fail') or c.get('error') else 0


if __name__ == '__main__':
    sys.exit(main())
