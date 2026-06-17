@echo off
setlocal
cd /d "%~dp0"

echo === EMS Tools build ===
echo.

REM Install/upgrade PyInstaller and runtime deps the first time
where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    py -m pip install --upgrade pyinstaller pillow python-docx pdfrw reportlab
)

REM Wipe previous build outputs
if exist build rmdir /s /q build
if exist "dist\EMS Tools" rmdir /s /q "dist\EMS Tools"

pyinstaller --noconfirm EMS_Tools.spec
if errorlevel 1 (
    echo.
    echo BUILD FAILED.
    pause
    exit /b 1
)

REM Drop README.txt next to the .exe so end users see it before clicking
if exist README.txt copy /y README.txt "dist\EMS Tools\README.txt" >nul

echo.
echo === Build complete ===
echo Output: dist\EMS Tools\EMS Tools.exe
echo Ship the ENTIRE dist\EMS Tools\ folder.
echo.
pause
