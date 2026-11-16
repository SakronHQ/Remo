@echo off
setlocal
REM SmartVision One-Click Launcher (Batch)
REM Phase 9: Production Packaging & Handover

set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%run_system.py" (
    set "TARGET_DIR=%SCRIPT_DIR%"
) else (
    set "TARGET_DIR=%SCRIPT_DIR%smartvision"
)

if exist "%TARGET_DIR%\.venv\Scripts\python.exe" (
    set "PY_EXE=%TARGET_DIR%\.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

"%PY_EXE%" "%TARGET_DIR%\run_system.py" %*
endlocal
