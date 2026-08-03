@echo off
echo ================================================================
echo  VisionFlow Backend - Khoi dong Control Plane API (port 8000)
echo ================================================================

cd /d "%~dp0services\control-plane"

echo [1/2] Kiem tra virtualenv...
if not exist "..\..\venv\Scripts\python.exe" (
    echo [ERROR] Khong tim thay venv. Chay: python -m venv venv
    pause
    exit /b 1
)

echo [2/2] Khoi dong server voi env variables tu .env...
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" (
        if not "%%A:~0,1%"=="#" (
            set "%%A=%%B"
        )
    )
)

echo.
echo [OK] Dang khoi dong uvicorn tai http://localhost:8000
echo [OK] API Docs: http://localhost:8000/docs
echo [OK] Dubbing dispatch: http://localhost:8000/api/v1/dubbing/dispatch
echo.
..\..\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
