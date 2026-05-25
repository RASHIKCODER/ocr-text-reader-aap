@echo off
:: ============================================================
::  OCR Vision System — Windows Start Script
::  Double-click karo ya Task Scheduler mein add karo
:: ============================================================

title OCR Vision System

cd /d "%~dp0"

echo ================================
echo   OCR Vision System Starting...
echo ================================

:: Install dependencies if needed
if not exist ".deps_installed" (
    echo Installing dependencies...
    pip install -r requirements.txt
    echo. > .deps_installed
)

:: Create folders
if not exist "data" mkdir data
if not exist "screenshots" mkdir screenshots

echo Starting OCR Vision...
echo Dashboard will be available at: http://localhost:5000
echo.

python main.py

pause
