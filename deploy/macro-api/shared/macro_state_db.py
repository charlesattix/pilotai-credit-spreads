"""
Macro State Database
====================
Production SQLite store for macro intelligence state.

Tables (defined in macro_system_architecture.md):
  snapshots     — weekly snapshot header
  sector_rs     — per-sector RS per snapshot
  macro_score   — 4-dimension macro score history
  macro_events  — FOMC / CPI / NFP calendar (updated daily)
  macro_state   — key-value current state

Integration API (read-only, called by scanner/backtester):
  get_current_macro_score()   -> float
  get_sector_rankings()       -> list[dict]
  get_event_scaling_factor()  -> float
  get_eligible_underlyings()  -> list[str]
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from shared.constants import DATA_DIR

logger = logging.getLogger(__name__)

MACRO_DB_PATH = Path(DATA_DIR) / "macro_state.db"

# Sectors eligible for universe expansion (liquid options, >300K daily options vol)
LIQUID_SECTOR_ETFS = ["XLE", "XLF", "XLV", "XLK", "XLI", "XLU", "XLY"]
BASE_UNIVERSE = ["SPY", "QQQ", "IWM"]


# ─────────────────────────────────────────────────────────────────────────────
# Connection & schema
# ─────────────────────────────────────────────────────────────────────────────

def get_db(path: Optional[str] = None) -> sqlite3.Connection:
    """Return a WAL-mode connection to macro_state.db."""
    db_path = Path(path) if path else MACRO_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Optional[str] = None) -> None:
    """Create all tables if they don't exist."""
    conn = get_db(path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                date            TEXT PRIMARY KEY,
                spy_close       REAL,
                top_sector_3m   TEXT,
                top_sector_12m  TEXT,
                leading_sectors TEXT,
                lagging_sectors TEXT,
                macro_overall   REAL,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sector_rs (
                date         TEXT NOT NULL,
                ticker       TEXT NOT NULL,
                name         TEXT,
                category     TEXT,
                close        REAL,
                rs_3m        REAL,
                rs_12m       REAL,
                rs_ratio     REAL,
                rs_momentum  REAL,
                rrg_quadrant TEXT,
                rank_3m      INTEGER,
                rank_12m     INTEGER,
                PRIMARY KEY (date, ticker)
            );

            CREATE TABLE IF NOT EXISTS macro_score (
                date              TEXT PRIMARY KEY,
                overall           REAL,
                growth            REAL,
                inflation         REAL,
                fed_policy        REAL,
                risk_appetite     REAL,
                regime            TEXT,
                cfnai_3m          REAL,
                payrolls_3m_avg_k REAL,
                cpi_yoy_pct       REAL,
                core_cpi_yoy_pct  REAL,
                breakeven_5y      REAL,
                t10y2y            REAL,
                fedfunds          REAL,
                vix               REAL,
                hy_oas_pct        REAL
            );

            CREATE TABLE IF NOT EXISTS macro_events (
                event_date     TEXT NOT NULL,
                event_type     TEXT NOT NULL,
                description    TEXT,
                days_out       INTEGER,
                scaling_factor REAL,
                PRIMARY KEY (event_date, event_type)
            );

            CREATE TABLE IF NOT EXISTS macro_state (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_sector_rs_date ON sector_rs(date);
            CREATE INDEX IF NOT EXISTS idx_macro_events_date ON macro_events(event_date);

            CREATE TABLE IF NOT EXISTS crypto_regime (
                snapshot_date       TEXT PRIMARY KEY,
                btc_price           REAL,
                eth_price           REAL,
                fear_greed_value    INTEGER,
                fear_greed_class    TEXT,
                btc_funding_rate    REAL,
                eth_funding_rate    REAL,
                btc_realized_vol_7d  REAL,
                btc_realized_vol_30d REAL,
                btc_iv_percentile   REAL,
                btc_dominance       REAL,
                btc_put_call_ratio  REAL,
                composite_score     REAL,
                score_band          TEXT,
                ma200_position      TEXT,
                overnight_gap_pct   REAL,
                created_at          TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_crypto_regime_date ON crypto_regime(snapshot_date);
        """)
        conn.commit()
        logger.debug("macro_state.db schema verified")
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Write helpers
# ─────────────────────────────────────────────────────────────────────────────

def _macro_regime(overall: Optional[float]) -> str:
    if overall is None:
        return "NEUTRAL_MACRO"
    if overall >= 65:
        return "BULL_MACRO"
    if overall < 45:
        return "BEAR_MACRO"
    return "NEUTRAL_MACRO"


def save_snapshot(snap: dict, db_path: Optional[str] = None) -> None:
    """
    Persist a full snapshot dict (as returned by MacroSnapshotEngine.generate_snapshot)
    into macro_state.db.  Uses INSERT OR REPLACE so re-running is idempotent.
    """
    conn = get_db(db_path)
    try:
        snap_date = snap["date"]
        ms = snap.get("macro_score") or {}
        ind = ms.get("indicators") or {}

        # snapshots table
        conn.execute(
            """
            INSERT OR REPLACE INTO snapshots
              (date, spy_close, top_sector_3m, top_sector_12m,
               leading_sectors, lagging_sectors, macro_overall)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snap_date,
                snap.get("spy_close"),
                snap.get("top_sector_3m"),
                snap.get("top_sector_12m"),
                json.dumps(snap.get("leading_sectors") or []),
                json.dumps(snap.get("lagging_sectors") or []),
                ms.get("overall"),
            ),
        )

        # sector_rs table
        for item in snap.get("sector_rankings") or []:
            conn.execute(
                """
                INSERT OR REPLACE INTO sector_rs
                  (date, ticker, name, category, close, rs_3m, rs_12m,
                   rs_ratio, rs_momentum, rrg_quadrant, rank_3m, rank_12m)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snap_date,
                    item["ticker"],
                    item.get("name"),
                    item.get("category"),
                    item.get("close"),
                    item.get("rs_3m"),
                    item.get("rs_12m"),
                    item.get("rs_ratio"),
                    item.get("rs_momentum"),
                    item.get("rrg_quadrant"),
                    item.get("rank_3m"),
                    item.get("rank_12m"),
                ),
            )

        # macro_score table
        conn.execute(
            """
            INSERT OR REPLACE INTO macro_score
              (date, overall, growth, inflation, fed_policy, risk_appetite, regime,
               cfnai_3m, payrolls_3m_avg_k, cpi_yoy_pct, core_cpi_yoy_pct,
               breakeven_5y, t10y2y, fedfunds, vix, hy_oas_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snap_date,
                ms.get("overall"),
                ms.get("growth"),
                ms.get("inflation"),
                ms.get("fed_policy"),
                ms.get("risk_appetite"),
                _macro_regime(ms.get("overall")),
                ind.get("cfnai_3m"),
                ind.get("payrolls_3m_avg_k"),
                ind.get("cpi_yoy_pct"),
                ind.get("core_cpi_yoy_pct"),
                ind.get("breakeven_5y"),
                ind.get("t10y2y"),
                ind.get("fedfunds"),
                ind.get("vix"),
                ind.get("hy_oas_pct"),
            ),
        )

        conn.commit()

    finally:
        conn.close()


def set_state(key: str, value: str, db_path: Optional[str] = None) -> None:
    conn = get_db(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO macro_state (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_state(key: str, default: Optional[str] = None, db_path: Optional[str] = None) -> Optional[str]:
    conn = get_db(db_path)
    try:
        row = conn.execute("SELECT value FROM macro_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def upsert_events(events: List[Dict], db_path: Optional[str] = None) -> None:
    """Upsert macro event rows (days_out and scaling_factor updated daily)."""
    conn = get_db(db_path)
    try:
        for ev in events:
            conn.execute(
                """
                INSERT OR REPLACE INTO macro_events
                  (event_date, event_type, description, days_out, scaling_factor)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ev["event_date"],
                    ev["event_type"],
                    ev.get("description", ""),
                    ev.get("days_out"),
                    ev.get("scaling_factor"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Integration API — called by scanner / backtester
# ─────────────────────────────────────────────────────────────────────────────

def get_current_macro_score(db_path: Optional[str] = None) -> float:
    """
    Return the macro overall score (0–100) from the most recent snapshot.
    Returns 50.0 (neutral) if no data is available.
    """
    conn = get_db(db_path)
    try:
        row = conn.execute(
            "SELECT overall FROM macro_score ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return float(row["overall"]) if row and row["overall"] is not None else 50.0
    finally:
        conn.close()


def get_sector_rankings(db_path: Optional[str] = None) -> List[Dict]:
    """
    Return sector RS rankings from the most recent snapshot, sorted by rank_3m.
    Each dict: {ticker, name, category, rs_3m, rs_12m, rank_3m, rank_12m, rrg_quadrant}
    """
    conn = get_db(db_path)
    try:
        latest_date = conn.execute(
            "SELECT MAX(date) AS d FROM sector_rs"
        ).fetchone()["d"]
        if not latest_date:
            return []
        rows = conn.execute(
            """
            SELECT ticker, name, category, rs_3m, rs_12m, rank_3m, rank_12m, rrg_quadrant
            FROM sector_rs
            WHERE date = ?
            ORDER BY rank_3m ASC
            """,
            (latest_date,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_event_scaling_factor(db_path: Optional[str] = None) -> float:
    """
    Return the current position-size scaling factor based on upcoming macro events.
    Value is stored in macro_state by the daily event gate job.
    Returns 1.0 (no scaling) if no event data available.
    """
    val = get_state("event_scaling_factor", default="1.0", db_path=db_path)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 1.0


def get_eligible_underlyings(
    regime: str = "NEUTRAL", db_path: Optional[str] = None
) -> List[str]:
    """
    Return tickers eligible as credit spread underlyings given current macro state.

    Logic:
    - Base universe is always included: SPY, QQQ, IWM
    - In BULL or NEUTRAL regime: add sectors ranked in top 4 by 3M RS
      (restricted to liquid-options sectors)
    - In BEAR regime: add sectors ranked in bottom 4 (for bear call spreads)
    - In BEAR_MACRO (macro score < 45): contract to base universe only
    """
    macro_score = get_current_macro_score(db_path)
    if macro_score < 45:
        # Macro veto: bear macro conditions, contract universe
        return BASE_UNIVERSE.copy()

    rankings = get_sector_rankings(db_path)
    eligible = BASE_UNIVERSE.copy()

    regime_upper = regime.upper()
    for item in rankings:
        ticker = item["ticker"]
        if ticker not in LIQUID_SECTOR_ETFS:
            continue
        rank = item.get("rank_3m") or 99
        if regime_upper in ("BULL", "NEUTRAL") and rank <= 4:
            eligible.append(ticker)
        elif regime_upper == "BEAR" and rank >= len(rankings) - 3:
            eligible.append(ticker)

    return list(dict.fromkeys(eligible))  # dedupe, preserve order


def get_latest_snapshot_date(db_path: Optional[str] = None) -> Optional[str]:
    """Return the date string of the most recent snapshot, or None."""
    conn = get_db(db_path)
    try:
        row = conn.execute("SELECT MAX(date) AS d FROM snapshots").fetchone()
        return row["d"] if row else None
    finally:
        conn.close()


def get_snapshot_count(db_path: Optional[str] = None) -> int:
    conn = get_db(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()
        return row["n"] if row else 0
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Crypto regime helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_latest_crypto_regime(db_path: Optional[str] = None) -> Optional[Dict]:
    """Return the most recent crypto regime snapshot as a dict, or None."""
    conn = get_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM crypto_regime ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_crypto_regime_history(days: int = 30, db_path: Optional[str] = None) -> List[Dict]:
    """Return the last *days* daily crypto regime snapshots, newest first."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM crypto_regime ORDER BY snapshot_date DESC LIMIT ?",
            (days,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
