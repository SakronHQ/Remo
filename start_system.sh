#!/usr/bin/env bash
# SmartVision One-Click Launcher (POSIX / Linux / macOS)
# Phase 9: Production Packaging & Handover

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/smartvision/run_system.py" ]; then
    TARGET_DIR="$SCRIPT_DIR/smartvision"
else
    TARGET_DIR="$SCRIPT_DIR"
fi

if [ -f "$TARGET_DIR/.venv/bin/python" ]; then
    PY_EXE="$TARGET_DIR/.venv/bin/python"
elif [ -f "$TARGET_DIR/.venv/Scripts/python.exe" ]; then
    PY_EXE="$TARGET_DIR/.venv/Scripts/python.exe"
else
    PY_EXE="python3"
fi

exec "$PY_EXE" "$TARGET_DIR/run_system.py" "$@"
