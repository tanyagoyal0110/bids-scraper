"""
GeM Bid Pipeline — Database Layer
===================================
SQLite helper for persistent bid storage, tracking, and querying.

On Streamlit Cloud the filesystem is ephemeral, so the SQLite DB is rebuilt
from gem_bids_filtered.csv on every boot.  The "is_filled" state is stored
in filled_bids.json (committed to the repo) so it survives reboots.
"""

import csv
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from config import DATABASE_PATH, DB_TABLE, NEW_BID_HOURS, PROJECT_ROOT

log = logging.getLogger("gem_database")

# Path to the JSON file that persists "filled" state across reboots
FILLED_JSON = PROJECT_ROOT / "filled_bids.json"

# ─── Schema ───────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {DB_TABLE} (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    bid_id        TEXT    UNIQUE NOT NULL,
    title         TEXT,
    organization  TEXT,
    quantity      TEXT,
    start_date    TEXT,
    end_date      TEXT,
    bid_value     TEXT,
    scraped_at    TEXT    DEFAULT (datetime('now', 'localtime')),
    is_filled     INTEGER DEFAULT 0
);
"""

CREATE_INDEX_SQL = f"""
CREATE INDEX IF NOT EXISTS idx_bid_id ON {DB_TABLE}(bid_id);
"""


# ─── Connection Helper ────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database."""
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ─── Init ─────────────────────────────────────────────────────────────────────

def init_db():
    """Create the bids table and indexes if they don't already exist."""
    conn = get_connection()
    try:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_INDEX_SQL)
        conn.commit()
        log.info("Database initialised: %s", DATABASE_PATH)
    finally:
        conn.close()


# ─── Filled-State JSON Helpers ────────────────────────────────────────────────

def load_filled_state() -> dict[str, bool]:
    """Load the filled-bid tracking state from JSON file.
    Returns a dict of {bid_id: True} for filled bids.
    """
    if not FILLED_JSON.exists():
        return {}
    try:
        with open(FILLED_JSON, encoding="utf-8") as f:
            data = json.load(f)
        return {k: bool(v) for k, v in data.items()}
    except (json.JSONDecodeError, IOError):
        log.warning("Could not read %s — starting with empty filled state.", FILLED_JSON)
        return {}


def save_filled_state(filled: dict[str, bool]):
    """Persist the filled-bid state to JSON file.
    Only saves bids that are True (filled) to keep the file small.
    """
    # Only store filled=True entries
    to_save = {bid_id: True for bid_id, val in filled.items() if val}
    with open(FILLED_JSON, "w", encoding="utf-8") as f:
        json.dump(to_save, f, indent=2, sort_keys=True)
    log.info("Saved filled state: %d bids marked as filled.", len(to_save))


def apply_filled_state_to_db():
    """Read filled_bids.json and apply the is_filled flags to the SQLite DB.
    Called after CSV import to overlay the persisted state.
    """
    filled = load_filled_state()
    if not filled:
        return

    conn = get_connection()
    try:
        for bid_id, is_filled in filled.items():
            conn.execute(
                f"UPDATE {DB_TABLE} SET is_filled = ? WHERE bid_id = ?",
                (1 if is_filled else 0, bid_id),
            )
        conn.commit()
        log.info("Applied filled state to DB: %d bids.", len(filled))
    finally:
        conn.close()


# ─── Upsert Bids ─────────────────────────────────────────────────────────────

def upsert_bids(rows: list[dict]) -> int:
    """
    Insert bids into the database, skipping duplicates (by bid_id).
    Returns the number of newly inserted rows.
    """
    if not rows:
        return 0

    sql = f"""
    INSERT OR IGNORE INTO {DB_TABLE}
        (bid_id, title, organization, quantity, start_date, end_date, bid_value, scraped_at)
    VALUES
        (:bid_id, :title, :organization, :quantity, :start_date, :end_date, :bid_value, :scraped_at)
    """

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    inserted = 0
    try:
        for row in rows:
            params = {
                "bid_id":       row.get("Bid ID", "").strip(),
                "title":        row.get("Title", "").strip(),
                "organization": row.get("Organization", "").strip(),
                "quantity":     row.get("Quantity", "").strip(),
                "start_date":   row.get("Start Date", "").strip(),
                "end_date":     row.get("End Date", "").strip(),
                "bid_value":    row.get("Bid Value", "").strip(),
                "scraped_at":   now,
            }
            if not params["bid_id"]:
                continue
            cursor = conn.execute(sql, params)
            if cursor.rowcount > 0:
                inserted += 1
        conn.commit()
        log.info("Upserted %d new bids (total rows sent: %d)", inserted, len(rows))
    finally:
        conn.close()

    return inserted


# ─── Import from CSV ──────────────────────────────────────────────────────────

def import_from_csv(csv_path: Path) -> int:
    """
    Read a filtered CSV and upsert all rows into SQLite.
    Returns the number of newly inserted rows.
    """
    if not csv_path.exists():
        log.warning("CSV not found for import: %s", csv_path)
        return 0

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    log.info("Importing %d rows from %s", len(rows), csv_path.name)
    return upsert_bids(rows)


def rebuild_db_from_csv(csv_path: Path) -> int:
    """
    Full rebuild: drop and re-import all bids from CSV, then apply
    filled state from JSON.  Used on Streamlit Cloud where the DB
    is ephemeral and needs to be rebuilt on every boot.
    Returns the number of rows imported.
    """
    # Re-init schema (creates table if missing)
    init_db()

    # Import all bids from CSV
    count = import_from_csv(csv_path)

    # Overlay the filled state from JSON
    apply_filled_state_to_db()

    log.info("DB rebuild complete: %d bids imported, filled state applied.", count)
    return count


# ─── Query: All Bids ─────────────────────────────────────────────────────────

def get_all_bids() -> pd.DataFrame:
    """Fetch all bids as a pandas DataFrame."""
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            f"SELECT * FROM {DB_TABLE} ORDER BY scraped_at DESC, id DESC",
            conn,
        )
    finally:
        conn.close()
    return df


# ─── Update: Filled Status ───────────────────────────────────────────────────

def update_filled(bid_id: str, is_filled: bool):
    """Toggle the is_filled flag for a given bid."""
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE {DB_TABLE} SET is_filled = ? WHERE bid_id = ?",
            (1 if is_filled else 0, bid_id),
        )
        conn.commit()
    finally:
        conn.close()


def batch_update_filled(updates: dict[str, bool]):
    """Batch-update filled status in both SQLite and the JSON file.
    updates = {bid_id: is_filled, ...}
    """
    if not updates:
        return

    # Update SQLite
    conn = get_connection()
    try:
        for bid_id, filled in updates.items():
            conn.execute(
                f"UPDATE {DB_TABLE} SET is_filled = ? WHERE bid_id = ?",
                (1 if filled else 0, bid_id),
            )
        conn.commit()
    finally:
        conn.close()

    # Persist to JSON (merge with existing state)
    current = load_filled_state()
    current.update(updates)
    save_filled_state(current)


# ─── Stats ────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    """
    Return summary statistics:
      total, filled, new_today
    """
    conn = get_connection()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM {DB_TABLE}").fetchone()[0]
        filled = conn.execute(
            f"SELECT COUNT(*) FROM {DB_TABLE} WHERE is_filled = 1"
        ).fetchone()[0]

        cutoff = (datetime.now() - timedelta(hours=NEW_BID_HOURS)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        new_today = conn.execute(
            f"SELECT COUNT(*) FROM {DB_TABLE} WHERE scraped_at >= ?",
            (cutoff,),
        ).fetchone()[0]
    finally:
        conn.close()

    return {"total": total, "filled": filled, "new_today": new_today}
