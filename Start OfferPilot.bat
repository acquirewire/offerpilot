@echo off
title OfferPilot launcher
cd /d "%~dp0"

echo ============================================
echo   Starting OfferPilot...
echo   (keep this window open while you use it)
echo ============================================
echo.

REM start the tool (the engine) in its own window, no auto browser tab
start "OfferPilot engine" cmd /k ".venv\Scripts\python.exe -m streamlit run jobtracker\dashboard.py --server.headless true --server.port 8501"

echo Waiting for the tool to warm up...
timeout /t 12 /nobreak >nul

REM open your branded website (its "Start free" buttons go to the tool)
start "" "website\index.html"

echo.
echo OfferPilot is open in your browser. Click "Start free" on the page.
echo To shut down: close the "OfferPilot engine" window.
timeout /t 6 >nul
