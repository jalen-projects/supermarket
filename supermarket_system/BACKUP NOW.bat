@echo off
title Backing up the supermarket data
cd /d "%~dp0"

echo.
echo  ==============================================================
echo    BACKING UP MAQAM FOOD CITY SUPERMARKET
echo  ==============================================================
echo.

if not exist "venv\Scripts\python.exe" (
  echo   The system is not installed on this computer.
  pause
  exit /b 1
)

REM Pass a drive letter to copy it straight onto a flash disk:
REM     "BACKUP NOW.bat" E:
if "%~1"=="" (
  "venv\Scripts\python.exe" manage.py backup_db
) else (
  "venv\Scripts\python.exe" manage.py backup_db --to %~1
)

echo.
echo   Keep the flash disk somewhere other than the shop counter.
echo.
pause
