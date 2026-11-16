#!/usr/bin/env python3
"""
SmartVision - Root System Launcher Delegator
Phase 8: System Integration & Stack Orchestration.
Delegates command execution directly to smartvision/run_system.py.
"""
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SMARTVISION_DIR = os.path.join(CURRENT_DIR, "smartvision")
SCRIPT_PATH = os.path.join(SMARTVISION_DIR, "run_system.py")

if __name__ == "__main__":
    if os.path.exists(SCRIPT_PATH):
        sys.path.insert(0, SMARTVISION_DIR)
        with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
            code = compile(f.read(), SCRIPT_PATH, "exec")
            exec(code, {"__name__": "__main__", "__file__": SCRIPT_PATH})
    else:
        sys.stderr.write(f"Error: {SCRIPT_PATH} not found.\n")
        sys.exit(1)
