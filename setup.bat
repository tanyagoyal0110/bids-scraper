@echo off
title GeM Bid Scraper - Setup
echo =========================================================
echo           GeM Bid Scraper - One-Time Setup
echo =========================================================
echo.

:: ── Check if Python is installed ──────────────────────────
echo [1/3] Checking for Python...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ERROR: Python is not installed or not in PATH.
    echo  Download it from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
python --version
echo       OK
echo.

:: ── Install Python packages ──────────────────────────────
echo [2/3] Installing Python packages...
pip install -r "%~dp0requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ERROR: pip install failed. Check the output above.
    pause
    exit /b 1
)
echo       OK
echo.

:: ── Install Playwright browsers ──────────────────────────
echo [3/3] Installing Playwright Chromium browser...
python -m playwright install chromium
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  ERROR: Playwright browser install failed.
    pause
    exit /b 1
)
echo       OK
echo.

echo =========================================================
echo   Setup complete! You can now run the scraper:
echo.
echo     python scraper.py           (scrape all bids)
echo     python filter_bids.py       (filter to selected titles)
echo =========================================================
echo.
pause
