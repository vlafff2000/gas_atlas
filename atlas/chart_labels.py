"""Свои подписи осей, заголовка и легенды для выгружаемых графиков — отдельно для каждого типа (модуля).

Поля формы ``label_<модуль>_<поле>``: ``title``, ``x``, ``y``, ``y2`` — заменяют название графика и осей (пусто — как в графике);
``legend`` — строки «что=на что»: фрагмент имени в легенде заменяется (после «=» пусто и имя совпадает целиком — запись
убирается из легенды); ``template`` (только ГДИ) — шаблон записи легенды из полей {дата}, {метод}, {исследование}.
Подписи применяются к уже построенному графику, считать заново ничего не нужно.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import chart_format

FIELDS = ('title', 'x', 'y', 'y2', 'legend', 'template')
GDI_FIELDS = ('дата', 'метод', 'исследование')
GDI_DEFAULT = '{дата}'
GDI_FULL = '{дата} · {метод} · {исследование}'
CURVE_SUFFIXES = (' · расчет', ' · БД')
DATE = re.compile(r'^\d{2}\.\d{2}\.\d{4}$')


class LabelError(ValueError):
    pass


def parse_rules(text: str) -> List[Tuple[str, str]]:
    rules = []
    for line in str(text or '').splitlines():
        if '=' not in line:
            continue
        old, new = line.split('=', 1)
        if old.strip():
            rules.append((old.strip(), new.strip()))
    return rules


def check(template: str) -> None:
    import string
    try:
        fields = [f for _, f, s, c in string.Formatter().parse(template) if f is not None and (f not in GDI_FIELDS or s or c)]
    except ValueError:
        raise LabelError('Шаблон легенды ГДИ: незакрытая фигурная скобка') from None
    if fields:
        raise LabelError('Неизвестное поле легенды: %s. Допустимы: %s' % (fields[0], ', '.join('{' + f + '}' for f in GDI_FIELDS)))


def configs(form: Mapping[str, Any], modules=None) -> Dict[str, Dict[str, str]]:
    """Непустые настройки подписей по модулям; ошибки шаблона и слишком длинный текст — до построения графиков."""
    found: Dict[str, Dict[str, str]] = {}
    for key, value in form.items():
        if not key.startswith('label_') or not isinstance(value, str) or not value.strip():
            continue
        module, _, field = key[len('label_'):].rpartition('_')
        if field not in FIELDS or not module:
            continue
        if len(value) > (2000 if field == 'legend' else 300):
            raise LabelError('Подпись «%s» слишком длинная' % field)
        found.setdefault(module, {})[field] = value.strip() if field != 'legend' else value
    # ГДИ: по умолчанию в легенде только дата; пустое поле «Запись легенды» возвращает полную запись
    if 'template' not in found.get('gdi', {}):
        found.setdefault('gdi', {})['template'] = GDI_FULL if 'label_gdi_template' in form else GDI_DEFAULT
    for cfg in found.values():
        if 'template' in cfg:
            check(cfg['template'])
    return found


def gdi_label(old: str, template: str) -> str:
    """«10.12.2023 · Установившиеся отборы · 2» → по шаблону из даты, метода и исследования."""
    parts = old.split(' · ')
    if not parts or not DATE.match(parts[0]):
        return old
    date, rest = parts[0], parts[1:]
    method = rest[0] if rest else ''
    study = rest[1] if len(rest) > 1 else ''
    text = template.format_map({'дата': date, 'метод': method, 'исследование': study})
    return re.sub(r'(\s*[·,;]\s*){2,}', ' · ', text).strip(' ·,;-–')


def _rename(old: str, cfg: Mapping[str, str], rules) -> Optional[str]:
    """Новое имя; ``None`` — убрать запись из легенды."""
    suffix = next((s for s in CURVE_SUFFIXES if old.endswith(s)), '')
    base = old[:-len(suffix)] if suffix else old
    if cfg.get('template'):
        base = gdi_label(base, cfg['template'])
    for before, after in rules:
        if base == before and not after:
            return None
        base = base.replace(before, after)
    return base + suffix


def apply(figure, cfg: Mapping[str, str]):
    """Копия графика с подписями из ``cfg`` (см. описание модуля)."""
    fig = copy.deepcopy(figure)
    meta = fig.layout.meta or {}
    wells = ', '.join(map(str, meta.get('wells', [])))
    if cfg.get('title'):
        fig.layout.title.text = cfg['title'].replace('{скважина}', wells)
    if cfg.get('x'):
        fig.layout.xaxis.title.text = cfg['x']
    if cfg.get('y'):
        fig.layout.yaxis.title.text = cfg['y']
    if cfg.get('y2') and 'yaxis2' in fig.layout:
        fig.layout.yaxis2.title.text = cfg['y2']
    rules = parse_rules(cfg.get('legend', ''))
    if rules or cfg.get('template'):
        names: Dict[str, Optional[str]] = {}
        for trace in fig.data:
            for attr in ('name', 'legendgroup'):
                old = getattr(trace, attr, None)
                if not old:
                    continue
                if old not in names:
                    names[old] = _rename(old, cfg, rules)
                new = names[old]
                if new is None:
                    if attr == 'name':
                        trace.showlegend = False
                else:
                    setattr(trace, attr, new)
    return fig


class LabelledJob:
    """Задание на график с подписями: всё остальное (имя, модуль) берётся у исходного."""

    def __init__(self, job, cfg: Mapping[str, str], format: Optional[Mapping[str, Any]] = None):
        self._job, self._cfg, self._format = job, cfg, format

    def __getattr__(self, name):
        return getattr(self._job, name)

    def render(self):
        figure = self._job.render()
        if self._format:
            figure = chart_format.apply(figure, self._format)
        return apply(figure, self._cfg) if self._cfg else figure


def labelled(plan, form: Mapping[str, Any]):
    """План выгрузки, в котором графики модулей с настроенными подписями строятся уже с ними."""
    from dataclasses import replace
    cfgs, formats = configs(form), chart_format.configs(form)
    if not cfgs and not formats:
        return plan
    return replace(plan, jobs=[LabelledJob(j, cfgs.get(j.module, {}), formats.get(j.module)) if getattr(j, 'module', '') in cfgs or getattr(j, 'module', '') in formats else j
                               for j in plan.jobs])
