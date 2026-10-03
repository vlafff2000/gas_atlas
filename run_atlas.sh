#!/usr/bin/env bash
# Газовый атлас 6: ядро + интерфейс в браузере. Python 3.8+ в .venv.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PY=.venv/bin/python
[ -x "$PY" ] || { echo "Сначала bash install.sh"; exit 1; }
"$PY" -c 'import starlette, uvicorn' 2>/dev/null || "$PY" tools/install.py
exec "$PY" -m atlas --browser "$@"
