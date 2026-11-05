#!/usr/bin/env bash
#
# scripts/test.sh - Environment-aware test runner for OccAIsion.
# Runs pytest using local .venv, system pytest, or provides devcontainer instructions.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTEST_BIN=""

if [ -x "$WORKSPACE_DIR/.venv/bin/pytest" ]; then
    PYTEST_BIN="$WORKSPACE_DIR/.venv/bin/pytest"
elif command -v pytest &>/dev/null; then
    PYTEST_BIN="$(command -v pytest)"
fi

if [ -n "$PYTEST_BIN" ]; then
    cd "$WORKSPACE_DIR"
    exec "$PYTEST_BIN" "$@"
else
    echo "❌ Error: 'pytest' could not be found in .venv or PATH." >&2
    echo "" >&2
    echo "To run tests on host:" >&2
    echo "  1. Create virtualenv:  python3 -m venv .venv" >&2
    echo "  2. Activate:           source .venv/bin/activate" >&2
    echo "  3. Install deps:       pip install -r requirements.txt" >&2
    echo "  4. Run:                pytest -v" >&2
    echo "" >&2
    echo "Or run inside Dev Container:" >&2
    echo "  ./scripts/agy-container.sh pytest -v" >&2
    exit 1
fi
