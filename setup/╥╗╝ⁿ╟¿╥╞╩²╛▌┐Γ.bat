@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ========================================
echo JubaOpen 210.2.24 客户治理数据库一键修复
echo ========================================
if "%~1"=="" (set /p "DB=请粘贴数据库完整路径后回车: ") else (set "DB=%~1")
set "DB=%DB:\"=%"
if not exist "%DB%" (echo [失败] 找不到数据库: %DB%&pause&exit /b 2)
echo 请先关闭 JubaOpen 服务。脚本会自动备份数据库。
choice /C YN /M "确认继续"
if errorlevel 2 exit /b 1
where py >nul 2>nul && (py -3 "%~dp0apply_contact_governance_fix.py" "%DB%") || (python "%~dp0apply_contact_governance_fix.py" "%DB%")
if errorlevel 1 (echo [失败] 修复未完成，数据库已自动恢复。&pause&exit /b 3)
echo [成功] 数据库修复完成。请启动服务并按 Ctrl+F5 刷新页面。
pause
