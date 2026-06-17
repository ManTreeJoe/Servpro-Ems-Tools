@echo off
echo ============================================
echo           IE File Organizer
echo ============================================
echo.

set /p CLIENT="Client name (Last First): "

set EXTRA=
set /p LAFIRE="LA Fire job? (y/n, default n): "
if /i "%LAFIRE%"=="y" set EXTRA=%EXTRA% -LaFire

set /p FNF="First name listed first in folder? (y/n, default n): "
if /i "%FNF%"=="y" set EXTRA=%EXTRA% -FirstNameFirst

set /p YEAR="Year (press Enter for current year): "
if not "%YEAR%"=="" set EXTRA=%EXTRA% -Year %YEAR%

echo.
echo Job type:
echo   1. PO PB  (Pack Out / Pack Back)  [default]
echo   2. EMS
echo   3. Contents
echo   4. Recon
echo   5. PO     (Pack Out only)
echo   6. PB     (Pack Back only)
echo   7. Other  (type manually)
echo.
set /p JTCHOICE="Select [1-7, Enter for default]: "

if "%JTCHOICE%"=="1" set EXTRA=%EXTRA% -JobType "PO PB"
if "%JTCHOICE%"=="2" set EXTRA=%EXTRA% -JobType "EMS"
if "%JTCHOICE%"=="3" set EXTRA=%EXTRA% -JobType "Contents"
if "%JTCHOICE%"=="4" set EXTRA=%EXTRA% -JobType "Recon"
if "%JTCHOICE%"=="5" set EXTRA=%EXTRA% -JobType "PO"
if "%JTCHOICE%"=="6" set EXTRA=%EXTRA% -JobType "PB"
if "%JTCHOICE%"=="7" (
    set /p CUSTOM="Job type: "
    set EXTRA=%EXTRA% -JobType "%CUSTOM%"
)

echo.
powershell -ExecutionPolicy Bypass -File "%~dp0sort_files.ps1" "%CLIENT%"%EXTRA%

echo.
pause
