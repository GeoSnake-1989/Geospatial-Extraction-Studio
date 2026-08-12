@echo off
setlocal
cd /d "%~dp0"

echo Starting Geospatial Extraction Studio...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"

if errorlevel 1 (
    echo.
    echo Geospatial Extraction Studio could not be started. Review the message above.
    pause
    exit /b 1
)

start "" "http://127.0.0.1:5173"
echo Geospatial Extraction Studio is opening in your browser.
timeout /t 3 /nobreak >nul
endlocal
