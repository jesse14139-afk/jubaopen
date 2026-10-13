@echo off
setlocal EnableExtensions
chcp 65001 >nul
title JubaOpen Threads 数据库迁移

rem ============================================================
rem JubaOpen Threads 数据库迁移启动器
rem 必须与 run_threads_migration.py 放在同一项目根目录
rem ============================================================

cd /d "%~dp0"

set "ROOT=%~dp0"
set "MIGRATION_PY=%ROOT%run_threads_migration.py"
set "MIGRATION_SQL=%ROOT%setup\V223_threads_platform.sql"
set "LOG_DIR=%ROOT%migration_logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

rem 使用 PowerShell 生成不会重名的时间戳。
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "STAMP=%%I"

if not defined STAMP set "STAMP=unknown_time"

set "LOG_FILE=%LOG_DIR%\threads_migration_%STAMP%.log"

cls
echo ============================================================
echo       JubaOpen Threads 数据库迁移
echo ============================================================
echo.
echo 项目目录：
echo %ROOT%
echo.
echo 本程序将：
echo   1. 检查 Python
echo   2. 检查迁移程序和 SQL 文件
echo   3. 由迁移程序备份数据库
echo   4. 注册 Threads 平台
echo   5. 检查执行结果
echo.
echo 重要：
echo   - 执行前请停止 JubaOpen 服务
echo   - 不要在服务仍然写入数据库时迁移
echo   - 不要选择空数据库或错误的数据库
echo.
echo 日志文件：
echo %LOG_FILE%
echo.
echo ------------------------------------------------------------
echo 正在检查运行环境……
echo ------------------------------------------------------------
echo.

rem ============================================================
rem 检查迁移程序
rem ============================================================

if not exist "%MIGRATION_PY%" (
    echo [失败] 找不到迁移程序：
    echo %MIGRATION_PY%
    echo.
    echo 请确认以下文件与本 BAT 位于同一目录：
    echo run_threads_migration.py
    echo.
    >>"%LOG_FILE%" echo [FAILED] Missing migration program: %MIGRATION_PY%
    goto :FAILED
)

echo [通过] 已找到 run_threads_migration.py
>>"%LOG_FILE%" echo [OK] Migration program: %MIGRATION_PY%

rem ============================================================
rem 检查 SQL 文件
rem ============================================================

if not exist "%MIGRATION_SQL%" (
    echo [失败] 找不到数据库迁移文件：
    echo %MIGRATION_SQL%
    echo.
    echo 正确位置应该是：
    echo setup\V223_threads_platform.sql
    echo.
    >>"%LOG_FILE%" echo [FAILED] Missing migration SQL: %MIGRATION_SQL%
    goto :FAILED
)

echo [通过] 已找到 setup\V223_threads_platform.sql
>>"%LOG_FILE%" echo [OK] Migration SQL: %MIGRATION_SQL%

rem ============================================================
rem 检查 Python
rem 优先使用 py -3，其次使用 python
rem ============================================================

set "PYTHON_CMD="

where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
    )
)

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python --version >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_CMD=python"
        )
    )
)

if not defined PYTHON_CMD (
    echo.
    echo [失败] 没有找到可用的 Python 3。
    echo.
    echo 请先安装 Python 3：
    echo https://www.python.org/downloads/windows/
    echo.
    echo 安装时请勾选：
    echo Add Python to PATH
    echo.
    >>"%LOG_FILE%" echo [FAILED] Python 3 not found.
    goto :FAILED
)

echo [通过] Python 命令：%PYTHON_CMD%
>>"%LOG_FILE%" echo [OK] Python command: %PYTHON_CMD%

for /f "delims=" %%V in ('%PYTHON_CMD% --version 2^>^&1') do (
    echo [通过] %%V
    >>"%LOG_FILE%" echo [OK] %%V
)

echo.
echo ------------------------------------------------------------
echo 环境检查通过
echo ------------------------------------------------------------
echo.
echo 接下来迁移程序会要求你输入 SQLite 数据库完整路径。
echo.
echo 示例：
echo C:\JubaOpen\data\jubaopen.db
echo.
echo 可以把数据库文件直接拖入窗口，然后按 Enter。
echo 路径外面的双引号会由迁移程序自动处理。
echo.
echo 确认迁移时必须输入大写：
echo YES
echo.
pause

cls
echo ============================================================
echo       正在执行 Threads 数据库迁移
echo ============================================================
echo.
echo 启动时间：%DATE% %TIME%
echo.
echo 请按照屏幕提示选择数据库。
echo.
echo ------------------------------------------------------------

>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo ============================================================
>>"%LOG_FILE%" echo Migration started: %DATE% %TIME%
>>"%LOG_FILE%" echo ============================================================

rem 通过 PowerShell Tee-Object 同时显示输出并保存日志。
rem 如果 PowerShell 不可用，则直接运行 Python。

where powershell >nul 2>&1

if errorlevel 1 (
    %PYTHON_CMD% "%MIGRATION_PY%"
    set "RESULT=%ERRORLEVEL%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "& { & %PYTHON_CMD% '%MIGRATION_PY%' 2^>^&1 | Tee-Object -FilePath '%LOG_FILE%' -Append; exit $LASTEXITCODE }"
    set "RESULT=%ERRORLEVEL%"
)

echo.
echo ------------------------------------------------------------
echo 迁移程序返回码：%RESULT%
echo ------------------------------------------------------------
echo.

>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo Migration exit code: %RESULT%
>>"%LOG_FILE%" echo Migration finished: %DATE% %TIME%

if not "%RESULT%"=="0" goto :FAILED

goto :SUCCESS


:SUCCESS
color 2F
echo ============================================================
echo.
echo                 Threads 数据库迁移成功
echo.
echo ============================================================
echo.
echo 迁移程序已成功完成检查和写入。
echo.
echo 请确认上方结果中存在类似内容：
echo.
echo   platform_id   : threads
echo   platform_code : threads
echo   platform_name : Threads
echo   status        : active
echo.
echo 数据库迁移前的备份文件通常位于数据库旁边，文件名类似：
echo.
echo   jubaopen.db.before_threads_日期_时间.bak
echo.
echo 完整日志：
echo %LOG_FILE%
echo.
echo 现在可以：
echo   1. 重新启动 JubaOpen
echo   2. 加载新版浏览器扩展
echo   3. 打开 https://www.threads.com/messages/
echo.
echo [SUCCESS] Threads migration completed successfully.>>"%LOG_FILE%"
echo.
pause
exit /b 0


:FAILED
color 4F
echo.
echo ============================================================
echo.
echo                 Threads 数据库迁移失败
echo.
echo ============================================================
echo.
echo 数据库迁移没有成功完成。
echo.
echo 请检查：
echo   1. JubaOpen 是否已经停止
echo   2. 是否选择了正确的 SQLite 数据库
echo   3. 数据库中是否存在 platforms 表
echo   4. Python 3 是否正确安装
echo   5. setup\V223_threads_platform.sql 是否存在
echo   6. run_threads_migration.py 是否存在
echo.
echo 如果程序已经生成数据库备份，请保留备份，不要删除。
echo.
echo 日志文件：
echo %LOG_FILE%
echo.
echo [FAILED] Threads migration failed.>>"%LOG_FILE%"
pause
exit /b 1
