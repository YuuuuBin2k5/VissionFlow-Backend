@echo off
setlocal
chcp 65001 >nul
title VisionFlow Local Render Server
color 0A

cd /d "%~dp0"

echo =======================================================================
echo   VISIONFLOW AUTOMATIC LOCAL RENDER SERVER
echo   Ket noi truc tiep Database Neon va lang nghe video tu Studio
echo =======================================================================
echo.

set "PYTHON_EXE=venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python.exe"
)

"%PYTHON_EXE%" start_render_worker.py %*

if %ERRORLEVEL% NEQ 0 (
  echo.
  echo [LOI] Render Worker da dung. Xem thong bao phia tren.
  pause
)
