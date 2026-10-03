import sys

# Gas Atlas 6 (пакет atlas/) требует Python 3.10+ и starlette; на 3.8 проверяется только версия 5.8.
collect_ignore = []
try:
    import starlette  # noqa: F401
except ImportError:
    collect_ignore.append('atlas')
if sys.version_info < (3, 10):
    collect_ignore.append('atlas')
