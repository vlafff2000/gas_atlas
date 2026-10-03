# Gas Atlas 6 (пакет atlas/) проверяется, если стоят starlette и его тестовый клиент (requirements-atlas.txt + httpx).
collect_ignore = []
try:
    import starlette.testclient  # noqa: F401  (нужен и клиент: httpx / httpx2 ставится только для atlas)
except (ImportError, RuntimeError):
    collect_ignore.append('atlas')
