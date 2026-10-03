import sys

# Gas Atlas 6 (пакет atlas/) требует Python 3.10+, starlette и его тестовый клиент; на 3.8 проверяется только версия 5.8.
collect_ignore = []
try:
    import starlette.testclient  # noqa: F401  (нужен и клиент: httpx / httpx2 ставится только для atlas)
except (ImportError, RuntimeError):
    collect_ignore.append('atlas')
if sys.version_info < (3, 10):
    collect_ignore.append('atlas')
