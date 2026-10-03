# Gas Atlas 6 (пакет atlas/) требует starlette и его тестовый клиент (httpx); без них проверяется только версия 5.8.
collect_ignore = []
try:
    import starlette.testclient  # noqa: F401  (нужен и клиент: httpx / httpx2 ставится только для atlas)
except (ImportError, RuntimeError):
    collect_ignore.append('atlas')
