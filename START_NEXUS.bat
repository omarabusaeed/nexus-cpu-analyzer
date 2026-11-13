@echo off
title NEXUS Real-Time CPU Analyzer Pro
color 0B
cls
echo.
echo  ================================================================
echo    NEXUS PRO - Real-Time High-Speed CPU Telemetry Dashboard
echo  ================================================================
echo.
echo   [*] Starting High-Performance Telemetry Engine...
echo   [*] Local Dashboard URL:  http://localhost:8050
echo   [*] Press Ctrl+C in this terminal window to stop the server.
echo.

cd /d "%~dp0"
python app.py

echo.
echo  [!] Server stopped.
pause
