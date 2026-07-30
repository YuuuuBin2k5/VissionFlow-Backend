@echo off
title VisionFlow Automatic Render Worker (1-Click Local)
color 0A
cd /d "%~dp0"

echo =======================================================
echo 🚀 VISIONFLOW AUTOMATIC LOCAL RENDER SERVER
echo =======================================================
echo.
echo [*] System is active and monitoring database for new videos...
echo [*] Every video created on website will render automatically here!
echo.

.\venv\Scripts\python.exe start_render_worker.py

pause
