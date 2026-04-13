"""
Filter GeM Bids CSV
====================
Reads gem_bids_delhi.csv (all bids) and produces gem_bids_filtered.csv
containing only rows whose Title starts with one of the allowed prefixes.

Usage:
    python filter_bids.py
"""

import csv
from pathlib import Path

INPUT_CSV  = Path(__file__).parent / "gem_bids_delhi.csv"
OUTPUT_CSV = Path(__file__).parent / "gem_bids_filtered.csv"

# Titles use prefix matching (the % from the user means "starts with")
ALLOWED_PREFIXES = [
    "Manpower Outsourcing Services - Fixed Remuneration",
    "Manpower Outsourcing Services - Man-days based",
    "Manpower Outsourcing Services - Minimum wage",
    "Hiring of Sanitation Service - Manpower Based Model",
    "Facility Management Service- Manpower based (Version 2)",
]
ALLOWED_PREFIXES_LOWER = [p.lower() for p in ALLOWED_PREFIXES]


def is_title_allowed(title: str) -> bool:
    """Return True if the title starts with any of the allowed prefixes."""
    t = title.strip().lower()
    return any(t.startswith(prefix) for prefix in ALLOWED_PREFIXES_LOWER)


def main():
    if not INPUT_CSV.exists():
        print(f"ERROR: Input file not found: {INPUT_CSV}")
        print("Run scraper.py first to generate the all-bids CSV.")
        return

    with open(INPUT_CSV, encoding="utf-8", newline="") as f_in:
        reader = csv.DictReader(f_in)
        headers = reader.fieldnames

        rows_total = 0
        rows_kept = 0

        with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f_out:
            writer = csv.DictWriter(f_out, fieldnames=headers)
            writer.writeheader()

            for row in reader:
                rows_total += 1
                if is_title_allowed(row.get("Title", "")):
                    writer.writerow(row)
                    rows_kept += 1

    print(f"\nDone!")
    print(f"  Input  : {INPUT_CSV}  ({rows_total} rows)")
    print(f"  Output : {OUTPUT_CSV}  ({rows_kept} rows kept)")
    print(f"  Filtered out: {rows_total - rows_kept} rows")


if __name__ == "__main__":
    main()
