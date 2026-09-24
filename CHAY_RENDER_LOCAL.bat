@echo off
setlocal
chcp 65001 >nul
title VisionFlow Local Render Stack
color 0A

cd /d "%~dp0"

echo =======================================================================
echo   VISIONFLOW LOCAL PIPELINE + REMOTE RENDER STACK
echo   PostgreSQL Docker local + Backend Render qua HTTPS - KHONG dung Neon
echo =======================================================================
echo.

set "WORKER_LAUNCHER=%~dp0scripts\start_local_render_stack.ps1"
if not exist "%WORKER_LAUNCHER%" (
  echo [LOI] Khong tim thay launcher: "%WORKER_LAUNCHER%"
  pause
  exit /b 1
)

if not defined VISIONFLOW_API_BASE_URL (
  set "VISIONFLOW_API_BASE_URL=https://visionflow-control-plane-free.onrender.com"
)

echo [*] Backend: %VISIONFLOW_API_BASE_URL%
echo [*] Pipeline worker dung PostgreSQL Docker local.
echo [*] Final render worker claim job qua HTTPS; khong ket noi Neon.
echo.

rem Prevent a parent PowerShell 7 session from leaking an incompatible module
rem search path into Windows PowerShell 5.1, which decrypts the DPAPI token.
set "PSModulePath="
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%WORKER_LAUNCHER%" -ApiBaseUrl "%VISIONFLOW_API_BASE_URL%" %*
set "WORKER_EXIT_CODE=%ERRORLEVEL%"

if not "%WORKER_EXIT_CODE%"=="0" (
  echo.
  echo [LOI] Remote Render Worker da dung voi ma loi %WORKER_EXIT_CODE%.
  echo Kiem tra worker token DPAPI va cau hinh tren Render.
  pause
)

exit /b %WORKER_EXIT_CODE%
