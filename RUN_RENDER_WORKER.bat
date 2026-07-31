@echo off
title VisionFlow Automatic Video Render Worker
chcp 65001 > nul
color 0A

echo =======================================================================
echo     VISIONFLOW AUTOMATIC VIDEO RENDER WORKER SERVER
echo     (100 Percent GitHub Actions Official Pipeline and Neon DB Sync)
echo =======================================================================
echo.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    color 0C
    echo [ERROR] Khong tim thay Python Virtual Environment tai venv!
    echo Vui long kiem tra lai thu muc du an.
    echo.
    pause
    exit /b 1
)

echo [INFO] Dang khoi chay Render Server...
echo [INFO] Tu dong lang nghe cac yeu cau render video tu Web Console...
echo -----------------------------------------------------------------------
echo.

venv\Scripts\python.exe start_render_worker.py

echo.
echo -----------------------------------------------------------------------
echo [INFO] Render Worker da dung.
pause
