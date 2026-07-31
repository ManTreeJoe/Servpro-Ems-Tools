@echo off
setlocal
cd /d "%~dp0"

echo === Linguar Hub build ===
echo.

REM Install/upgrade PyInstaller and runtime deps the first time
where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    py -m pip install --upgrade pyinstaller pillow python-docx pdfrw reportlab
)

REM Wipe previous build outputs
if exist build rmdir /s /q build
if exist "dist\Linguar Hub" rmdir /s /q "dist\Linguar Hub"

pyinstaller --noconfirm Linguar_Hub.spec
if errorlevel 1 (
    echo.
    echo BUILD FAILED.
    pause
    exit /b 1
)

REM Drop README.txt next to the .exe so end users see it before clicking
if exist README.txt copy /y README.txt "dist\Linguar Hub\README.txt" >nul

echo.
echo === Build complete ===
echo Output: dist\Linguar Hub\Linguar Hub.exe
echo Ship the ENTIRE dist\Linguar Hub\ folder.
echo.
pause
