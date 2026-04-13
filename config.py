"""
GeM Bid Pipeline — Configuration
=================================
Central configuration for all pipeline components.
Edit this file to change keywords, paths, or thresholds.
"""

from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT   = Path(__file__).parent.resolve()
DATABASE_PATH  = PROJECT_ROOT / "database.db"
LOG_DIR        = PROJECT_ROOT / "logs"
SCRAPER_SCRIPT = PROJECT_ROOT / "scraper.py"
FILTER_SCRIPT  = PROJECT_ROOT / "filter_bids.py"

# CSV files produced by the existing scraper + filter
RAW_CSV        = PROJECT_ROOT / "gem_bids_delhi.csv"
FILTERED_CSV   = PROJECT_ROOT / "gem_bids_filtered.csv"

# ─── Filter Keywords ─────────────────────────────────────────────────────────
# Bids whose title starts with (case-insensitive) any of these are kept.
# This list is used by filter_bids.py and also surfaced in the dashboard
# as multi-select filter options.

FILTER_KEYWORDS = [
    "Manpower Outsourcing Services - Fixed Remuneration",
    "Manpower Outsourcing Services - Man-days based",
    "Manpower Outsourcing Services - Minimum wage",
    "Hiring of Sanitation Service - Manpower Based Model",
    "Facility Management Service- Manpower based (Version 2)",
]

# ─── Dashboard Thresholds ────────────────────────────────────────────────────
# Bids scraped within this many hours are tagged as "New"
NEW_BID_HOURS = 24

# Bids whose deadline is within this many hours are flagged as "Expiring"
EXPIRING_HOURS = 48

# ─── Database Table ──────────────────────────────────────────────────────────
DB_TABLE = "bids"
