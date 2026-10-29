"""Где лежат проекты Атласа. Только стандартная библиотека: модуль читают и Атлас (``config``), и меню ПХГ (``pxg_hub``).

Раньше Атлас брал папку ``storage`` рядом с программой, а меню ПХГ — ``Проект/Атлас`` (если ``storage`` не было). Любой запуск
Атласа в обход меню (``Gas_Atlas_6.bat``, ярлык) создавал пустую ``storage``, и меню переключалось на неё: прежний проект
«пропадал», настройки слетали. Теперь обе точки входа пользуются одним выбором:

1. ``GAS_ATLAS_STORAGE`` — явное указание, ничего не угадывается;
2. иначе из двух папок (``storage`` и ``Проект/Атлас``) берётся та, где есть проекты; если проекты в обеих — та, где
   последнее изменение новее, а недостающие проекты другой папки копируются (``adopt``): ничего не удаляется и не переносится;
3. проектов нет нигде: существующая папка, иначе ``Проект/Атлас`` при запуске из меню ПХГ и ``storage`` при прямом запуске.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

log = logging.getLogger(__name__)

ADOPTED = 'adopted_projects.json'      # в папке-источнике: какие проекты уже скопированы (удалённый в приложении не возвращается)


def project_dirs(path: Path) -> List[Path]:
    try:
        return sorted(p.parent for p in Path(path).glob('projects/*/manifest.json'))
    except OSError:
        return []


def has_projects(path: Path) -> bool:
    return bool(project_dirs(path))


def last_activity(path: Path) -> float:
    """Время последнего изменения проектов папки (по manifest.json: его пишет каждое изменение проекта)."""
    times = []
    for folder in project_dirs(path):
        try:
            times.append((folder / 'manifest.json').stat().st_mtime)
        except OSError:
            continue
    return max(times, default=0.0)


def candidates(root: Path, project: Optional[Path] = None) -> List[Path]:
    """Возможные папки проектов: общая папка единого архива и ``storage`` рядом с программой."""
    root = Path(root)
    if project is None:
        project = Path(os.environ.get('PXG_PROJECT') or root / 'Проект')
    return [Path(project) / 'Атлас', root / 'storage']


def resolve(root: Path, project: Optional[Path] = None, unified: Optional[bool] = None) -> Path:
    """Папка проектов Атласа. ``project`` — общая папка «Проект» (меню ПХГ); ``unified`` — запуск из меню единого архива (по
    умолчанию: задан ``PXG_PROJECT`` или ``project``)."""
    root = Path(root)
    explicit = os.environ.get('GAS_ATLAS_STORAGE', '').strip()
    if explicit:
        return Path(explicit)
    shared, legacy = candidates(root, project)
    filled = [p for p in (shared, legacy) if has_projects(p)]
    if filled:
        return max(filled, key=last_activity) if len(filled) == 2 else filled[0]
    for existing in (shared, legacy):
        if existing.is_dir():
            return existing
    if unified is None:
        unified = project is not None or bool(os.environ.get('PXG_PROJECT'))
    return shared if unified else legacy


def others(chosen: Path, root: Path, project: Optional[Path] = None) -> List[Path]:
    """Другие папки с проектами (кроме выбранной): из них ``adopt`` докопирует недостающее."""
    chosen = Path(chosen).resolve()
    return [p for p in candidates(root, project) if p.resolve() != chosen and has_projects(p)]


def adopt(chosen: Path, sources: Iterable[Path]) -> List[str]:
    """Копирует в ``chosen`` проекты из ``sources``, которых там нет. Источник не меняется (кроме списка ``adopted_projects.json``).
    Возвращает идентификаторы скопированных проектов."""
    chosen = Path(chosen)
    copied: List[str] = []
    for source in sources:
        source = Path(source)
        marker = source / ADOPTED
        try:
            done = set(json.loads(marker.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError):
            done = set()
        for folder in project_dirs(source):
            pid = folder.name
            target = chosen / 'projects' / pid
            if pid in done or target.exists():
                continue
            tmp = target.with_name(pid + '.adopting')
            try:
                shutil.rmtree(str(tmp), ignore_errors=True)
                tmp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(str(folder), str(tmp))
                os.replace(str(tmp), str(target))
            except OSError:
                log.warning('Проект %s из %s не скопирован', pid, source, exc_info=True)
                shutil.rmtree(str(tmp), ignore_errors=True)
                continue
            copied.append(pid)
            done.add(pid)
        if copied:
            try:
                marker.write_text(json.dumps(sorted(done)), encoding='utf-8')
            except OSError:
                log.warning('Не записан %s', marker, exc_info=True)
    if copied:
        log.warning('В %s добавлены проекты из других папок хранения: %s', chosen, ', '.join(copied))
    return copied
