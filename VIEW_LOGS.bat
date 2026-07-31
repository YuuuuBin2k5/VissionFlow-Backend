@echo off
title VisionFlow Render Worker Log Viewer
cd /d "%~dp0"

if exist "logs\render_worker.log" (
    echo [INFO] Dang mo file log: logs\render_worker.log ...
    start notepad "logs\render_worker.log"
) else (
    echo [NOTICE] Chua co file log nao duoc tao. Vui long chay RUN_RENDER_WORKER.bat truoc.
    pause
)
