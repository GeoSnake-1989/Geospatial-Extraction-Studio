@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"

if errorlevel 1 (
    echo.
    echo Geospatial Extraction Studio could not be stopped. Review the message above.
    pause
    exit /b 1
)

timeout /t 2 /nobreak >nul
endlocal
