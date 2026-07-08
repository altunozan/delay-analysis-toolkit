#!/usr/bin/env bash
#
# Run the DCMA 14-point engine against an XER file from the command line
# (no browser / Streamlit UI). Prints the scorecard to the terminal.
#
# Usage:
#   ./test.sh                         # uses sample/Sample Baseline.xer
#   ./test.sh path/to/your.xer        # runs against your own file
#
# On first run this creates the local virtual environment (.venv) and installs
# dependencies, the same way run.sh does.

set -euo pipefail

# Resolve the directory this script lives in, so it works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

# Default XER file; override by passing a path as the first argument.
XER_FILE="${1:-sample/Sample Baseline.xer}"

if [ ! -f "$XER_FILE" ]; then
    echo "Error: XER file not found: $XER_FILE" >&2
    exit 1
fi

# Pick a Python interpreter (prefer python3).
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "Error: Python is not installed or not on PATH." >&2
    exit 1
fi

# Create the virtual environment on first run.
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# Activate it.
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Install / update dependencies only when requirements.txt changes.
STAMP_FILE="$VENV_DIR/.requirements.installed"
if [ ! -f "$STAMP_FILE" ] || [ requirements.txt -nt "$STAMP_FILE" ]; then
    echo "Installing dependencies from requirements.txt ..."
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    touch "$STAMP_FILE"
fi

echo "Running DCMA 14-point assessment on: $XER_FILE"
echo
exec "$PYTHON" test_engine.py "$XER_FILE"
