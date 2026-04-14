@echo off
:: GeM Bid Pipeline — Scheduled Task Runner
:: ==========================================
:: Runs the scraper + filter + DB import pipeline,
:: then auto-commits and pushes results to GitHub.
:: Streamlit Cloud will auto-redeploy with fresh data.
::
:: Set up in Windows Task Scheduler to run every 12 hours.

set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo ============================================== >> logs\scheduler.log
echo [%date% %time%] Pipeline starting... >> logs\scheduler.log
echo ============================================== >> logs\scheduler.log

:: Step 1: Run the scraping + filtering pipeline
python run_pipeline.py --headless >> logs\scheduler.log 2>&1
set PIPELINE_EXIT=%ERRORLEVEL%
echo [%date% %time%] Pipeline finished (exit code: %PIPELINE_EXIT%) >> logs\scheduler.log

if %PIPELINE_EXIT% NEQ 0 (
    echo [%date% %time%] Pipeline failed — skipping git push. >> logs\scheduler.log
    goto :END
)

:: Step 2: Auto-commit and push updated CSV to GitHub
echo [%date% %time%] Pushing updated data to GitHub... >> logs\scheduler.log

git add gem_bids_filtered.csv filled_bids.json >> logs\scheduler.log 2>&1

:: Check if there are changes to commit
git diff --cached --quiet
if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] No changes to commit — data is up to date. >> logs\scheduler.log
    goto :END
)

:: Commit and push
git commit -m "Auto-update: scraped %date% %time%" >> logs\scheduler.log 2>&1
git push >> logs\scheduler.log 2>&1

if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] Successfully pushed to GitHub. Streamlit will redeploy. >> logs\scheduler.log
) else (
    echo [%date% %time%] Git push failed! Check credentials. >> logs\scheduler.log
)

:END
echo [%date% %time%] Done. >> logs\scheduler.log
echo. >> logs\scheduler.log
