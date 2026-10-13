@echo off
setlocal DisableDelayedExpansion
title JubaOpen 210.2.75 Launcher

set "APP_DIR=%~dp0"
set "DB_DIR=I:\jubaopen_data"
set "DB_FILE=%DB_DIR%\jubaopen-v208-schema222.db"
set "LOG_DIR=%APP_DIR%logs"
set "LOG_FILE=%LOG_DIR%\jubaopen-210.2.75.log"
set "HOST=127.0.0.1"
set "PORT=8765"
set "PYTHON_EXE="
set "PYTHON_ARGS="

if not exist "%APP_DIR%V207_center_service.py" goto ERR_FILES
if not exist "%APP_DIR%setup\first_run.py" goto ERR_FILES
if not exist "%APP_DIR%setup\prepare_database.py" goto ERR_FILES
if not exist "%APP_DIR%setup\windows_first_run.ps1" goto ERR_FILES
if not exist "%APP_DIR%web\admin.html" goto ERR_FILES
if not exist "%APP_DIR%web\echarts.min.js" goto ERR_FILES

where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
  )
)
if not defined PYTHON_EXE (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
  )
)
if not defined PYTHON_EXE goto ERR_PYTHON

%PYTHON_EXE% %PYTHON_ARGS% -c "import socket,sys;s=socket.socket();s.settimeout(0.6);sys.exit(0 if s.connect_ex(('127.0.0.1',8765))==0 else 1)" >nul 2>&1
if not errorlevel 1 goto ALREADY_RUNNING

if not exist "%DB_DIR%\." (
  mkdir "%DB_DIR%" >nul 2>&1
  if errorlevel 1 goto ERR_DB_DIR
)
if not exist "%DB_DIR%\." goto ERR_DB_DIR

if not exist "%LOG_DIR%\." (
  mkdir "%LOG_DIR%" >nul 2>&1
  if errorlevel 1 goto ERR_LOG_DIR
)
if not exist "%LOG_DIR%\." goto ERR_LOG_DIR

rem A zero-byte file is an interrupted fresh install, not a usable database.
if exist "%DB_FILE%" for %%A in ("%DB_FILE%") do if %%~zA EQU 0 del /q "%DB_FILE%" >nul 2>&1

if not exist "%DB_FILE%" goto FIRST_RUN
%PYTHON_EXE% %PYTHON_ARGS% -B -u "%APP_DIR%setup\prepare_database.py" --db "%DB_FILE%"
if errorlevel 1 goto ERR_VALIDATE
goto DB_READY

:FIRST_RUN
echo First launch: creating a fresh Schema 222 database.
set "JUBAOPEN_LAUNCH_PYTHON_EXE=%PYTHON_EXE%"
set "JUBAOPEN_LAUNCH_PYTHON_ARGS=%PYTHON_ARGS%"
set "JUBAOPEN_LAUNCH_APP_DIR=%APP_DIR%"
set "JUBAOPEN_LAUNCH_DATABASE=%DB_FILE%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%setup\windows_first_run.ps1"
set "JUBAOPEN_LAUNCH_PYTHON_EXE="
set "JUBAOPEN_LAUNCH_PYTHON_ARGS="
set "JUBAOPEN_LAUNCH_APP_DIR="
set "JUBAOPEN_LAUNCH_DATABASE="
if errorlevel 1 goto ERR_INIT
%PYTHON_EXE% %PYTHON_ARGS% -B -u "%APP_DIR%setup\prepare_database.py" --db "%DB_FILE%"
if errorlevel 1 goto ERR_VALIDATE

:DB_READY
echo.
echo Database: %DB_FILE%
echo URL: http://%HOST%:%PORT%/admin
echo Log: %LOG_FILE%
echo.
%PYTHON_EXE% %PYTHON_ARGS% -B -u "%APP_DIR%V207_center_service.py" --db "%DB_FILE%" --host "%HOST%" --port %PORT% >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo JubaOpen stopped with exit code %EXIT_CODE%.
echo See log: %LOG_FILE%
powershell -NoProfile -Command "if(Test-Path -LiteralPath '%LOG_FILE%'){Get-Content -LiteralPath '%LOG_FILE%' -Tail 30}"
pause
exit /b %EXIT_CODE%

:ALREADY_RUNNING
echo JubaOpen is already running at http://%HOST%:%PORT%/admin
start "" "http://%HOST%:%PORT%/admin"
exit /b 0

:ERR_INIT
echo [ERROR] Fresh Schema 222 database initialization failed.
echo Database: %DB_FILE%
pause
exit /b 11
:ERR_VALIDATE
echo [ERROR] Database validation or safe permission backfill failed.
echo Database: %DB_FILE%
pause
exit /b 15
:ERR_DB_DIR
echo [ERROR] Cannot create database directory: %DB_DIR%
pause
exit /b 13
:ERR_LOG_DIR
echo [ERROR] Cannot create log directory: %LOG_DIR%
pause
exit /b 14
:ERR_FILES
echo [ERROR] Application package is incomplete.
pause
exit /b 2
:ERR_PYTHON
echo [ERROR] Python 3.9 or newer was not found.
pause
exit /b 10
