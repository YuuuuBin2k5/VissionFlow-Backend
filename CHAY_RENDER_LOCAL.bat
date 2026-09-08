@echo off
chcp 65001 >nul
color 0B
title VisionFlow 24/7 Local Render Daemon (Worker: desktop-main)

echo ==============================================================================
echo        [*] VISIONFLOW AUTONOMOUS LOCAL RENDER WORKER (CANONICAL V1)
echo ==============================================================================
echo.
echo   [*] Worker ID    : desktop-main
echo   [*] Control Plane: https://visionflow-control-plane-free.onrender.com
echo   [*] Storage Cache: D:\VisionFlowWorker
echo   [*] FFmpeg Target: Canonical FFmpeg 7.1 Engine
echo.
echo   [*] Ket noi Database & Control Plane de nhan job render tu dong 24/7.
echo   [*] Moi video tao tren website (Vercel) se tu dong duoc may tinh nay render!
echo   [*] Nhan Ctrl+C de dung tien trinh bat ky luc nao.
echo ==============================================================================
echo.

cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set "PATH=C:\Program Files (x86)\Digiarty\VideoProc Converter AI;%PATH%"
set "VISIONFLOW_API_BASE_URL=https://visionflow-control-plane-free.onrender.com"
set "VISIONFLOW_WORKER_ID=desktop-main"
set "VISIONFLOW_WORKER_TOKEN=d3afd930a243b74210f83efe8dc2eb372383470af47d77bd9a2d9e1550329a81"
set "VISIONFLOW_WORKER_WORK_DIR=D:\VisionFlowWorker"

if exist ".\venv\Scripts\python.exe" (
    set "PY_EXE=.\venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo [LOI] Khong tim thay Python trong PATH hoac virtualenv!
        pause
        exit /b 1
    )
    set "PY_EXE=python"
)

echo   [*] Python: %PY_EXE%
echo   [*] Kiem tra ket noi va dang ky Worker voi Production Backend...
%PY_EXE% -m worker.remote_render_worker --check
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [LOI] Khong the dang ky hoac xac thuc Worker voi Production Backend!
    echo Vui long kiem tra lai ket noi Internet hoac Token.
    pause
    exit /b 1
)

echo.
echo   [*] Worker da dang ky thanh cong. Bat dau lang nghe Render Jobs...
echo ==============================================================================
%PY_EXE% -m worker.remote_render_worker

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ==============================================================================
    echo [CANH BAO] Worker da dung lai (Exit code: %ERRORLEVEL%).
    echo ==============================================================================
    pause
)
