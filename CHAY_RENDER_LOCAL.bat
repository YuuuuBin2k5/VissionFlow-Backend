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
echo   [*] Nhan Ctrl+C de dung tien trinh bat ky luc nao.
echo.
echo ==============================================================================
echo.

cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set "DATABASE_URL=postgresql://neondb_owner:npg_EwgAC4iWTSj0@ep-calm-queen-az3o70qo-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [LOI] Khong tim thay Python trong PATH tren may tinh cua ban!
    echo Vui long kiem tra lai cai dat Python.
    pause
    exit /b 1
)

python local_render_daemon.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ==============================================================================
    echo [CANH BAO] Tien trinh Render Daemon da dung lai (Exit code: %ERRORLEVEL%).
    echo ==============================================================================
    pause
)
