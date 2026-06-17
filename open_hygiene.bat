@echo off
REM Open Hygiene as a STANDALONE window — its own pywebview process,
REM its own WebView2 renderer, totally isolated from the bloated
REM home_web shell. This is the escape hatch when home_web's shared
REM renderer is too memory-pressured to render Hygiene reliably.
REM
REM Sized baseline: ~50 MB for a fresh standalone window vs 3+ GB
REM for the home_web shared renderer after a long session.
REM
REM Workflow:
REM   1. (Optional) close home_web to free its bloated renderer
REM   2. Double-click this .bat
REM   3. Hygiene opens in its own window, ready to scan/view
REM   4. Close the window when done — process exits cleanly

setlocal
cd /d "%~dp0"

REM Use pythonw to avoid an extra console window. Falls back to
REM python or py launcher if pythonw isn't on PATH.
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw hygiene_web.py
    goto :done
)
where python >nul 2>nul
if not errorlevel 1 (
    start "" python hygiene_web.py
    goto :done
)
where py >nul 2>nul
if not errorlevel 1 (
    start "" py hygiene_web.py
    goto :done
)
echo ERROR: No python interpreter found on PATH.
pause
exit /b 1

:done
endlocal
