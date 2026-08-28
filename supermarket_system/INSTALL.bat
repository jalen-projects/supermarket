@echo off
title Installing the Supermarket Management System
cd /d "%~dp0"

echo.
echo  ==============================================================
echo    SUPERMARKET MANAGEMENT SYSTEM - installation
echo  ==============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo   Python is not installed on this computer.
  echo.
  echo   Download it from python.org, and TICK "Add Python to PATH"
  echo   during installation. Then run this file again.
  echo.
  pause
  exit /b 1
)

echo   [1/4] Preparing the program folder...
if not exist "venv\Scripts\python.exe" python -m venv venv

echo   [2/4] Installing the parts it needs...
"venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
"venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

echo   [3/4] Creating the shop's database...
"venv\Scripts\python.exe" manage.py migrate --noinput
"venv\Scripts\python.exe" manage.py collectstatic --noinput >nul

echo   [4/4] Setting up the shop...
"venv\Scripts\python.exe" manage.py setup_shop

echo.
echo  ==============================================================
echo    Done. Start the system with "START SUPERMARKET.bat"
echo.
echo    Sign in with username: admin
echo    Change that password immediately under Setup - Users.
echo  ==============================================================
echo.
pause
