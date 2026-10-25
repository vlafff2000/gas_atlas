"""Ядро меню: описание приложений, окружение с общей папкой проекта, запуск и остановка процессов."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class App:
    id: str
    title: str
    note: str
    port: int
    argv: List[str]  # аргументы интерпретатора; {port} подставляется


APPS = [
    App('atlas', 'Газовый атлас', 'Графики, ГДИ, давления, кроссплот, экспорт', 8765, ['-m', 'atlas', '--server', '--port', '{port}']),
    App('base', 'Работа с исходными данными', 'Сбор баз из исходных файлов, проверки', 8766, ['-m', 'pxg_base', '--server', '{port}']),
    App('maps', 'Карты', 'Расходы газа и воды по скважинам на карте', 8767, ['-m', 'gsp_maps', '--server', '{port}']),
    App('schedule', 'ГДМ', 'Модели tNavigator: сценарии, планшеты, выгрузка', 8768, ['-m', 'schedule_pxg', '--server', '{port}']),
]


def project_dir(root: Path = ROOT) -> Path:
    """Общая папка проекта: PXG_PROJECT или «Проект» рядом с программой."""
    return Path(os.environ.get('PXG_PROJECT') or root / 'Проект').resolve()


def app_url(app: App) -> str:
    return 'http://127.0.0.1:%d/' % app.port


def project_env(apps: List[App], project: Path, root: Path = ROOT) -> Dict[str, str]:
    """Переменные окружения, по которым приложения кладут данные в одну папку и знают адреса друг друга."""
    old_storage = root / 'storage'  # проекты, созданные до единого запуска, остаются на месте
    urls = {a.id: app_url(a) for a in apps}
    return {
        'PXG_PROJECT': str(project),
        'GAS_ATLAS_STORAGE': str(old_storage if old_storage.is_dir() else project / 'Атлас'),
        'GAS_ATLAS_LOGS': str(project / 'logs'),
        'PXG_RUNS_DIR': str(project / 'pxg_runs'),
        'GSP_MAPS_HOME': str(project / 'Карты_ГСП'),
        'GSP_MAPS_CACHE': str(project / 'Карты_ГСП' / 'cache'),
        'SCHEDULE_PXG_PROJECT': str(project / 'Скедул'),
        'PXG_APP_URLS': json.dumps(urls, ensure_ascii=False),
        'PXG_MAPS_URL': urls.get('maps', ''),
        'PYTHONNOUSERSITE': '1',
        'PYTHONUTF8': '1',
    }


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.3):
            return True
    except OSError:
        return False


class Hub:
    def __init__(self, apps: Optional[List[App]] = None, project: Optional[Path] = None, root: Path = ROOT):
        self.apps = {a.id: a for a in (APPS if apps is None else apps)}
        self.root = root
        self.project = project or project_dir(root)
        self.procs = {}  # type: Dict[str, subprocess.Popen]
        self.locks = {a: threading.Lock() for a in self.apps}

    def status(self) -> List[dict]:
        rows = []
        for app in self.apps.values():
            proc = self.procs.get(app.id)
            running = port_open(app.port)
            rows.append({'id': app.id, 'title': app.title, 'note': app.note, 'url': app_url(app), 'running': running,
                         'ours': bool(proc and proc.poll() is None)})
        return rows

    def start(self, app_id: str, timeout: float = 90) -> dict:
        with self.locks[app_id]:  # меню многопоточное: два нажатия подряд не должны запускать приложение дважды
            return self._start(app_id, timeout)

    def _start(self, app_id: str, timeout: float) -> dict:
        app = self.apps[app_id]
        if not port_open(app.port):
            self.project.mkdir(parents=True, exist_ok=True)
            logs = self.project / 'logs'
            logs.mkdir(exist_ok=True)
            env = dict(os.environ)
            env.update(project_env(list(self.apps.values()), self.project, self.root))
            argv = [sys.executable, '-s', '-X', 'utf8'] + [a.format(port=app.port) for a in app.argv]
            with open(str(logs / ('hub_%s.log' % app.id)), 'ab') as log:
                self.procs[app.id] = subprocess.Popen(argv, cwd=str(self.root), env=env, stdout=log, stderr=subprocess.STDOUT,
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and not port_open(app.port):
                if self.procs[app.id].poll() is not None:
                    raise RuntimeError('«%s» не запустилась, см. %s' % (app.title, logs / ('hub_%s.log' % app.id)))
                time.sleep(0.2)
            if not port_open(app.port):
                raise RuntimeError('«%s» не отвечает за %d с' % (app.title, int(timeout)))
        return {'url': app_url(app)}

    def stop(self, app_id: str) -> None:
        proc = self.procs.pop(app_id, None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stop_all(self) -> None:
        for app_id in list(self.procs):
            self.stop(app_id)
