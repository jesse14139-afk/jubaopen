@echo off
setlocal DisableDelayedExpansion
title JUBAOPEN Read-Only Diagnostics
cd /d "%~dp0"

set "SCRIPT=%~dp0diagnose_jubaopen.py"
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "DB_FILE=I:\jubaopen_data\jubaopen-v208-schema222.db"
set "LOG_DIR=%~dp0logs"
set "OUT_DIR=%~dp0audit_%RANDOM%_%RANDOM%"

echo ============================================================
echo JUBAOPEN Read-Only Diagnostic Collector
echo This does not modify application code or production DB.
echo Internet access is required to download the pinned source.
echo ============================================================
echo.

if not exist "%SCRIPT%" goto MISSING_SCRIPT

where py >nul 2>&1
if errorlevel 1 goto CHECK_PYTHON
py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
if errorlevel 1 goto CHECK_PYTHON
set "PYTHON_EXE=py"
set "PYTHON_ARGS=-3"
goto PYTHON_READY

:CHECK_PYTHON
where python >nul 2>&1
if errorlevel 1 goto MISSING_PYTHON
python -c "import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
if errorlevel 1 goto MISSING_PYTHON
set "PYTHON_EXE=python"

:PYTHON_READY
if exist "%OUT_DIR%" goto OUTPUT_EXISTS
echo Python found.
echo Output folder: "%OUT_DIR%"
echo.

if not exist "%DB_FILE%" goto NO_DATABASE
if not exist "%LOG_DIR%\." goto DATABASE_ONLY

echo Collecting source, read-only DB information and log excerpts...
"%PYTHON_EXE%" %PYTHON_ARGS% "%SCRIPT%" --db "%DB_FILE%" --logs "%LOG_DIR%" --out "%OUT_DIR%"
set "RESULT=%ERRORLEVEL%"
goto FINISHED

:DATABASE_ONLY
echo Logs folder not found. Collecting source and read-only DB information.
"%PYTHON_EXE%" %PYTHON_ARGS% "%SCRIPT%" --db "%DB_FILE%" --out "%OUT_DIR%"
set "RESULT=%ERRORLEVEL%"
goto FINISHED

:NO_DATABASE
echo Default database not found. No other database will be guessed.
if not exist "%LOG_DIR%\." goto SOURCE_ONLY
echo Collecting source and log excerpts.
"%PYTHON_EXE%" %PYTHON_ARGS% "%SCRIPT%" --logs "%LOG_DIR%" --out "%OUT_DIR%"
set "RESULT=%ERRORLEVEL%"
goto FINISHED

:SOURCE_ONLY
echo Logs folder not found. Collecting pinned source only.
"%PYTHON_EXE%" %PYTHON_ARGS% "%SCRIPT%" --out "%OUT_DIR%"
set "RESULT=%ERRORLEVEL%"
goto FINISHED

:FINISHED
echo.
echo ============================================================
if "%RESULT%"=="0" goto SUCCESS
echo Collection was incomplete. Review error files in the output.
echo If source download failed, check your Internet connection.
goto SHOW_OUTPUT

:SUCCESS
echo Collection finished.

:SHOW_OUTPUT
echo Review log excerpts for passwords, tokens and private data.
echo This collection is NOT a runtime load test or a repair.
echo ============================================================
if exist "%OUT_DIR%\." start "" explorer.exe "%OUT_DIR%"
echo.
pause
exit /b %RESULT%

:MISSING_SCRIPT
echo ERROR: diagnose_jubaopen.py was not found.
echo Save the Python script beside this BAT file and try again.
echo Expected file: "%SCRIPT%"
echo.
pause
exit /b 1

:MISSING_PYTHON
echo ERROR: Python 3.9 or newer was not found.
echo Try placing these files on the computer running JUBAOPEN.
echo If Python is not installed, install it from python.org.
echo.
pause
exit /b 1

:OUTPUT_EXISTS
echo ERROR: Output folder already exists. Nothing was overwritten.
echo Double-click this BAT again to generate a new folder name.
echo.
pause
exit /b 1