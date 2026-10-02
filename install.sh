#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Any 64-bit CPython 3.8 or newer works. Set PYTHON_BIN to choose one explicitly.
if [ -n "${PYTHON_BIN:-}" ]; then
  atlas_python="$PYTHON_BIN"
else
  atlas_python=""
  for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" tools/check_runtime.py --quiet >/dev/null 2>&1; then
      atlas_python="$candidate"; break
    fi
  done
  if [ -z "$atlas_python" ]; then
    echo "Python 3.8 or newer (64-bit) was not found. Install it or set PYTHON_BIN=/path/to/python." >&2
    exit 1
  fi
fi
exec "$atlas_python" tools/install.py
