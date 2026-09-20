@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Jubaopen V207.7.0-dev Launcher
set "APP_DIR=%~dp0"
set "DB_FILE=%APP_DIR%data\jubaopen-v207.db"
set "LOG_DIR=%APP_DIR%logs"
set "BACKUP_DIR=%APP_DIR%backup"
set "LOG_FILE=%LOG_DIR%\jubaopen-v207.log"
set "HOST=127.0.0.1"
set "PORT=8765"
set "PYTHON_CMD="

if not exist "%APP_DIR%V207_center_service.py" goto ERR_FILES
if not exist "%APP_DIR%V207_shared_db.py" goto ERR_FILES
if not exist "%APP_DIR%V207_first_run.py" goto ERR_FILES
if not exist "%APP_DIR%V206_core_compat.py" goto ERR_FILES
if not exist "%APP_DIR%admin_v207.html" goto ERR_FILES

where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
  )
)
if not defined PYTHON_CMD goto ERR_PYTHON

if not exist "%APP_DIR%data" mkdir "%APP_DIR%data" >nul 2>&1
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%" >nul 2>&1

if not exist "%DB_FILE%" (
  echo ==================================================
  echo First launch: creating the Schema 210 database automatically.
  echo A strong initial administrator password is required.
  echo The password must be at least 12 characters and contain letters and digits.
  echo ==================================================
  if not defined JUBAOPEN_INITIAL_ADMIN_PASSWORD (
    set /p "JUBAOPEN_INITIAL_ADMIN_PASSWORD=Please enter initial admin password: "
    if not defined JUBAOPEN_INITIAL_ADMIN_PASSWORD goto ERR_PASSWORD
  )
  echo !JUBAOPEN_INITIAL_ADMIN_PASSWORD! > "%TEMP%\jubaopen_pwd_check.txt"
  %PYTHON_CMD% -c "import sys,re;pwd=open(r'%TEMP%\jubaopen_pwd_check.txt',encoding='utf-8').read().strip();sys.exit(0 if len(pwd)>=12 and re.search('[a-zA-Z]',pwd) and re.search('[0-9]',pwd) else 1)" >nul 2>&1
  set "PWD_CHECK_RESULT=!ERRORLEVEL!"
  del "%TEMP%\jubaopen_pwd_check.txt" >nul 2>&1
  if !PWD_CHECK_RESULT! NEQ 0 goto ERR_PASSWORD_WEAK
  %PYTHON_CMD% -u "%APP_DIR%V207_first_run.py" --db "%DB_FILE%"
  if errorlevel 1 goto ERR_INIT
)

for /f %%A in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "STAMP=%%A"
if not defined STAMP set "STAMP=before_start"
copy /y "%DB_FILE%" "%BACKUP_DIR%\before_start_%STAMP%.db" >nul

echo ==================================================
echo Jubaopen V207.7.0-dev
echo URL: http://%HOST%:%PORT%/admin
echo DB : %DB_FILE%
echo LOG: %LOG_FILE%
echo ==================================================
echo Starting service. Keep this window open; Ctrl+C stops it.
echo.

>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo [%date% %time%] Starting Jubaopen V207.7.0-dev
%PYTHON_CMD% -u "%APP_DIR%V207_center_service.py" --db "%DB_FILE%" --host "%HOST%" --port %PORT% 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%LOG_FILE%' -Append"
set "RC=%ERRORLEVEL%"
echo.
echo Service stopped. Exit code: %RC%
echo Log: %LOG_FILE%
pause
exit /b %RC%

:ERR_PASSWORD
echo [ERROR] JUBAOPEN_INITIAL_ADMIN_PASSWORD is not set.
echo No database was created and no service was started.
pause
exit /b 12

:ERR_PASSWORD_WEAK
echo [ERROR] Password does not meet requirements.
echo The password must be at least 12 characters and contain both letters and digits.
echo No database was created and no service was started.
pause
exit /b 13

:ERR_INIT
echo [ERROR] First-run initialization failed. No service was started.
echo Correct the message above and run this launcher again.
pause
exit /b 11

:ERR_FILES
echo [ERROR] The application package is incomplete or was not fully extracted.
echo Folder: %APP_DIR%
pause
exit /b 2

:ERR_PYTHON
echo [ERROR] Python 3.9 or newer was not found.
echo Install Python and enable the option "Add Python to PATH".
pause
exit /b 10
