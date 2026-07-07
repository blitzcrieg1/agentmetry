@echo off
rem BLACKBOX mobile / LAN access — build dashboard once, bind 0.0.0.0:8000.
rem Open the printed http://<your-lan-ip>:8000 URL on your phone (same Wi-Fi).

echo Building dashboard for same-origin LAN access...
cd /d "%~dp0..\apps\dashboard"
set NEXT_PUBLIC_SAME_ORIGIN=true
call npm run build
if errorlevel 1 (
    echo Dashboard build failed.
    exit /b 1
)

echo.
echo Detecting LAN address...
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set _IP=%%a
    goto :found_ip
)
:found_ip
set _IP=%_IP: =%
if defined _IP (
    echo.
    echo  Phone URL:  http://%_IP%:8000
    echo  ^(Same Wi-Fi as this PC. Allow port 8000 in Windows Firewall if needed.^)
    echo.
) else (
    echo Run ipconfig and open http://YOUR-PC-IP:8000 on your phone.
)

echo Starting BLACKBOX on all interfaces :8000 ...
cd /d "%~dp0..\apps\orchestrator"
.venv\Scripts\uvicorn api.main:app --host 0.0.0.0 --port 8000
