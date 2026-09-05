@echo off
chcp 65001 >nul
color 0B
title VisionFlow 24/7 Local Render Daemon

echo ==============================================================================
echo        [*] VISIONFLOW AUTONOMOUS LOCAL RENDER WORKER (FFMPEG 7.1)
echo ==============================================================================
echo.
echo   [*] Dang khoi dong Local Render Daemon...
echo   [*] Ket noi Database Neon PostgreSQL de lang nghe job render 24/7.
echo   [*] Moi video tao tren website se tu dong render tai day!
echo   [*] Nhan Ctrl+C de dung tien trinh bat ky luc nao.
echo.
echo ==============================================================================
echo.

cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set "DATABASE_URL=postgresql://neondb_owner:npg_TD8BYOyg6AVC@ep-restless-waterfall-azn7ekhh-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

if exist ".\venv\Scripts\python.exe" (
    set "PY_EXE=.\venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo [LOI] Khong tim thay Python trong PATH hoac virtualenv tren may tinh cua ban!
        echo Vui long kiem tra lai cai dat Python.
        pause
        exit /b 1
    )
    set "PY_EXE=python"
)

echo   [*] Su dung Python: %PY_EXE%
%PY_EXE% start_render_worker.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ==============================================================================
    echo [CANH BAO] Tien trinh Render Daemon da dung lai (Exit code: %ERRORLEVEL%).
    echo ==============================================================================
    pause
)
echo.
echo ==============================================================================
echo [THONG BAO] Tien trinh Render Daemon da ket thuc.
echo ==============================================================================
pause
