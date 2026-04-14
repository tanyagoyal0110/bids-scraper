"""
GeM Bid Dashboard — Streamlit App
====================================
Interactive dashboard for browsing, filtering, tracking, and managing
GeM bids stored in the SQLite database.

Data flow (Streamlit Community Cloud):
  1. GitHub Actions scrapes bids on a cron schedule
  2. The filtered CSV is auto-committed to the repo
  3. Streamlit Cloud auto-redeploys, picking up the new CSV
  4. This app rebuilds the in-memory SQLite DB from the CSV on boot
  5. "Filled" state is persisted in filled_bids.json (committed to repo)

Run:
    streamlit run app.py
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from config import (
    PROJECT_ROOT,
    FILTER_KEYWORDS,
    NEW_BID_HOURS,
    EXPIRING_HOURS,
    FILTERED_CSV,
)
from database import (
    rebuild_db_from_csv,
    get_all_bids,
    batch_update_filled,
    get_stats,
)

# ─── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="GeM Bid Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* ── Import Google Font ─────────────────────────────────── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* ── Global ─────────────────────────────────────────────── */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* ── Header ─────────────────────────────────────────────── */
    .main-header {
        background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
        padding: 1.8rem 2rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
        border: 1px solid rgba(255,255,255,0.08);
    }
    .main-header h1 {
        color: #ffffff;
        font-size: 1.9rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.5px;
    }
    .main-header p {
        color: rgba(255,255,255,0.6);
        font-size: 0.95rem;
        margin: 0.3rem 0 0 0;
    }
    .update-badge {
        display: inline-block;
        background: rgba(52, 211, 153, 0.15);
        color: #34d399;
        border: 1px solid rgba(52, 211, 153, 0.3);
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        margin-top: 0.4rem;
    }

    /* ── Stat Cards ─────────────────────────────────────────── */
    .stat-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        padding: 1.3rem 1.5rem;
        text-align: center;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .stat-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.3);
    }
    .stat-number {
        font-size: 2.2rem;
        font-weight: 700;
        margin: 0;
        line-height: 1.2;
    }
    .stat-label {
        font-size: 0.82rem;
        color: rgba(255,255,255,0.55);
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 0.3rem;
    }
    .stat-total .stat-number { color: #60a5fa; }
    .stat-filled .stat-number { color: #34d399; }
    .stat-new .stat-number { color: #fbbf24; }
    .stat-expiring .stat-number { color: #f87171; }

    /* ── Badges ─────────────────────────────────────────────── */
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }
    .badge-new {
        background: rgba(251, 191, 36, 0.15);
        color: #fbbf24;
        border: 1px solid rgba(251, 191, 36, 0.3);
    }
    .badge-expiring {
        background: rgba(248, 113, 113, 0.15);
        color: #f87171;
        border: 1px solid rgba(248, 113, 113, 0.3);
        animation: pulse-red 2s ease-in-out infinite;
    }
    .badge-filled {
        background: rgba(52, 211, 153, 0.15);
        color: #34d399;
        border: 1px solid rgba(52, 211, 153, 0.3);
    }

    @keyframes pulse-red {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }

    /* ── Table Rows ─────────────────────────────────────────── */
    .row-filled {
        opacity: 0.5;
        text-decoration: line-through;
    }
    .row-expiring {
        border-left: 3px solid #f87171;
    }

    /* ── Sidebar ────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f0c29 0%, #1a1a2e 100%);
    }
    [data-testid="stSidebar"] .stMarkdown h2 {
        color: #60a5fa;
        font-size: 1rem;
        text-transform: uppercase;
        letter-spacing: 1.5px;
    }

    /* ── Buttons ────────────────────────────────────────────── */
    .stButton > button {
        border-radius: 10px;
        font-weight: 600;
        letter-spacing: 0.3px;
        transition: all 0.2s ease;
    }

    /* ── Pipeline status ────────────────────────────────────── */
    .pipeline-running {
        background: rgba(251, 191, 36, 0.1);
        border: 1px solid rgba(251, 191, 36, 0.3);
        border-radius: 10px;
        padding: 0.8rem 1rem;
        color: #fbbf24;
        font-size: 0.85rem;
    }

    /* ── Analytics ───────────────────────────────────────────── */
    .analytics-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 12px;
        padding: 1rem 1.3rem;
    }

    /* ── Hide Streamlit branding ─────────────────────────────── */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ─── Initialize DB from CSV ──────────────────────────────────────────────────
# On Streamlit Cloud the SQLite DB is ephemeral.  We rebuild it from the
# committed CSV every time the app boots, then overlay filled state from JSON.

if FILTERED_CSV.exists():
    rebuild_db_from_csv(FILTERED_CSV)


# ─── Helper Functions ─────────────────────────────────────────────────────────

def parse_date(date_str: str) -> datetime | None:
    """Parse date strings in DD-MM-YYYY HH:MM AM/PM format."""
    if not date_str or pd.isna(date_str):
        return None
    for fmt in ("%d-%m-%Y %I:%M %p", "%d-%m-%Y %H:%M", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(date_str).strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None


def is_expiring(end_date_str: str) -> bool:
    """Check if a bid's end date is within the EXPIRING_HOURS threshold."""
    dt = parse_date(end_date_str)
    if dt is None:
        return False
    now = datetime.now()
    return now < dt <= now + timedelta(hours=EXPIRING_HOURS)


def is_new_bid(scraped_at_str: str) -> bool:
    """Check if a bid was scraped within the NEW_BID_HOURS window."""
    if not scraped_at_str or pd.isna(scraped_at_str):
        return False
    try:
        dt = datetime.strptime(str(scraped_at_str).strip(), "%Y-%m-%d %H:%M:%S")
        return dt >= datetime.now() - timedelta(hours=NEW_BID_HOURS)
    except (ValueError, TypeError):
        return False


def get_category(title: str) -> str:
    """Extract the main category from a bid title."""
    if not title or pd.isna(title):
        return "Other"
    t = str(title).strip()
    for kw in FILTER_KEYWORDS:
        if t.lower().startswith(kw.lower()):
            return kw.split(" - ")[0].strip() if " - " in kw else kw
    return "Other"


def get_csv_last_modified() -> str:
    """Get the last-modified timestamp of the filtered CSV file."""
    if FILTERED_CSV.exists():
        mtime = FILTERED_CSV.stat().st_mtime
        dt = datetime.fromtimestamp(mtime)
        return dt.strftime("%d %b %Y, %I:%M %p")
    return "Unknown"


# ─── Header ───────────────────────────────────────────────────────────────────

last_updated = get_csv_last_modified()
st.markdown(f"""
<div class="main-header">
    <h1>📊 GeM Bid Tracker</h1>
    <p>Government e-Marketplace — Delhi Bid Monitoring Dashboard</p>
    <div class="update-badge">🔄 Data last updated: {last_updated}</div>
</div>
""", unsafe_allow_html=True)


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🎛️ Controls")

    # Refresh Data button
    if st.button("🔄 Refresh Data", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    # ── Filters ───────────────────────────────────────────────
    st.markdown("## 🔍 Filters")

    # Search bar
    search_query = st.text_input(
        "Search by title",
        placeholder="e.g. manpower, staffing...",
        key="search_input",
    )

    # Keyword filter
    keyword_filter = st.multiselect(
        "Category filter",
        options=FILTER_KEYWORDS,
        default=[],
        key="keyword_filter",
    )

    # Status filter
    status_filter = st.selectbox(
        "Status",
        options=["All", "Unfilled only", "Filled only", "Expiring soon", "New bids"],
        key="status_filter",
    )

    # Date filter
    st.markdown("**End Date range**")
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        date_from = st.date_input("From", value=None, key="date_from")
    with col_d2:
        date_to = st.date_input("To", value=None, key="date_to")

    st.divider()

    # ── Stats ─────────────────────────────────────────────────
    st.markdown("## 📈 Quick Stats")
    stats = get_stats()

    st.divider()

    # ── Info ──────────────────────────────────────────────────
    st.markdown("## ℹ️ Auto-Updates")
    st.caption(
        "Data is automatically refreshed every 12 hours via "
        "GitHub Actions. The app redeploys with fresh data "
        "after each scrape."
    )


# ─── Stat Cards Row ──────────────────────────────────────────────────────────

# Load data
df = get_all_bids()

# Count expiring
expiring_count = 0
if not df.empty and "end_date" in df.columns:
    expiring_count = df["end_date"].apply(is_expiring).sum()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="stat-card stat-total">
        <div class="stat-number">{stats['total']}</div>
        <div class="stat-label">Total Bids</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="stat-card stat-filled">
        <div class="stat-number">{stats['filled']}</div>
        <div class="stat-label">Filled</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="stat-card stat-new">
        <div class="stat-number">{stats['new_today']}</div>
        <div class="stat-label">New Today</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="stat-card stat-expiring">
        <div class="stat-number">{expiring_count}</div>
        <div class="stat-label">Expiring Soon</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("")


# ─── Apply Filters ───────────────────────────────────────────────────────────

if df.empty:
    st.info(
        "No bids in database yet. Data is automatically scraped every 12 hours "
        "via GitHub Actions. If this is the first deployment, the next scheduled "
        "run will populate the data."
    )
    st.stop()

# Title search
if search_query:
    df = df[df["title"].str.contains(search_query, case=False, na=False)]

# Keyword / category filter
if keyword_filter:
    mask = pd.Series(False, index=df.index)
    for kw in keyword_filter:
        mask |= df["title"].str.lower().str.startswith(kw.lower(), na=False)
    df = df[mask]

# Status filter
if status_filter == "Unfilled only":
    df = df[df["is_filled"] == 0]
elif status_filter == "Filled only":
    df = df[df["is_filled"] == 1]
elif status_filter == "Expiring soon":
    df = df[df["end_date"].apply(is_expiring)]
elif status_filter == "New bids":
    df = df[df["scraped_at"].apply(is_new_bid)]

# Date range filter
if date_from or date_to:
    parsed_dates = df["end_date"].apply(parse_date)
    if date_from:
        from_dt = datetime.combine(date_from, datetime.min.time())
        df = df[parsed_dates.apply(lambda d: d is not None and d >= from_dt)]
        # Recompute after filter
        parsed_dates = df["end_date"].apply(parse_date)
    if date_to:
        to_dt = datetime.combine(date_to, datetime.max.time())
        df = df[parsed_dates.apply(lambda d: d is not None and d <= to_dt)]


# ─── Results Header ──────────────────────────────────────────────────────────

st.markdown(f"**Showing {len(df)} bids**")


# ─── Bid Table with Checkboxes ───────────────────────────────────────────────

if df.empty:
    st.warning("No bids match the current filters.")
    st.stop()

# Build display table
updates = {}

# Column configuration for data_editor
display_df = df[["is_filled", "bid_id", "title", "organization", "quantity",
                 "start_date", "end_date", "bid_value", "scraped_at" ]].copy()

# Add status badges as a column
def make_status(row):
    badges = []
    if is_new_bid(row.get("scraped_at", "")):
        badges.append("🆕 New")
    if is_expiring(row.get("end_date", "")):
        badges.append("⏰ Expiring")
    if row.get("is_filled") == 1:
        badges.append("✅ Filled")
    return " | ".join(badges) if badges else "—"

display_df.insert(0, "status", df.apply(make_status, axis=1))
display_df["is_filled"] = display_df["is_filled"].astype(bool)

# Rename columns for display
display_df = display_df.rename(columns={
    "status":       "Status",
    "bid_id":       "Bid ID",
    "title":        "Title",
    "organization": "Organization",
    "quantity":     "Qty",
    "start_date":   "Start Date",
    "end_date":     "End Date",
    "bid_value":    "Value",
    "scraped_at":   "Scraped At",
    "is_filled":    "Filled",
})

# Use st.data_editor for interactive checkboxes
edited_df = st.data_editor(
    display_df,
    column_config={
        "Status": st.column_config.TextColumn(
            "Status", width="medium",
        ),
        "Bid ID": st.column_config.TextColumn(
            "Bid ID", width="medium",
        ),
        "Title": st.column_config.TextColumn(
            "Title", width="large",
        ),
        "Organization": st.column_config.TextColumn(
            "Organization", width="large",
        ),
        "Qty": st.column_config.TextColumn(
            "Qty", width="small",
        ),
        "Start Date": st.column_config.TextColumn(
            "Start Date", width="medium",
        ),
        "End Date": st.column_config.TextColumn(
            "End Date", width="medium",
        ),
        "Value": st.column_config.TextColumn(
            "Value", width="small",
        ),
        "Scraped At": st.column_config.TextColumn(
            "Scraped At", width="medium",
        ),
        "Filled": st.column_config.CheckboxColumn(
            "Filled",
            help="Mark this bid as filled / handled",
            default=False,
            width="small",
        ),
    },
    disabled=["Status", "Bid ID", "Title", "Organization", "Qty",
              "Start Date", "End Date", "Value", "Scraped At"],
    hide_index=True,
    use_container_width=True,
    key="bid_table",
)

# Detect checkbox changes and persist them
if edited_df is not None:
    original_filled = display_df.set_index("Bid ID")["Filled"]
    edited_filled = edited_df.set_index("Bid ID")["Filled"]

    # Find changed rows
    try:
        changed = original_filled.compare(edited_filled)
        if not changed.empty:
            updates = {}
            for bid_id in changed.index:
                new_val = bool(edited_filled[bid_id])
                updates[bid_id] = new_val
            if updates:
                batch_update_filled(updates)
                st.toast(
                    f"✅ Updated {len(updates)} bid(s)",
                    icon="💾",
                )
    except Exception:
        pass


# ─── Analytics Section ────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### 📊 Analytics")

analytics_col1, analytics_col2 = st.columns(2)

with analytics_col1:
    # Count by category
    full_df = get_all_bids()
    if not full_df.empty:
        full_df["category"] = full_df["title"].apply(get_category)
        cat_counts = full_df["category"].value_counts()
        st.markdown("**Bids by Category**")
        st.bar_chart(cat_counts, color="#60a5fa")

with analytics_col2:
    # Timeline: bids scraped per day
    if not full_df.empty and "scraped_at" in full_df.columns:
        try:
            full_df["scrape_date"] = pd.to_datetime(
                full_df["scraped_at"], errors="coerce"
            ).dt.date
            daily = full_df.groupby("scrape_date").size()
            daily.index = pd.to_datetime(daily.index)
            st.markdown("**Bids Scraped per Day**")
            st.line_chart(daily, color="#34d399")
        except Exception:
            st.caption("Timeline data unavailable.")


# ─── Footer ───────────────────────────────────────────────────────────────────

st.markdown("---")
st.caption(
    f"GeM Bid Tracker • Data last updated: {last_updated} "
    f"• Auto-scraped every 12 hours via GitHub Actions"
)