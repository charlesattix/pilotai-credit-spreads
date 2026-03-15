"""
scripts/sync_db_from_alpaca.py
------------------------------
Diagnose and fix DB/Alpaca position sync issues for all 4 paper trading accounts.

Usage:
    python3 scripts/sync_db_from_alpaca.py            # report only
    python3 scripts/sync_db_from_alpaca.py --fix      # register orphans into DB
    python3 scripts/sync_db_from_alpaca.py --account exp059  # single account
"""

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

ROOT = Path(__file__).resolve().parent.parent

ACCOUNTS = {
    "exp036": {
        "key":    "PK4SGNFT3BGN54TCVOE4G44OYQ",
        "secret": "D3pVjqqBF9kLjyW1W9UMJcoqzVvqex5azhGB15fzgTCh",
        "account_id": "PA3D6UPXF5F2",
        "db":     ROOT / "data" / "pilotai_exp036.db",
    },
    "exp059": {
        "key":    "PK6URS6OBCSSHZZ2RQZSE2FOAH",
        "secret": "4PTrX1ppT5iZRAnwpcY7282of8UiFyN9pCEE2ZcmjzJ1",
        "account_id": "PA3LP867WNGU",
        "db":     ROOT / "data" / "pilotai_exp059.db",
    },
    "exp154": {
        "key":    "PKANAYVKHZX24Z3KCYNI2PLSCR",
        "secret": "GyBN2gCyuXfG7yTqFKs5JKTHL8eyC8SYTQ77Y3oyQp4J",
        "account_id": "PA3UNOV58WGK",
        "db":     ROOT / "data" / "pilotai_exp154.db",
    },
    "exp305": {
        "key":    "PKSPAM5732NK425PEUR7ZBELCB",
        "secret": "4Xmjn5wynCWoiJboiAf95tGozQCBD96rnQYujNTNuiZX",
        "account_id": "PA3W9FZKK6XD",
        "db":     ROOT / "data" / "pilotai_exp305.db",
    },
}

BASE_URL = "https://paper-api.alpaca.markets"

# ---------------------------------------------------------------------------
# Alpaca helpers
# ---------------------------------------------------------------------------

def _headers(account: dict) -> dict:
    return {
        "APCA-API-KEY-ID": account["key"],
        "APCA-API-SECRET-KEY": account["secret"],
    }


def get_alpaca_positions(account: dict) -> List[dict]:
    resp = requests.get(f"{BASE_URL}/v2/positions", headers=_headers(account), timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_alpaca_account(account: dict) -> dict:
    resp = requests.get(f"{BASE_URL}/v2/account", headers=_headers(account), timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# OCC symbol helpers
# ---------------------------------------------------------------------------

def build_occ_symbol(ticker: str, expiration: str, strike: float, opt_type: str) -> str:
    """Build an OCC symbol like SPY260417C00699000."""
    exp = expiration.replace("-", "")[2:]  # YYMMDD
    s = "C" if "call" in opt_type.lower() else "P"
    strike_str = f"{int(strike * 1000):08d}"
    return f"{ticker}{exp}{s}{strike_str}"


def parse_occ_symbol(symbol: str) -> Optional[dict]:
    """Parse OCC symbol into components. Returns None on failure."""
    m = re.match(r'^([A-Z]{1,6})(\d{6})([CP])(\d{8})$', symbol.replace(' ', ''))
    if not m:
        return None
    ticker, yymmdd, cp, strike_raw = m.groups()
    try:
        year = 2000 + int(yymmdd[:2])
        month = int(yymmdd[2:4])
        day = int(yymmdd[4:6])
        expiration = f"{year:04d}-{month:02d}-{day:02d}"
        strike = int(strike_raw) / 1000.0
    except (ValueError, ZeroDivisionError):
        return None
    return {
        "ticker": ticker,
        "expiration": expiration,
        "option_type": "call" if cp == "C" else "put",
        "strike": strike,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def get_open_trades(db_path: Path) -> List[dict]:
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status='open' ORDER BY entry_date"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_active_trades(db_path: Path) -> List[dict]:
    """Get all non-closed trades (open + needs_investigation + pending_open)."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status NOT IN ('closed','closed_profit','closed_loss','closed_expiry','closed_manual','failed_open') ORDER BY entry_date"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_trade_raw(conn: sqlite3.Connection, trade: dict) -> None:
    metadata = {k: v for k, v in trade.items() if k not in (
        "id", "source", "ticker", "strategy_type", "status",
        "short_strike", "long_strike", "expiration", "credit",
        "contracts", "entry_date", "exit_date", "exit_reason", "pnl",
        "alpaca_client_order_id", "alpaca_fill_price", "alpaca_status",
        "created_at", "updated_at",
    )}
    conn.execute("""
        INSERT INTO trades (id, source, ticker, strategy_type, status,
            short_strike, long_strike, expiration, credit, contracts,
            entry_date, exit_date, exit_reason, pnl, metadata,
            alpaca_client_order_id, alpaca_fill_price, alpaca_status,
            updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            status=excluded.status,
            exit_date=excluded.exit_date,
            exit_reason=excluded.exit_reason,
            pnl=excluded.pnl,
            metadata=excluded.metadata,
            alpaca_client_order_id=excluded.alpaca_client_order_id,
            alpaca_fill_price=excluded.alpaca_fill_price,
            alpaca_status=excluded.alpaca_status,
            updated_at=datetime('now')
    """, (
        str(trade.get("id", "")),
        trade.get("source", "sync_script"),
        trade.get("ticker", ""),
        trade.get("strategy_type", "unknown"),
        trade.get("status", "open"),
        trade.get("short_strike"),
        trade.get("long_strike"),
        str(trade.get("expiration", "")),
        trade.get("credit"),
        trade.get("contracts", 1),
        trade.get("entry_date"),
        trade.get("exit_date"),
        trade.get("exit_reason"),
        trade.get("pnl"),
        json.dumps(metadata, default=str),
        trade.get("alpaca_client_order_id"),
        trade.get("alpaca_fill_price"),
        trade.get("alpaca_status"),
    ))


def insert_reconciliation_event(conn: sqlite3.Connection, trade_id: str, event_type: str, details: dict) -> None:
    conn.execute(
        "INSERT INTO reconciliation_events (trade_id, event_type, details) VALUES (?, ?, ?)",
        (trade_id, event_type, json.dumps(details, default=str)),
    )


# ---------------------------------------------------------------------------
# Core comparison logic
# ---------------------------------------------------------------------------

def _expected_symbols_for_trade(trade: dict) -> List[Tuple[str, str]]:
    """Return list of (occ_symbol, role) for each leg of a DB trade."""
    ticker = trade.get("ticker", "")
    exp = str(trade.get("expiration", "")).split(" ")[0].split("T")[0]
    spread_type = str(trade.get("strategy_type", trade.get("type", ""))).lower()
    short_strike = trade.get("short_strike")
    long_strike = trade.get("long_strike")

    if not ticker or not exp:
        return []

    if "condor" in spread_type:
        put_short = trade.get("put_short_strike") or short_strike
        put_long = trade.get("put_long_strike") or long_strike
        call_short = trade.get("call_short_strike")
        call_long = trade.get("call_long_strike")
        result = []
        if put_short:
            result.append((build_occ_symbol(ticker, exp, put_short, "put"), "put_short"))
        if put_long:
            result.append((build_occ_symbol(ticker, exp, put_long, "put"), "put_long"))
        if call_short:
            result.append((build_occ_symbol(ticker, exp, call_short, "call"), "call_short"))
        if call_long:
            result.append((build_occ_symbol(ticker, exp, call_long, "call"), "call_long"))
        return result
    else:
        opt_type = "call" if "call" in spread_type else "put"
        result = []
        if short_strike:
            result.append((build_occ_symbol(ticker, exp, short_strike, opt_type), "short"))
        if long_strike:
            result.append((build_occ_symbol(ticker, exp, long_strike, opt_type), "long"))
        return result


def compare_account(name: str, account: dict) -> dict:
    """Compare DB state vs Alpaca for one account. Returns a report dict."""
    db_path = account["db"]

    # Fetch Alpaca data
    try:
        alpaca_positions = {p["symbol"]: p for p in get_alpaca_positions(account)}
        alpaca_account = get_alpaca_account(account)
        alpaca_error = None
    except Exception as e:
        alpaca_positions = {}
        alpaca_account = {}
        alpaca_error = str(e)

    # Fetch DB data
    open_trades = get_open_trades(db_path)
    all_active = get_all_active_trades(db_path)

    # Build managed symbol set from open trades
    managed_symbols: Dict[str, dict] = {}  # symbol -> trade
    for trade in open_trades:
        for sym, role in _expected_symbols_for_trade(trade):
            managed_symbols[sym] = trade

    # Detect orphans: in Alpaca but not managed by any DB open trade
    orphans = []
    for sym, pos in alpaca_positions.items():
        asset_class = str(pos.get("asset_class", "")).lower()
        if "option" not in asset_class:
            continue
        if sym not in managed_symbols:
            orphans.append(pos)

    # Detect phantoms: DB open trade whose ALL legs are missing from Alpaca
    phantoms = []
    partial_mismatches = []
    qty_mismatches = []
    for trade in open_trades:
        legs = _expected_symbols_for_trade(trade)
        if not legs:
            continue
        missing_legs = [sym for sym, _ in legs if sym not in alpaca_positions]
        present_legs = [sym for sym, _ in legs if sym in alpaca_positions]

        if len(missing_legs) == len(legs):
            phantoms.append({"trade": trade, "expected_symbols": [s for s, _ in legs]})
        elif missing_legs:
            partial_mismatches.append({
                "trade": trade,
                "missing": missing_legs,
                "present": present_legs,
            })
        else:
            # All legs present - check qty mismatch
            for sym, role in legs:
                if sym in alpaca_positions:
                    db_qty = abs(int(trade.get("contracts", 0) or 0))
                    alp_qty = abs(int(alpaca_positions[sym].get("qty", "0") or 0))
                    if db_qty > 0 and alp_qty > 0 and db_qty != alp_qty:
                        qty_mismatches.append({
                            "trade_id": trade["id"],
                            "symbol": sym,
                            "role": role,
                            "db_qty": db_qty,
                            "alpaca_qty": alp_qty,
                        })

    return {
        "account": name,
        "alpaca_error": alpaca_error,
        "alpaca_equity": alpaca_account.get("equity"),
        "alpaca_cash": alpaca_account.get("cash"),
        "alpaca_status": alpaca_account.get("status"),
        "alpaca_position_count": len(alpaca_positions),
        "db_open_count": len(open_trades),
        "db_active_count": len(all_active),
        "open_trades": open_trades,
        "alpaca_positions": alpaca_positions,
        "orphans": orphans,
        "phantoms": phantoms,
        "partial_mismatches": partial_mismatches,
        "qty_mismatches": qty_mismatches,
    }


# ---------------------------------------------------------------------------
# Fix: register orphans into DB
# ---------------------------------------------------------------------------

def fix_orphans(name: str, account: dict, report: dict, dry_run: bool = False) -> List[str]:
    """Insert orphan Alpaca positions as DB records. Returns list of messages."""
    messages = []
    if not report["orphans"]:
        messages.append(f"[{name}] No orphans to fix.")
        return messages

    db_path = account["db"]
    conn = get_db(db_path)
    try:
        for pos in report["orphans"]:
            sym = pos["symbol"]
            info = parse_occ_symbol(sym)
            if not info:
                messages.append(f"[{name}] SKIP orphan {sym}: cannot parse OCC symbol")
                continue

            ticker = info["ticker"]
            expiration = info["expiration"]
            opt_type = info["option_type"]
            strike = info["strike"]
            qty = abs(int(pos.get("qty", "0") or 0))
            side = pos.get("side", "")
            avg_price = pos.get("avg_entry_price", "0")

            # Determine spread_type from side and option type
            if side == "short" and opt_type == "call":
                spread_type = "bear_call"
            elif side == "short" and opt_type == "put":
                spread_type = "bull_put"
            else:
                spread_type = "unknown_leg"

            orphan_id = f"orphan-{sym[:20]}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

            record = {
                "id": orphan_id,
                "ticker": ticker,
                "strategy_type": spread_type,
                "status": "unmanaged",
                "short_strike": strike if side == "short" else None,
                "long_strike": strike if side == "long" else None,
                "expiration": expiration,
                "credit": 0.0,
                "contracts": qty,
                "entry_date": datetime.now(timezone.utc).isoformat(),
                "alpaca_status": "filled",
                "alpaca_symbol": sym,
                "avg_entry_price": avg_price,
                "source": "sync_script",
            }

            msg = (
                f"[{name}] {'DRY-RUN: Would register' if dry_run else 'Registering'} orphan: "
                f"{sym} qty={qty} side={side} as id={orphan_id}"
            )
            messages.append(msg)
            print(msg)

            if not dry_run:
                upsert_trade_raw(conn, record)
                insert_reconciliation_event(conn, orphan_id, "registered_orphan_by_sync_script", {
                    "symbol": sym,
                    "qty": qty,
                    "side": side,
                    "avg_entry_price": avg_price,
                })

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    return messages


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_report(reports: List[dict]) -> None:
    sep = "=" * 70
    for r in reports:
        name = r["account"]
        print(f"\n{sep}")
        print(f"  ACCOUNT: {name}")
        print(sep)

        if r["alpaca_error"]:
            print(f"  ERROR fetching Alpaca: {r['alpaca_error']}")
            continue

        print(f"  Alpaca equity:     ${r['alpaca_equity']}")
        print(f"  Alpaca cash:       ${r['alpaca_cash']}")
        print(f"  Alpaca status:     {r['alpaca_status']}")
        print(f"  Alpaca positions:  {r['alpaca_position_count']} legs")
        print(f"  DB open trades:    {r['db_open_count']}")
        print(f"  DB active trades:  {r['db_active_count']} (includes non-closed)")

        if not r["orphans"] and not r["phantoms"] and not r["partial_mismatches"] and not r["qty_mismatches"]:
            print("  STATUS: CLEAN — no discrepancies found")
            continue

        if r["orphans"]:
            print(f"\n  ORPHANS ({len(r['orphans'])} positions in Alpaca with no DB record):")
            for pos in r["orphans"]:
                print(f"    {pos['symbol']:35s}  qty={pos['qty']:5s}  side={pos['side']:6s}  "
                      f"market_value=${pos.get('market_value','?')}")

        if r["phantoms"]:
            print(f"\n  PHANTOMS ({len(r['phantoms'])} DB open trades with no Alpaca legs):")
            for p in r["phantoms"]:
                t = p["trade"]
                print(f"    trade_id={t['id']}  {t.get('strategy_type','')}  "
                      f"exp={t.get('expiration','')}  x{t.get('contracts','')}  "
                      f"exit_reason={t.get('exit_reason','')}")
                for sym in p["expected_symbols"]:
                    print(f"      missing leg: {sym}")

        if r["partial_mismatches"]:
            print(f"\n  PARTIAL MISMATCHES ({len(r['partial_mismatches'])} trades with some legs missing):")
            for pm in r["partial_mismatches"]:
                t = pm["trade"]
                print(f"    trade_id={t['id']}  {t.get('strategy_type','')}")
                print(f"      missing: {pm['missing']}")
                print(f"      present: {pm['present']}")

        if r["qty_mismatches"]:
            print(f"\n  QTY MISMATCHES ({len(r['qty_mismatches'])} legs with different qty):")
            for qm in r["qty_mismatches"]:
                print(f"    trade_id={qm['trade_id']}  {qm['symbol']}  "
                      f"DB={qm['db_qty']}  Alpaca={qm['alpaca_qty']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sync DB state with Alpaca positions")
    parser.add_argument("--fix", action="store_true", help="Register orphan Alpaca positions into DB")
    parser.add_argument("--account", choices=list(ACCOUNTS.keys()), help="Run for a single account only")
    args = parser.parse_args()

    accounts_to_run = {args.account: ACCOUNTS[args.account]} if args.account else ACCOUNTS

    reports = []
    for name, account in accounts_to_run.items():
        print(f"Checking {name}...", flush=True)
        report = compare_account(name, account)
        reports.append(report)

    print_report(reports)

    if args.fix:
        print(f"\n{'=' * 70}")
        print("  APPLYING FIXES")
        print("=" * 70)
        for report in reports:
            name = report["account"]
            account = ACCOUNTS[name]
            if report["alpaca_error"]:
                print(f"[{name}] Skipping fixes due to Alpaca error")
                continue
            messages = fix_orphans(name, account, report, dry_run=False)
            for msg in messages:
                print(msg)
    else:
        # Show what --fix would do
        has_orphans = any(r["orphans"] for r in reports)
        if has_orphans:
            print("\nRun with --fix to register orphan positions into the DB.")


if __name__ == "__main__":
    main()
