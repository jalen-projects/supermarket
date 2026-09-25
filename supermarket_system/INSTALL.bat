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
  echo   Run the installer in the "PYTHON INSTALLER" folder on the
  echo   flash disk, and TICK "Add python.exe to PATH" on the first
  echo   screen. Then run this file again.
  echo.
  pause
  exit /b 1
)

echo   [1/4] Preparing the program folder...
if not exist "venv\Scripts\python.exe" python -m venv venv

echo   [2/4] Installing the parts it needs...
REM The shop has no internet. The wheelhouse folder carries every package
REM with it, so the install works on a counter with no connection at all.
REM If it is missing we fall back to the internet, which is what a machine
REM with a connection will do anyway.
if exist "wheelhouse\*.whl" (
  echo         ...from the flash disk, no internet needed.
  "venv\Scripts\python.exe" -m pip install --quiet --no-index --find-links wheelhouse -r requirements.txt
  if errorlevel 1 (
    echo.
    echo   The offline packages did not fit this computer - usually that
    echo   means a different version of Python. Trying the internet instead.
    "venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    "venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  )
) else (
  "venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  "venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)

if errorlevel 1 (
  echo.
  echo   The parts could not be installed. Do not continue - call the
  echo   person who set this up.
  echo.
  pause
  exit /b 1
)

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
