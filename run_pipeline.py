"""
GeM Bid Pipeline — Orchestrator
=================================
Runs the full scraping + filtering + database import pipeline.

Usage:
    python run_pipeline.py
    python run_pipeline.py --headless       (default)
    python run_pipeline.py --no-headless    (visible browser)

Can also be called from Streamlit or a cron job.
"""

import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from config import (
    PROJECT_ROOT,
    LOG_DIR,
    SCRAPER_SCRIPT,
    FILTER_SCRIPT,
    FILTERED_CSV,
)
from database import init_db, import_from_csv

# ─── Logging Setup ────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """Configure pipeline logger with file + console output."""
    LOG_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"pipeline_{timestamp}.log"

    logger = logging.getLogger("gem_pipeline")
    logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers on repeated calls
    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    logger.info("Pipeline log: %s", log_file)
    return logger


# ─── Subprocess Runner ────────────────────────────────────────────────────────

def run_script(script_path: Path, logger: logging.Logger,
               extra_env: dict | None = None) -> bool:
    """
    Run a Python script as a subprocess.
    Returns True on success, False on failure.
    """
    import os

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    logger.info("Running: %s", script_path.name)
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,  # 1-hour timeout
        )

        # Log stdout (tail)
        if result.stdout:
            for line in result.stdout.strip().splitlines()[-20:]:
                logger.info("  [%s] %s", script_path.stem, line)

        if result.returncode != 0:
            logger.error(
                "%s exited with code %d", script_path.name, result.returncode
            )
            if result.stderr:
                for line in result.stderr.strip().splitlines()[-10:]:
                    logger.error("  [%s STDERR] %s", script_path.stem, line)
            return False

        logger.info("%s completed successfully.", script_path.name)
        return True

    except subprocess.TimeoutExpired:
        logger.error("%s timed out after 1 hour.", script_path.name)
        return False
    except Exception as exc:
        logger.exception("Failed to run %s: %s", script_path.name, exc)
        return False


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(headless: bool = True) -> bool:
    """
    Execute the full pipeline:
      1. Run scraper.py
      2. Run filter_bids.py
      3. Import filtered CSV into SQLite

    Returns True if all steps succeed.
    """
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("GeM Bid Pipeline — Starting")
    logger.info("=" * 60)

    t0 = time.time()
    success = True

    # Step 0: Ensure database exists
    init_db()

    # Step 1: Run scraper
    scraper_env = {"HEADLESS": "true" if headless else "false"}
    if not run_script(SCRAPER_SCRIPT, logger, extra_env=scraper_env):
        logger.error("Scraper failed — attempting to continue with existing CSV.")
        success = False

    # Step 2: Run filter
    if not run_script(FILTER_SCRIPT, logger):
        logger.error("Filter failed — attempting DB import with existing filtered CSV.")
        success = False

    # Step 3: Import filtered CSV into SQLite
    try:
        new_count = import_from_csv(FILTERED_CSV)
        logger.info("Database import: %d new bids added.", new_count)
    except Exception as exc:
        logger.exception("Database import failed: %s", exc)
        success = False

    elapsed = time.time() - t0
    status = "SUCCESS" if success else "PARTIAL FAILURE"
    logger.info("=" * 60)
    logger.info("Pipeline finished: %s  (%.1f seconds)", status, elapsed)
    logger.info("=" * 60)

    return success


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    headless = "--no-headless" not in sys.argv
    ok = run_pipeline(headless=headless)
    sys.exit(0 if ok else 1)
