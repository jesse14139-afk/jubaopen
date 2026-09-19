@echo off
chcp 936 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Jubaopen V207.2.0 Launcher

set "APP_DIR=%~dp0"
set "DB_FILE=%APP_DIR%data\jubaopen-v207.db"
set "LOG_DIR=%APP_DIR%logs"
set "BACKUP_DIR=%APP_DIR%backup"
set "LOG_FILE=%LOG_DIR%\jubaopen-v207.log"
set "HOST=127.0.0.1"
set "PORT=8765"
set "PYTHON_CMD="

if not exist "%APP_DIR%V207_center_service.py" goto ERR_SERVICE
if not exist "%APP_DIR%V207_shared_db.py" goto ERR_DBMODULE
if not exist "%APP_DIR%V206_core_compat.py" goto ERR_COMPAT
if not exist "%APP_DIR%admin_v207.html" goto ERR_ADMIN
if not exist "%APP_DIR%data" mkdir "%APP_DIR%data" >nul 2>&1
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%" >nul 2>&1

where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
  )
)

if not defined PYTHON_CMD goto ERR_PYTHON

if exist "%DB_FILE%" (
  for /f "tokens=1-3 delims=/- " %%a in ('date /t') do set "D=%%a_%%b_%%c"
  for /f "tokens=1-2 delims=: " %%a in ('time /t') do set "T=%%a%%b"
  set "T=!T: =0!"
  copy /y "%DB_FILE%" "%BACKUP_DIR%\before_start_!D!_!T!.db" >nul
)

echo ================================================
echo Jubaopen V207.2.0
echo APP : %APP_DIR%
echo DB  : %DB_FILE%
echo URL : http://%HOST%:%PORT%/admin
echo LOG : %LOG_FILE%
echo ================================================
echo.
echo Starting service. Press Ctrl+C to stop.
echo.

echo.>>"%LOG_FILE%"
echo [%date% %time%] Starting Jubaopen V207.2.0>>"%LOG_FILE%"

%PYTHON_CMD% -u "%APP_DIR%V207_center_service.py" --db "%DB_FILE%" --host "%HOST%" --port %PORT% >>"%LOG_FILE%" 2>&1
set "RC=%ERRORLEVEL%"

echo.
echo Service stopped. Exit code: %RC%
echo Log: %LOG_FILE%
pause
exit /b %RC%

:ERR_SERVICE
echo [ERROR] V207_center_service.py was not found.
echo Folder: %APP_DIR%
pause
exit /b 2

:ERR_DBMODULE
echo [ERROR] V207_shared_db.py was not found.
echo Folder: %APP_DIR%
pause
exit /b 3

:ERR_COMPAT
echo [ERROR] V206_core_compat.py was not found.
echo V207 center service requires the V206 compatibility layer.
pause
exit /b 5

:ERR_ADMIN
echo [ERROR] admin_v207.html was not found.
echo The /admin page cannot be served without this file.
pause
exit /b 4

:ERR_PYTHON
echo [ERROR] Python 3.9 or newer was not found.
echo Install Python and enable Add Python to PATH.
pause
exit /b 10
