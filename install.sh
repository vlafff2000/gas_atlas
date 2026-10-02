#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [ -n "${PYTHON_BIN:-}" ]; then
  atlas_python="$PYTHON_BIN"
elif command -v python3.8 >/dev/null 2>&1; then
  atlas_python=python3.8
else
  atlas_python=python3
fi
exec "$atlas_python" tools/install.py
