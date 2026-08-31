@echo off
chcp 65001 > nul
title VisionFlow - Autonomous Local Render Daemon
echo ======================================================================
echo  🚀 VISIONFLOW AUTONOMOUS LOCAL RENDER DAEMON
echo  📡 Listening for QUEUED render jobs from Neon DB 24/7...
echo ======================================================================
cd /d "%~dp0VisionFlow_Bakend"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
python local_render_daemon.py
pause
