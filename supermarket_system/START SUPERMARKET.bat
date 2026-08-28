@echo off
title Supermarket Management System
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo.
  echo   The system is not installed yet on this computer.
  echo   Run INSTALL.bat first.
  echo.
  pause
  exit /b 1
)

"venv\Scripts\python.exe" run_server.py

echo.
echo   The system has stopped.
pause
