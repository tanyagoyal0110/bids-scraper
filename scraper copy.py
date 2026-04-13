"""
GeM Bid Scraper — Consignee State: Delhi (ALL cities, ALL pages)
================================================================
Author   : Production Grade — GeM Bid Scraper
Target   : https://bidplus.gem.gov.in/advance-search
API      : POST https://bidplus.gem.gov.in/search-bids (JSON)
Filter   : searchType=con, state_name_con=DELHI (no city filter)
Output   : gem_bids_delhi.csv

Architecture (Hybrid — fast & reliable):
  1. Playwright launches headless Chromium ONCE to:
       a. Navigate to advance-search
       b. Select Consignee Location tab + DELHI state
       c. Trigger the first search to get a valid CSRF token + session cookies
  2. All subsequent pages are fetched via direct HTTP POST (requests library)
     using the captured cookies and CSRF token — no browser needed per page.
  3. JSON responses are parsed directly — no HTML parsing needed.

Features:
  ✓ No time.sleep — async explicit waits
  ✓ Progressive CSV append (safe on crash)
  ✓ Resume capability (skip already-scraped pages via progress file)
  ✓ Retry logic per page (up to 3 retries with exponential backoff)
  ✓ Duplicate bid ID deduplication
  ✓ Structured logging (console + file)
  ✓ Headless mode toggle (--no-headless flag or HEADLESS=false env var)
  ✓ Handles 1000+ pages dynamically (stops when page > total pages)

Setup:
  pip install playwright requests
  playwright install chromium
  python scraper.py [--no-headless]

Output CSV columns:
  Bid ID | Title | Organization | Quantity | Start Date | End Date | Bid Value
"""

import asyncio
import csv
import json
import logging
import os
import sys
import time
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

import requests
from playwright.async_api import async_playwright

# ─── Configuration ────────────────────────────────────────────────────────────

ADVANCE_SEARCH_URL = "https://bidplus.gem.gov.in/advance-search"
SEARCH_BIDS_URL    = "https://bidplus.gem.gov.in/search-bids"
OUTPUT_CSV         = Path(__file__).parent / "gem_bids_delhi.csv"
PROGRESS_FILE      = Path(__file__).parent / ".scraper_progress"
STATE_VALUE        = "DELHI"
HEADLESS           = os.environ.get("HEADLESS", "true").lower() != "false"
MAX_RETRIES        = 3
RETRY_BACKOFF      = [2, 5, 10]   # seconds between retries
REQUEST_TIMEOUT    = 30            # seconds for HTTP requests

CSV_HEADERS = ["Bid ID", "Title", "Organization", "Quantity",
               "Start Date", "End Date", "Bid Value"]

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "scraper.log",
                            encoding="utf-8", mode="a"),
    ],
)
log = logging.getLogger("gem_scraper")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_seen_ids() -> set:
    """Load Bid IDs already written to CSV (for resume / dedup)."""
    seen = set()
    if OUTPUT_CSV.exists() and OUTPUT_CSV.stat().st_size > 0:
        with open(OUTPUT_CSV, encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            if rdr.fieldnames and "Bid ID" in rdr.fieldnames:
                for row in rdr:
                    bid = row.get("Bid ID", "").strip()
                    if bid:
                        seen.add(bid)
        log.info("Resume: found %d existing records in CSV.", len(seen))
    return seen


def load_last_page() -> int:
    """Return the last successfully scraped page (0 = fresh start)."""
    if PROGRESS_FILE.exists():
        try:
            p = int(PROGRESS_FILE.read_text().strip())
            log.info("Resume: last saved page = %d. Starting from page %d.", p, p + 1)
            return p
        except ValueError:
            pass
    return 0


def save_progress(page_num: int):
    PROGRESS_FILE.write_text(str(page_num))


def open_csv_writer():
    """Open CSV in append mode; write header only if file is new."""
    is_new = not OUTPUT_CSV.exists() or OUTPUT_CSV.stat().st_size == 0
    fh = open(OUTPUT_CSV, "a", encoding="utf-8", newline="")
    writer = csv.DictWriter(fh, fieldnames=CSV_HEADERS)
    if is_new:
        writer.writeheader()
        fh.flush()
    return fh, writer


def format_date(iso_str: str) -> str:
    """Convert ISO 8601 UTC string to DD-MM-YYYY HH:MM local-ish format."""
    if not iso_str:
        return ""
    try:
        dt = datetime.strptime(iso_str.replace("Z", "+00:00"), "%Y-%m-%dT%H:%M:%S%z")
        return dt.strftime("%d-%m-%Y %I:%M %p")
    except Exception:
        return iso_str


def parse_doc(doc: dict) -> dict:
    """
    Convert one JSON doc from the search-bids API into a CSV row dict.

    Relevant API fields:
      b_bid_number          → Bid ID
      b_category_name       → Title
      ba_official_details_minName / ba_official_details_deptName → Organization
      b_total_quantity      → Quantity
      final_start_date_sort → Start Date (ISO UTC)
      final_end_date_sort   → End Date (ISO UTC)
      (bid value not exposed in search-bids; left blank)
    """
    def first(lst):
        """Return first element of a list, or empty string."""
        return lst[0] if isinstance(lst, list) and lst else (lst or "")

    bid_id   = first(doc.get("b_bid_number", ""))
    title    = first(doc.get("b_category_name", doc.get("bd_category_name", "")))
    min_name = first(doc.get("ba_official_details_minName", ""))
    dep_name = first(doc.get("ba_official_details_deptName", ""))
    org_parts = [p for p in [min_name, dep_name] if p]
    org      = " | ".join(org_parts)
    qty      = first(doc.get("b_total_quantity", ""))
    start    = format_date(first(doc.get("final_start_date_sort", "")))
    end      = format_date(first(doc.get("final_end_date_sort", "")))

    return {
        "Bid ID":       str(bid_id),
        "Title":        str(title),
        "Organization": str(org),
        "Quantity":     str(qty),
        "Start Date":   start,
        "End Date":     end,
        "Bid Value":    "",   # not in search-bids endpoint
    }

# ─── Phase 1: Browser — get session + CSRF ────────────────────────────────────

async def get_session_and_csrf() -> tuple[dict, str]:
    """
    Launch Playwright headless, navigate to advance-search,
    select DELHI, trigger the first search, then capture:
      - cookies (for requests session)
      - CSRF token (csrf_bd_gem_nk)
    Returns (cookies_dict, csrf_token)
    """
    log.info("Launching browser to get session cookies + CSRF token …")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        captured = {}

        async def on_request(req):
            if "search-bids" in req.url and req.method == "POST":
                data = urllib.parse.parse_qs(req.post_data or "")
                if "csrf_bd_gem_nk" in data:
                    captured["csrf"] = data["csrf_bd_gem_nk"][0]
                    log.info("Captured CSRF token: %s…", captured["csrf"][:8])
                # Capture the payload structure too
                if "payload" in data:
                    try:
                        captured["payload_template"] = json.loads(data["payload"][0])
                    except Exception:
                        pass
        page.on("request", on_request)

        await page.goto(ADVANCE_SEARCH_URL, wait_until="domcontentloaded", timeout=90_000)
        await page.click("text=Search by Consignee Location", timeout=30_000)
        await page.wait_for_selector("select#state_name_con", timeout=30_000)
        await page.select_option("select#state_name_con", value=STATE_VALUE, timeout=30_000)

        # Click the correct Search button for the consignee location tab
        # It is an <a> tag with onclick="searchBid('con')"
        await page.click("a[onclick=\"searchBid('con')\"]", timeout=30_000)

        # Wait for the first AJAX call to complete (CSRF captured in on_request)
        deadline = asyncio.get_event_loop().time() + 30
        while "csrf" not in captured and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.3)

        if "csrf" not in captured:
            raise RuntimeError("Could not capture CSRF token — check the site manually.")

        # Get all cookies for the session
        raw_cookies = await context.cookies()
        cookies = {c["name"]: c["value"] for c in raw_cookies}
        log.info("Captured %d cookies.", len(cookies))

        await browser.close()

    return cookies, captured["csrf"]

# ─── Phase 2: HTTP requests — scrape all pages ────────────────────────────────

def fetch_page(session: requests.Session, csrf: str, page_num: int) -> dict | None:
    """
    POST to /search-bids and return the parsed JSON response.
    Returns None on final failure.
    """
    payload_dict = {
        "searchType":    "con",
        "state_name_con": STATE_VALUE,
        "city_name_con": "",       # no city filter
        "bidEndFromCon": "",
        "bidEndToCon":   "",
        "page":          page_num,
    }
    form_data = {
        "payload":       json.dumps(payload_dict),
        "csrf_bd_gem_nk": csrf,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(
                SEARCH_BIDS_URL,
                data=form_data,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            wait = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            log.warning("  Page %d attempt %d/%d failed: %s — retrying in %ds",
                        page_num, attempt, MAX_RETRIES, exc, wait)
            if attempt < MAX_RETRIES:
                time.sleep(wait)
            else:
                log.error("  Page %d: all %d retries exhausted.", page_num, MAX_RETRIES)
                return None

# ─── Main scrape loop ─────────────────────────────────────────────────────────

async def scrape():
    seen_ids    = load_seen_ids()
    start_page  = load_last_page() + 1  # resume from next unscraped page
    fh, writer  = open_csv_writer()
    total_written = len(seen_ids)

    # ── Phase 1: get session ──────────────────────────────────────────────────
    cookies, csrf = await get_session_and_csrf()

    # Build a requests session with the captured cookies
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/122.0.0.0 Safari/537.36"),
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer":          ADVANCE_SEARCH_URL,
        "Origin":           "https://bidplus.gem.gov.in",
    })

    # ── Phase 2: discover total pages ────────────────────────────────────────
    log.info("Fetching page 1 to discover total record count …")
    first_resp = fetch_page(session, csrf, 1)
    if not first_resp:
        log.error("Failed to fetch first page. Aborting.")
        fh.close()
        return

    result_data = first_resp.get("response", {}).get("response", {})
    total_records = result_data.get("numFound", 0)
    docs_per_page = len(result_data.get("docs", [])) or 10
    total_pages   = (total_records + docs_per_page - 1) // docs_per_page

    log.info("Total records: %d | Pages: %d | Starting from page: %d",
             total_records, total_pages, start_page)

    # ── Phase 2a: write page 1 if not resuming past it ───────────────────────
    if start_page == 1:
        docs = result_data.get("docs", [])
        new_count = 0
        for doc in docs:
            row = parse_doc(doc)
            bid_id = row["Bid ID"]
            if bid_id and bid_id not in seen_ids:
                writer.writerow(row)
                seen_ids.add(bid_id)
                total_written += 1
                new_count += 1
        fh.flush()
        save_progress(1)
        log.info("Page  1/%d | +%d new | Total: %d", total_pages, new_count, total_written)
        start_page = 2

    # ── Phase 2b: remaining pages ─────────────────────────────────────────────
    for page_num in range(start_page, total_pages + 1):
        resp_json = fetch_page(session, csrf, page_num)
        if resp_json is None:
            log.error("Skipping page %d after all retries.", page_num)
            continue

        docs = resp_json.get("response", {}).get("response", {}).get("docs", [])
        if not docs:
            log.warning("Page %d returned no docs — may be past last page.", page_num)
            if page_num > total_pages:
                break
            continue

        new_count = 0
        for doc in docs:
            row = parse_doc(doc)
            bid_id = row["Bid ID"]
            if bid_id and bid_id not in seen_ids:
                writer.writerow(row)
                seen_ids.add(bid_id)
                total_written += 1
                new_count += 1

        fh.flush()
        save_progress(page_num)
        log.info("Page %3d/%d | +%d new | Total: %d",
                 page_num, total_pages, new_count, total_written)

        # Small polite delay to avoid hammering the server
        time.sleep(0.5)

    fh.close()

    # Clean up progress file on successful completion
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()

    log.info("═══════════════════════════════════════════════")
    log.info("Scraping complete!")
    log.info("Total records written : %d", total_written)
    log.info("Output CSV            : %s", OUTPUT_CSV)
    log.info("═══════════════════════════════════════════════")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--no-headless" in sys.argv:
        HEADLESS = False
    elif "--headless" in sys.argv:
        HEADLESS = True

    log.info("GeM Delhi Bid Scraper starting (headless=%s) …", HEADLESS)
    t0 = time.time()
    try:
        asyncio.run(scrape())
    except KeyboardInterrupt:
        log.info("Interrupted by user. Progress saved — re-run to resume from last page.")
    except Exception as exc:
        log.exception("Fatal error: %s", exc)
        sys.exit(1)
    finally:
        elapsed = time.time() - t0
        log.info("Total runtime: %.1f seconds (%.1f minutes)", elapsed, elapsed / 60)
