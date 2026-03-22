# Macro Intelligence System — Architecture

**Version:** 1.0
**Date:** 2026-03-07
**Status:** Production

---

## Overview

The Macro Intelligence layer is a **pre-filter and position sizer** that operates upstream of the existing credit spread scanner. It adds sector rotation awareness, macro regime scoring, and event gating without touching `backtester.py`, `spread_strategy.py`, or `ComboRegimeDetector`.

```
┌──────────────────────────────────────────────────────────────────┐
│                    MACRO INTELLIGENCE LAYER                      │
│                                                                  │
│  MacroSnapshotEngine ──► Sector RS + RRG quadrants              │
│       │                  Macro score (4 dimensions)             │
│       │                                                          │
│  MacroEventGate ──────► Event scaling factor (0.50–1.00)        │
│       │                  FOMC / CPI / NFP calendar              │
│       │                                                          │
│  macro_state.db ──────► Single source of truth                  │
│                          (sector_rs, macro_score, macro_events)  │
└──────────────────────────────────┬───────────────────────────────┘
                                   │  Integration API (read-only)
                                   │  get_current_macro_score()
                                   │  get_sector_rankings()
                                   │  get_event_scaling_factor()
                                   │  get_eligible_underlyings()
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                    EXISTING SYSTEM (unchanged)                   │
│                                                                  │
│  ComboRegimeDetector (BULL / BEAR / NEUTRAL)                    │
│         │                                                        │
│  CreditSpreadStrategy.evaluate_spread_opportunity()             │
│         │                                                        │
│  AlertPositionSizer.size() ← effective_risk_pct (macro-scaled)  │
│         │                                                        │
│  AlpacaProvider.submit_order()                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Files

### New files

| File | Purpose |
|------|---------|
| `shared/macro_state_db.py` | `macro_state.db` schema, save/query functions, integration API |
| `shared/macro_event_gate.py` | FOMC/CPI/NFP calendar, scaling factor computation |
| `scripts/run_macro_snapshot.py` | CLI entry: `--weekly`, `--daily`, `--backfill` |
| `scripts/macro_report.py` | Human-readable report from DB |

### Modified files

| File | Change |
|------|--------|
| `shared/macro_snapshot_engine.py` | Added `save_to_db(snap, db_conn)` |

### Data files

| File | Purpose |
|------|---------|
| `data/macro_state.db` | Production state DB (sector_rs, macro_score, macro_events, snapshots) |
| `data/macro_cache/macro_cache.db` | Polygon + FRED raw data cache (append-only) |

---

## Database Schema — `data/macro_state.db`

### `snapshots` — weekly snapshot header
```sql
CREATE TABLE snapshots (
    date           TEXT PRIMARY KEY,   -- YYYY-MM-DD (Friday)
    spy_close      REAL,
    top_sector_3m  TEXT,
    top_sector_12m TEXT,
    leading_sectors TEXT,              -- JSON array of tickers
    lagging_sectors TEXT,              -- JSON array of tickers
    macro_overall  REAL,
    created_at     TEXT DEFAULT (datetime('now'))
);
```

### `sector_rs` — per-sector RS per snapshot (from proposal Section F)
```sql
CREATE TABLE sector_rs (
    date         TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    name         TEXT,
    category     TEXT,        -- 'sector' | 'thematic'
    close        REAL,
    rs_3m        REAL,        -- % outperformance vs SPY over 3M
    rs_12m       REAL,        -- % outperformance vs SPY over 12M
    rs_ratio     REAL,        -- RRG normalized (100 = universe avg)
    rs_momentum  REAL,        -- RRG momentum normalized (100 = avg)
    rrg_quadrant TEXT,        -- Leading / Weakening / Lagging / Improving
    rank_3m      INTEGER,
    rank_12m     INTEGER,
    PRIMARY KEY (date, ticker)
);
```

### `macro_score` — 4-dimension macro score (from proposal Section F)
```sql
CREATE TABLE macro_score (
    date             TEXT PRIMARY KEY,
    overall          REAL,        -- 0–100
    growth           REAL,
    inflation        REAL,
    fed_policy       REAL,
    risk_appetite    REAL,
    regime           TEXT,        -- 'BULL_MACRO' | 'NEUTRAL_MACRO' | 'BEAR_MACRO'
    -- raw indicators
    cfnai_3m         REAL,
    payrolls_3m_avg_k REAL,
    cpi_yoy_pct      REAL,
    core_cpi_yoy_pct REAL,
    breakeven_5y     REAL,
    t10y2y           REAL,
    fedfunds         REAL,
    vix              REAL,
    hy_oas_pct       REAL
);
```

### `macro_events` — upcoming FOMC/CPI/NFP (from proposal Section F)
```sql
CREATE TABLE macro_events (
    event_date     TEXT NOT NULL,
    event_type     TEXT NOT NULL,  -- 'FOMC' | 'CPI' | 'NFP'
    description    TEXT,
    days_out       INTEGER,        -- recomputed daily
    scaling_factor REAL,           -- 0.50–1.00
    PRIMARY KEY (event_date, event_type)
);
```

### `macro_state` — key-value current state
```sql
CREATE TABLE macro_state (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
```

Key state entries:
- `event_scaling_factor` — current composite scaling (worst of any upcoming event)
- `last_weekly_snapshot` — date of last full snapshot run
- `last_daily_check` — date of last event gate check

---

## Scheduling

| Job | Schedule (ET) | Mode | Duration |
|-----|--------------|------|----------|
| Weekly full snapshot | Friday 5:00 PM | `--weekly` | ~30s |
| Daily event gate check | Mon–Fri 6:00 AM | `--daily` | <1s |

```bash
# Weekly — every Friday at 5 PM ET
python3 scripts/run_macro_snapshot.py --weekly

# Daily — every weekday at 6 AM ET
python3 scripts/run_macro_snapshot.py --daily
```

### Automated execution (via `main.py scheduler`)

The weekly snapshot runs inside `_run_macro_weekly_with_retry()` in `main.py`, invoked automatically when the scheduler fires `SLOT_MACRO_WEEKLY` (Friday 5 PM ET).

**Retry policy — 5 attempts, exponential backoff:**

| Attempt | Delay before retry |
|---------|--------------------|
| 1 → fail | 5 min (300s) |
| 2 → fail | 10 min (600s) |
| 3 → fail | 20 min (1200s) |
| 4 → fail | 40 min (2400s) |
| 5 → fail | no retry — Telegram alert sent |

On final failure, `shared.telegram_alerts.send_message()` fires a Telegram notification (requires `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`). Manual recovery:

```bash
python3 scripts/run_macro_snapshot.py --weekly
```

---

## Integration API

These four functions are the only interface the trading system needs to query macro state:

```python
from shared.macro_state_db import (
    get_current_macro_score,    # -> float (0–100)
    get_sector_rankings,        # -> list[dict]
    get_event_scaling_factor,   # -> float (0.50–1.00)
    get_eligible_underlyings,   # -> list[str]
)
```

### `get_current_macro_score() -> float`
Returns macro overall score 0–100 from the most recent snapshot.
- ≥ 65: BULL_MACRO — full risk allocation
- 45–65: NEUTRAL_MACRO — standard allocation
- < 45: BEAR_MACRO — reduce directional exposure

### `get_sector_rankings() -> list[dict]`
Returns sector RS rankings from latest snapshot, sorted by `rank_3m`.
Each dict: `{ticker, name, rs_3m, rs_12m, rank_3m, rrg_quadrant}`

### `get_event_scaling_factor() -> float`
Returns current position size scaling factor based on upcoming events:
- FOMC scaling: `{5d: 1.00, 4d: 0.90, 3d: 0.80, 2d: 0.70, 1d: 0.60, 0d: 0.50}`
- CPI scaling:  `{2d: 1.00, 1d: 0.75, 0d: 0.65}`
- NFP scaling:  `{2d: 1.00, 1d: 0.80, 0d: 0.75}`
- Composite: min() of all active event scalings

### `get_eligible_underlyings(regime) -> list[str]`
Returns tickers eligible as credit spread underlyings based on macro state:
- Base universe: `["SPY", "QQQ", "IWM"]`
- Top-ranked liquid sectors added when RS rank ≤ 4 and regime ≠ BEAR
- Eligible liquid sectors: XLE, XLF, XLV, XLK, XLI, XLU

---

## Macro Regime Classification

| Score | Regime | Effect on trading |
|-------|--------|-------------------|
| ≥ 65 | BULL_MACRO | +0–20% size boost available; universe expansion active |
| 45–65 | NEUTRAL_MACRO | Standard sizing; base universe only |
| < 45 | BEAR_MACRO | −25% size reduction; universe contracted to SPY/QQQ/IWM |

---

## Event Scaling Logic

Position size multiplier = `base_risk × event_scaling_factor`

Example: FOMC in 2 days → scaling = 0.70
- 5% base risk × 0.70 = 3.5% effective risk

All active events contribute; the system takes the **minimum** (most conservative).

---

## Data Sources

| Source | Data | Method |
|--------|------|--------|
| Polygon REST API | Adjusted daily OHLCV for 15 ETFs + SPY | `prefetch_prices()` |
| FRED public CSV | 9 macro series (VIX, spreads, CPI, payrolls, CFNAI) | `prefetch_fred()` |
| Built-in calendar | FOMC 2026 dates, NFP/CPI date formulas | `macro_event_gate.py` |

No API key required for FRED — uses the public `fredgraph.csv` endpoint.

---

## Historical Backfill

323 weekly snapshots (2020-01-03 → 2026-03-06) imported from:
`output/historical_snapshots/YYYY/YYYY-MM-DD.json`

Run once:
```bash
python3 scripts/run_macro_snapshot.py --backfill
```
