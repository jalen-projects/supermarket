@echo off
title Allow other tills to reach this computer
cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem  Windows Firewall blocks incoming connections by default, so a second till
rem  typing the right address still sees nothing. This opens the one port the
rem  supermarket system listens on - and nothing else.
rem
rem  It only ever has to be run once, on the computer that RUNS the system.
rem  Do not run it on the other tills; they do not need it.
rem
rem  Must be run as administrator: right-click this file -> Run as administrator.
rem ---------------------------------------------------------------------------

net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo.
  echo   ==========================================================
  echo     THIS MUST BE RUN AS ADMINISTRATOR
  echo   ==========================================================
  echo.
  echo   Windows will not let a normal program change the firewall.
  echo.
  echo     1. Close this window.
  echo     2. Right-click "ALLOW OTHER TILLS.bat"
  echo     3. Choose "Run as administrator"
  echo     4. Answer Yes to the Windows question.
  echo.
  pause
  exit /b 1
)

if "%SMMS_PORT%"=="" set SMMS_PORT=8000

echo.
echo   Opening port %SMMS_PORT% for the supermarket system...
echo.

rem Remove any older rule first, so running this twice does not stack up
rem duplicate rules in the firewall list.
netsh advfirewall firewall delete rule name="Supermarket Management System" >nul 2>&1

netsh advfirewall firewall add rule ^
  name="Supermarket Management System" ^
  dir=in action=allow protocol=TCP localport=%SMMS_PORT% ^
  profile=private,domain ^
  description="Lets other tills in this shop reach the supermarket system. Local network only."

if not "%errorlevel%"=="0" (
  echo.
  echo   Something went wrong. Write down what is shown above and send it over.
  echo.
  pause
  exit /b 1
)

echo.
echo   ==========================================================
echo     DONE. Other tills can now reach this computer.
echo   ==========================================================
echo.
echo   Next:
echo     1. Make sure START SUPERMARKET is running on this computer.
echo     2. On the other computer, open a browser and type the address
echo        shown under "Other computers" in the menu.
echo.
echo   Note: this only opens the port on PRIVATE and DOMAIN networks -
echo   your shop and office. If Windows has your shop wi-fi marked as a
echo   Public network, set it to Private in Windows network settings,
echo   which is correct for a shop anyway.
echo.
pause
