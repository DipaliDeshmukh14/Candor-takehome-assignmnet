#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 not found. Install Python 3.10+ and try again." >&2
    exit 1
fi

PY_OK=$(python3 -c "import sys; print('ok' if sys.version_info >= (3,10) else 'bad')")
if [ "$PY_OK" != "ok" ]; then
    echo "Error: Python 3.10 or newer required." >&2
    python3 --version >&2
    exit 1
fi

python3 report.py
