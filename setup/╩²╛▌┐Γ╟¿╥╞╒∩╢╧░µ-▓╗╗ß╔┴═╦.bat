@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
color 0F
title JubaOpen Database Migration Diagnostic

set "BATDIR=%~dp0"
set "MIGRATOR=%BATDIR%apply_contact_governance_fix.py"
set "LOG=%BATDIR%migration-diagnostic.log"

>"%LOG%" echo ============================================================
>>"%LOG%" echo JubaOpen database migration diagnostic log
>>"%LOG%" echo Started: %date% %time%
>>"%LOG%" echo BAT directory: %BATDIR%
>>"%LOG%" echo Migrator: %MIGRATOR%
>>"%LOG%" echo ============================================================

echo.
echo ============================================================
echo JubaOpen Database Migration - Diagnostic Mode
echo This window will NOT close automatically.
echo Log file: %LOG%
echo ============================================================
echo.

if not exist "%MIGRATOR%" (
  echo [ERROR] apply_contact_governance_fix.py was not found.
  echo Put this BAT in the same setup folder as that Python file.
  >>"%LOG%" echo ERROR: Migrator not found.
  goto :ENDFAIL
)

set "DB=%~1"
if not defined DB (
  echo You can drag the active JubaOpen .db file into this window.
  echo Or paste its full path below, then press Enter.
  set /p "DB=Database path: "
)
set "DB=%DB:"=%"

if not defined DB (
  echo [ERROR] No database path was entered.
  >>"%LOG%" echo ERROR: Empty database path.
  goto :ENDFAIL
)
if not exist "%DB%" (
  echo [ERROR] Database file does not exist:
  echo %DB%
  >>"%LOG%" echo ERROR: Database does not exist: %DB%
  goto :ENDFAIL
)

>>"%LOG%" echo Database: %DB%
echo.
echo Database selected:
echo %DB%
echo.
echo IMPORTANT: Close JubaOpen before continuing.
choice /C YN /N /M "Continue migration? [Y/N]: "
if errorlevel 2 goto :CANCEL

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python 3 was not found.
  echo Install Python 3 and select Add Python to PATH during installation.
  >>"%LOG%" echo ERROR: Python command not found.
  goto :ENDFAIL
)

>>"%LOG%" echo Python command: %PY%
echo.
echo Running migration. Please wait...
echo ------------------------------------------------------------
%PY% "%MIGRATOR%" "%DB%" 1>"%BATDIR%migration-output.tmp" 2>"%BATDIR%migration-error.tmp"
set "RC=%ERRORLEVEL%"
type "%BATDIR%migration-output.tmp"
type "%BATDIR%migration-error.tmp"
>>"%LOG%" type "%BATDIR%migration-output.tmp"
>>"%LOG%" type "%BATDIR%migration-error.tmp"
del /q "%BATDIR%migration-output.tmp" "%BATDIR%migration-error.tmp" >nul 2>nul
>>"%LOG%" echo Exit code: %RC%

if not "%RC%"=="0" (
  echo ------------------------------------------------------------
  echo [FAILED] Migration failed. Exit code: %RC%
  echo Please send migration-diagnostic.log for diagnosis.
  goto :ENDFAIL
)

echo ------------------------------------------------------------
echo [SUCCESS] Database migration completed.
echo It is now safe to restart JubaOpen.
>>"%LOG%" echo RESULT: SUCCESS
copy /y "%LOG%" "%BATDIR%migration-success.log" >nul

goto :END

:CANCEL
echo Cancelled. No migration was run.
>>"%LOG%" echo RESULT: CANCELLED
goto :END

:ENDFAIL
>>"%LOG%" echo RESULT: FAILED
color 4F
echo.
echo Do NOT start JubaOpen yet if you are unsure.
echo Send this file for diagnosis:
echo %LOG%
goto :END

:END
echo.
echo Press any key to close this window...
pause >nul
endlocal
