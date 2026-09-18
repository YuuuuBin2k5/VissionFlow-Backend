@echo off
setlocal
chcp 65001 >nul
title VisionFlow Local Render Server (Studio & Unified Pipeline)
color 0A

cd /d "%~dp0"

echo =======================================================================
echo   🚀 VISIONFLOW LOCAL AUTOMATIC RENDER WORKER SERVER
echo   (Dong bo truc tiep Studio, OpenCut va Neon Database Queue)
echo =======================================================================
echo.

if not defined VISIONFLOW_API_BASE_URL set "VISIONFLOW_API_BASE_URL=https://visionflow-control-plane-free.onrender.com"
if exist "C:\Program Files (x86)\Digiarty\VideoProc Converter AI\ffmpeg.exe" set "PATH=C:\Program Files (x86)\Digiarty\VideoProc Converter AI;%PATH%"

set "PYTHON_EXE=venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python.exe"
)

if "%1"=="--remote" (
  echo [*] Che do: Remote Worker Poller (HTTP Leased Queue)
  echo [*] Ket noi Production Backend: %VISIONFLOW_API_BASE_URL%
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_remote_worker.ps1" %*
  set "workerExit=%ERRORLEVEL%"
  if not "%workerExit%"=="0" (
    echo [LOI] Remote Worker dung voi ma %workerExit%.
    pause
  )
  exit /b %workerExit%
)

echo [*] Che do: Unified Studio Local Render Server (Single Source of Truth)
echo [*] Tu dong lang nghe va render video tao tu ShortStudio, OpenCut va Auto-Production...
echo [*] Logs duoc ghi tai: logs\render_worker.log
echo -----------------------------------------------------------------------
echo.

"%PYTHON_EXE%" start_render_worker.py %*
set "workerExit=%ERRORLEVEL%"

if not "%workerExit%"=="0" (
  echo [LOI] Render Worker dung voi ma %workerExit%. Xem logs\render_worker.log de biet chi tiet.
  pause
)
exit /b %workerExit%
