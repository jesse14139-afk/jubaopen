@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title Jubaopen V208.1.7 Launcher
set "APP_DIR=%~dp0"
set "DB_FILE=%APP_DIR%data\jubaopen-schema216.db"
set "LOG_DIR=%APP_DIR%logs"
set "LOG_FILE=%LOG_DIR%\jubaopen-208.1.8.log"
set "HOST=127.0.0.1"
set "PORT=8765"
set "PYTHON_CMD="

if not exist "%APP_DIR%V207_center_service.py" goto ERR_FILES
if not exist "%APP_DIR%setup\first_run.py" goto ERR_FILES
if not exist "%APP_DIR%web\admin.html" goto ERR_FILES
if not exist "%APP_DIR%web\echarts.min.js" goto ERR_FILES

where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
  where python >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD goto ERR_PYTHON
if not exist "%APP_DIR%data" mkdir "%APP_DIR%data" >nul 2>&1
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

if not exist "%DB_FILE%" (
  echo First launch: creating database and P1 preset data.
  if not defined JUBAOPEN_INITIAL_ADMIN_PASSWORD (
    set /p "JUBAOPEN_INITIAL_ADMIN_PASSWORD=Please enter initial admin password: "
    if not defined JUBAOPEN_INITIAL_ADMIN_PASSWORD goto ERR_PASSWORD
  )
  %PYTHON_CMD% -B -u "%APP_DIR%setup\first_run.py" --db "%DB_FILE%"
  if errorlevel 1 goto ERR_INIT
)

echo URL: http://%HOST%:%PORT%/admin
powershell -NoProfile -Command "& { & %PYTHON_CMD% -B -u '%APP_DIR%V207_center_service.py' --db '%DB_FILE%' --host '%HOST%' --port %PORT% 2>&1 | Tee-Object -FilePath '%LOG_FILE%' -Append; exit $LASTEXITCODE }"
pause
exit /b %ERRORLEVEL%
:ERR_PASSWORD
echo [ERROR] Initial administrator password is required.
pause
exit /b 12
:ERR_INIT
echo [ERROR] Initialization failed.
pause
exit /b 11
:ERR_FILES
echo [ERROR] Application package is incomplete.
pause
exit /b 2
:ERR_PYTHON
echo [ERROR] Python 3.9 or newer was not found.
pause
exit /b 10
