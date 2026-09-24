#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

PYTHON=""

try_python() {
  candidate=$1
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -m app.check_gui_dependencies >/dev/null 2>&1; then
    PYTHON=$candidate
    return 0
  fi
  return 1
}

try_python_path() {
  candidate=$1
  if [ -x "$candidate" ] && "$candidate" -m app.check_gui_dependencies >/dev/null 2>&1; then
    PYTHON=$candidate
    return 0
  fi
  return 1
}

try_python_path "$SCRIPT_DIR/.venv/bin/python" || try_python python3 || try_python python || try_python_path "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" || true

if [ -z "$PYTHON" ]; then
  echo "No Python runtime with the required GUI dependencies was found."
  echo
  echo "Tried: .venv, python3, python, and the bundled Codex Python runtime."
  echo "Install dependencies from this folder with:"
  echo "  python3 -m pip install -r requirements.txt"
  exit 1
fi

if ! "$PYTHON" -m app.check_gui_dependencies; then
  exit 1
fi

exec "$PYTHON" -m app.gui_app
