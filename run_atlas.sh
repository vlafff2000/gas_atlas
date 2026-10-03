#!/usr/bin/env bash
# Газовый атлас 6 (предварительная версия): ядро + интерфейс в браузере.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PY=.venv/bin/python
[ -x "$PY" ] || { echo "Сначала bash install.sh"; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Нужен Python 3.10+ в .venv"; exit 1; }
"$PY" -c 'import starlette, uvicorn' 2>/dev/null || "$PY" -m pip install -r requirements-atlas.txt
exec "$PY" -m atlas --browser "$@"
