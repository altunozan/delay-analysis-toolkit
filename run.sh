#!/usr/bin/env bash
#
# Launch the DCMA 14-Point Assessment Streamlit app.
#
# Usage:
#   ./run.sh
#
# On first run this creates a local virtual environment (.venv) and installs
# dependencies. Subsequent runs reuse it and start the app directly.

set -euo pipefail

# Resolve the directory this script lives in, so it works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

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

# Install / update dependencies. The stamp file avoids reinstalling every run
# unless requirements.txt has changed.
STAMP_FILE="$VENV_DIR/.requirements.installed"
if [ ! -f "$STAMP_FILE" ] || [ requirements.txt -nt "$STAMP_FILE" ]; then
    echo "Installing dependencies from requirements.txt ..."
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    touch "$STAMP_FILE"
fi

echo "Starting DCMA 14-Point Assessment app ..."
echo "(Press Ctrl+C to stop. Browser opens at http://localhost:8501)"
# Use `python -m streamlit` rather than the bare `streamlit` binary: some
# environments (e.g. Anaconda) ship a stale wrapper script that crashes.
exec python -m streamlit run app.py
