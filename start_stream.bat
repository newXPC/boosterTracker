@echo off
title Booster Tracker
cd /d "%~dp0"

echo ============================================
echo  BOOSTER TRACKER - Stream-Start
echo ============================================
echo.
echo [1/2] Resette Tracker-Seiten (Zaehler, Listen, Gesamtwert)...
python -c "import sys; sys.path.insert(0, '.'); import stream_monitor_v4 as m; m.update_html([], {'ex': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'SAR': 0}, 1, '', 0.0); m.update_html_all([])"
if errorlevel 1 (
    echo FEHLER beim Reset! Ist Python installiert?
    pause
    exit /b 1
)
echo       Reset OK.
echo.
echo [2/2] Starte Scanner + Webserver...
echo       Tracker:  http://localhost:8765/booster-tracker.html
echo       Alle:     http://localhost:8765/booster-tracker-alle.html
echo       Alert:    http://localhost:8765/alert.html
echo       Rahmen:   http://localhost:8765/frame.html
echo.
python stream_monitor_v4.py

echo.
echo Scanner beendet.
pause
