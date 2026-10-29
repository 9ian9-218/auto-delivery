@echo off
chcp 65001 >nul
title Scenario 5 - Service Launcher
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run setup.bat first.
    pause
    exit /b 1
)
set "PY=.venv\Scripts\python.exe"

if "%~1"=="" goto menu
if /i "%~1"=="all"   goto all
if /i "%~1"=="agent" goto agent
if /i "%~1"=="api"   goto api
if /i "%~1"=="laya"  goto laya
if /i "%~1"=="sms"   goto sms
echo Unknown arg: %1
echo Usage: start.bat [all^|agent^|api^|laya^|sms]
pause & exit /b 1

:menu
echo ============================================================
echo   Scenario 5 - Service Launcher
echo ============================================================
echo   1. All        (Laya GPU + Task API)
echo   2. Agent      (interactive console)
echo   3. API        (port 8792)
echo   4. Laya GPU   (port 8791)
echo   5. SMS        (port 8099)
echo   0. Exit
echo ============================================================
choice /c 123450 /n /m "Choice: "
if errorlevel 6 exit /b 0
if errorlevel 5 goto sms
if errorlevel 4 goto laya
if errorlevel 3 goto api
if errorlevel 2 goto agent
goto all

:all
echo [1/2] Starting Laya GPU server (new window, port 8791)...
start "Laya GPU Server" cmd /k "%~dp0start.bat" laya
echo [2/2] Waiting for model load (about 20s)...
timeout /t 20 /nobreak >nul
echo Starting Task API (new window, port 8792)...
start "Task API" cmd /k "%~dp0start.bat" api
echo.
echo  Started. For interactive console run: start.bat agent
timeout /t 5 >nul
exit /b 0

:agent
%PY% runner.py
pause
exit /b 0

:api
%PY% api_server.py --port 8792
pause
exit /b 0

:laya
%PY% tools\start_laya_server.py --port 8791
pause
exit /b 0

:sms
%PY% services\sms_service.py --host 0.0.0.0 --port 8099
pause
exit /b 0
