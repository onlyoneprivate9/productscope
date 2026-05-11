#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

PYTHON=""

try_python() {
  candidate=$1
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" check_gui_dependencies.py >/dev/null 2>&1; then
    PYTHON=$candidate
    return 0
  fi
  return 1
}

try_python_path() {
  candidate=$1
  if [ -x "$candidate" ] && "$candidate" check_gui_dependencies.py >/dev/null 2>&1; then
    PYTHON=$candidate
    return 0
  fi
  return 1
}

try_python python3 || try_python python || try_python_path "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" || true

if [ -z "$PYTHON" ]; then
  echo "No Python runtime with the required GUI dependencies was found."
  echo
  echo "Tried: python3, python, and the bundled Codex Python runtime."
  echo "Install dependencies from this folder with:"
  echo "  python3 -m pip install -r requirements.txt"
  exit 1
fi

if ! "$PYTHON" check_gui_dependencies.py; then
  exit 1
fi

exec "$PYTHON" gui_app.py
