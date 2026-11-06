#!/usr/bin/env bash
#
# scripts/lint.sh - Environment-aware linter & syntax validator for OccAIsion.
# Runs ruff on backend/tests and node syntax checks on extension/frontend scripts.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RUFF_BIN=""
if [ -x "$WORKSPACE_DIR/.venv/bin/ruff" ]; then
    RUFF_BIN="$WORKSPACE_DIR/.venv/bin/ruff"
elif command -v ruff &>/dev/null; then
    RUFF_BIN="$(command -v ruff)"
fi

if [ -z "$RUFF_BIN" ]; then
    echo "⚠️ Warning: 'ruff' not found. To install: pip install -r requirements-dev.txt" >&2
else
    echo "🔍 Running Ruff linter on backend/ and tests/..."
    "$RUFF_BIN" check "$WORKSPACE_DIR/backend" "$WORKSPACE_DIR/tests"
    echo "✅ Ruff linter passed."
fi

if command -v node &>/dev/null; then
    echo "🔍 Validating JavaScript syntax via Node.js..."
    node -c "$WORKSPACE_DIR/extension/background.js"
    node -c "$WORKSPACE_DIR/extension/content.js"
    node -c "$WORKSPACE_DIR/frontend/app.js"
    if [ -f "$WORKSPACE_DIR/frontend/api.js" ]; then
        node -c "$WORKSPACE_DIR/frontend/api.js"
    fi
    if [ -f "$WORKSPACE_DIR/frontend/toast.js" ]; then
        node -c "$WORKSPACE_DIR/frontend/toast.js"
    fi
    echo "✅ JavaScript syntax validation passed."
else
    echo "⚠️ Warning: 'node' not found in PATH; skipping JS syntax checks." >&2
fi
