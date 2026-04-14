@echo off
:: GeM Bid Pipeline — Scheduled Task Runner
:: Runs the scraper + filter + DB import pipeline

set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo [%date% %time%] Pipeline starting... >> logs\scheduler.log
python run_pipeline.py --headless >> logs\scheduler.log 2>&1
echo [%date% %time%] Pipeline finished (exit code: %ERRORLEVEL%) >> logs\scheduler.log
echo. >> logs\scheduler.log
