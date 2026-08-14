@echo off
cd /d "%~dp0"
echo =====================================================
echo   SERVPRONET bulletin check
echo =====================================================
echo.
echo [1/2] checking the site for new or changed bulletins...
python bulletin_watch.py scan
echo.
echo [2/2] comparing against X:\IE_Public\Forms_Contracts\Bulletins ...
python bulletin_watch.py compare-local
echo.
echo -----------------------------------------------------
echo  To download the newer versions and see what changed:
echo     python bulletin_watch.py compare-local --download
echo -----------------------------------------------------
echo.
pause
