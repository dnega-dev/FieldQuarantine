#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" -m unittest discover -s "$ROOT/tests" -v
"$PYTHON" "$ROOT/examples/disconnect_reconnect.py" >/dev/null
"$PYTHON" -m compileall -q "$ROOT/src" "$ROOT/tests" "$ROOT/examples"

echo "Field Quarantine checks passed."
