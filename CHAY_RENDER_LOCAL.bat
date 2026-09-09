@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [*] Ket noi Production Backend qua HTTPS
echo [*] Render Queue: Remote Worker
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_remote_worker.ps1" %*
exit /b %ERRORLEVEL%
