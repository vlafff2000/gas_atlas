"""«Любой график»: предпросмотр устаревшего запроса не рисуется (остался в очереди, пока инженер менял настройки дальше)."""
import threading
import time

from atlas.export_any import Newest


def test_queued_old_previews_are_skipped_and_only_the_newest_is_drawn():
    newest, drawn, release = Newest(), [], threading.Event()
    results = {}

    def request(seq):
        results[seq] = newest.run('page', seq, lambda: (drawn.append(seq), release.wait(2), seq)[2])

    first = threading.Thread(target=request, args=(1,))
    first.start()
    time.sleep(0.1)                       # первый уже рисует и держит очередь
    rest = [threading.Thread(target=request, args=(n,)) for n in (2, 3, 4)]
    for t in rest:
        t.start()
        time.sleep(0.05)
    release.set()
    for t in [first, *rest]:
        t.join(3)
    assert drawn == [1, 4]               # 2 и 3 устарели, пока ждали: пропущены без расчёта
    assert results[2] is Newest.STALE and results[3] is Newest.STALE and results[4] == 4


def test_requests_without_token_are_always_drawn():
    newest = Newest()
    assert newest.run(None, 0, lambda: 'ok') == 'ok'


def test_other_pages_do_not_cancel_each_other():
    newest = Newest()
    newest.run('a', 5, lambda: None)
    assert newest.run('b', 1, lambda: 'ok') == 'ok'
