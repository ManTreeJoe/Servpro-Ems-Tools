@echo off
REM Standalone hygiene scan launcher — runs the scan worker in its own
REM console window, completely independent of the home_web pywebview
REM process. Use this when the webview renderer is too bloated to run
REM the scan in-app (memory-constrained laptop, long session, etc.).
REM
REM Flow:
REM   1. Close home_web (frees the bloated webview process)
REM   2. Run this .bat
REM   3. Wait for scan to finish (visible progress in this console)
REM   4. Reopen home_web — Hygiene panel shows fresh data
REM
REM This script picks the right python executable by checking PATH
REM and falling back to py launcher. Edits to the scan worker are
REM picked up automatically — no rebuild needed.

setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo   Hygiene Scan — standalone background run
echo ============================================
echo.
echo Working directory: %CD%
echo.

REM Prefer pythonw if home_web is using it (same interpreter, same
REM packages installed). Falls through to python.exe if not found.
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Neither 'python' nor 'py' found on PATH.
        echo Install Python or activate the Linguar Hub venv.
        pause
        exit /b 1
    )
    py hygiene_scan_worker.py "" full
) else (
    python hygiene_scan_worker.py "" full
)

echo.
echo ============================================
echo   Scan finished. Reopen Hygiene to view results.
echo ============================================
echo.
pause
endlocal
