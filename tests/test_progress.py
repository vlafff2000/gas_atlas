"""Шкала выполнения: задачи видны, пока идёт запрос; шаги отмечаются в map_jobs."""
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from atlas import parallel, progress, runlog


def test_task_visible_and_removed():
    assert progress.active() == []
    with progress.task('расчёт', total=4) as t:
        t.advance(text='шаг')
        (a,) = progress.active()
        assert (a['label'], a['done'], a['total'], a['text']) == ('расчёт', 1, 4, 'шаг')
    assert progress.active() == []


def test_labels():
    assert progress.label_for('/api/modules/x/run') == 'Расчёт раздела'
    assert progress.label_for('/api/whatever') == 'Выполняется запрос'


def test_map_jobs_counts_steps():
    with progress.task('x') as t:
        assert parallel.map_jobs(lambda j: j + 1, [1, 2, 3]) == [2, 3, 4]
        assert (t.data['done'], t.data['total']) == (3, 3)


def test_request_is_a_task_while_running():
    seen = []

    async def slow(request):
        seen.append(client.get('/api/progress').json()['tasks'] if False else progress.active())
        return JSONResponse({})

    app = Starlette(routes=[Route('/api/modules/a/run', slow), *progress.routes()], middleware=[Middleware(runlog.RequestLog)])
    client = TestClient(app)
    client.get('/api/modules/a/run')
    assert seen[0][0]['label'] == 'Расчёт раздела'
    assert client.get('/api/progress').json() == {'tasks': []}
