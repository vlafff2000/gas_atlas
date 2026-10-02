#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
.venv/bin/python -m pip install -r requirements-dev.txt
exec .venv/bin/python -m pytest tests -q
