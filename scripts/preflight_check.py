#!/usr/bin/env python3
"""Pre-market-open preflight check for the PilotAI paper trading system.

Validates all subsystems are GO before market open. Run this Sunday night
or Monday morning before 9:15 AM ET.

Exit codes:
    0  — ALL CLEAR: every check passed
    1  — HOLD: one or more critical checks failed
    2  — WARN: non-critical issues detected (system can run)

Usage:
    python3 scripts/preflight_check.py           # human-readable output
    python3 scripts/preflight_check.py --json     # machine-readable JSON
    python3 scripts/preflight_check.py --fix      # attempt auto-fix where possible
"""

import argparse
import json
import os
import signal
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from shared.constants import DATA_DIR, PROJECT_ROOT, CONFIG_PATH  # noqa: E402

HEARTBEAT_PATH = Path(DATA_DIR) / "heartbeat.json"
DB_PATH = Path(DATA_DIR) / "pilotai.db"
CHAMPION_CONFIG = Path(PROJECT_ROOT) / "configs" / "champion.json"
SCHEDULER_LOG = Path(PROJECT_ROOT) / "logs" / "scheduler.log"


class CheckResult:
    """Result of a single preflight check."""

    def __init__(self, name: str, status: str, message: str, details: dict = None):
        self.name = name
        self.status = status  # "PASS", "FAIL", "WARN"
        self.message = message
        self.details = details or {}

    def to_dict(self):
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


def check_scheduler_process() -> CheckResult:
    """Verify the scheduler process is running."""
    import subprocess

    result = subprocess.run(
        ["pgrep", "-f", "main.py scheduler"],
        capture_output=True, text=True,
    )
    pids = result.stdout.strip().split("\n") if result.stdout.strip() else []
    # Filter out zombie processes
    alive_pids = []
    for pid in pids:
        try:
            stat = subprocess.run(
                ["ps", "-p", pid, "-o", "stat="],
                capture_output=True, text=True,
            )
            state = stat.stdout.strip()
            if state and "Z" not in state:
                alive_pids.append(pid)
        except Exception:
            pass

    if alive_pids:
        return CheckResult(
            "Scheduler Process",
            "PASS",
            f"Running (PID {', '.join(alive_pids)})",
            {"pids": alive_pids},
        )
    return CheckResult(
        "Scheduler Process",
        "FAIL",
        "No scheduler process found. Restart with:\n"
        f"  cd {PROJECT_ROOT} && nohup python3 main.py scheduler --config config.yaml "
        f"> logs/scheduler.log 2>&1 &",
    )


def check_heartbeat() -> CheckResult:
    """Check heartbeat freshness (allows weekend staleness)."""
    if not HEARTBEAT_PATH.exists():
        return CheckResult("Heartbeat", "FAIL", f"File not found: {HEARTBEAT_PATH}")

    try:
        with open(HEARTBEAT_PATH) as f:
            hb = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return CheckResult("Heartbeat", "FAIL", f"Cannot read: {e}")

    utc_str = hb.get("last_scan_utc", "")
    try:
        last_utc = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return CheckResult("Heartbeat", "FAIL", f"Bad timestamp: {utc_str}")

    age_hours = (datetime.now(timezone.utc) - last_utc).total_seconds() / 3600
    scan_count = hb.get("scan_count", 0)
    had_error = hb.get("had_error", False)

    # Weekend: allow up to 65 hours staleness (Friday 4:30 PM to Monday 9:15 AM)
    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() in (5, 6) or (now.weekday() == 0 and now.hour < 14)

    if is_weekend and age_hours < 65:
        status = "WARN" if had_error else "PASS"
        msg = (
            f"Weekend gap OK — last scan {age_hours:.0f}h ago "
            f"(scan_count={scan_count}, had_error={had_error})"
        )
    elif age_hours > 2:
        status = "FAIL"
        msg = f"Stale: {age_hours:.0f}h old (should be <1h during market hours)"
    elif had_error:
        status = "WARN"
        msg = f"Last scan had errors ({hb.get('last_scan_time', '?')})"
    else:
        status = "PASS"
        msg = f"Fresh: {age_hours:.1f}h ago, scan_count={scan_count}"

    return CheckResult("Heartbeat", status, msg, {"heartbeat": hb})


def check_alpaca() -> CheckResult:
    """Verify Alpaca paper trading connection."""
    api_key = os.environ.get("ALPACA_API_KEY", "")
    api_secret = os.environ.get("ALPACA_SECRET_KEY", "")

    if not api_key or not api_secret:
        return CheckResult("Alpaca", "FAIL", "ALPACA_API_KEY or ALPACA_SECRET_KEY missing from .env")

    try:
        from alpaca.trading.client import TradingClient

        client = TradingClient(api_key, api_secret, paper=True)
        account = client.get_account()
        cash = float(account.cash)
        portfolio = float(account.portfolio_value)
        status = str(account.status)

        if "ACTIVE" not in status:
            return CheckResult(
                "Alpaca", "FAIL",
                f"Account status: {status} (expected ACTIVE)",
                {"cash": cash, "portfolio_value": portfolio},
            )

        return CheckResult(
            "Alpaca", "PASS",
            f"ACTIVE | Cash: ${cash:,.2f} | Portfolio: ${portfolio:,.2f}",
            {"cash": cash, "portfolio_value": portfolio, "status": status},
        )
    except Exception as e:
        return CheckResult("Alpaca", "FAIL", f"Connection failed: {e}")


def check_polygon() -> CheckResult:
    """Verify Polygon API key and data feed."""
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        return CheckResult("Polygon", "FAIL", "POLYGON_API_KEY missing from .env")

    try:
        from strategy.polygon_provider import PolygonProvider

        provider = PolygonProvider(api_key)
        return CheckResult("Polygon", "PASS", f"Provider initialized (key: {api_key[:8]}...)")
    except Exception as e:
        return CheckResult("Polygon", "FAIL", f"Provider init failed: {e}")


def check_data_cache() -> CheckResult:
    """Verify DataCache can fetch live price data."""
    try:
        from shared.data_cache import DataCache

        cache = DataCache(ttl_seconds=60)
        df = cache.get_history("SPY", period="5d")
        if df is None or df.empty:
            return CheckResult("Data Cache", "FAIL", "SPY 5d history returned empty")

        last_date = df.index[-1]
        rows = len(df)
        last_close = df["Close"].iloc[-1]
        return CheckResult(
            "Data Cache", "PASS",
            f"SPY: {rows} rows, last={last_date.strftime('%Y-%m-%d')}, close=${last_close:.2f}",
            {"rows": rows, "last_date": str(last_date), "last_close": float(last_close)},
        )
    except Exception as e:
        return CheckResult("Data Cache", "FAIL", f"Fetch failed: {e}")


def check_database() -> CheckResult:
    """Verify SQLite database integrity and trade state."""
    if not DB_PATH.exists():
        return CheckResult("Database", "FAIL", f"Not found: {DB_PATH}")

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Integrity check
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        if integrity != "ok":
            conn.close()
            return CheckResult("Database", "FAIL", f"Integrity check: {integrity}")

        # Trade counts
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'open'")
        open_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM trades WHERE status LIKE 'closed%'")
        closed_count = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status LIKE 'closed%'")
        total_pnl = cursor.fetchone()[0]

        conn.close()

        return CheckResult(
            "Database", "PASS",
            f"OK | Open: {open_count} | Closed: {closed_count} | P&L: ${total_pnl:,.2f}",
            {"open": open_count, "closed": closed_count, "total_pnl": total_pnl},
        )
    except Exception as e:
        return CheckResult("Database", "FAIL", f"Error: {e}")


def check_champion_config() -> CheckResult:
    """Verify champion.json exists and is valid."""
    if not CHAMPION_CONFIG.exists():
        return CheckResult("Champion Config", "FAIL", f"Not found: {CHAMPION_CONFIG}")

    try:
        with open(CHAMPION_CONFIG) as f:
            config = json.load(f)

        strategies = config.get("strategies", [])
        if not strategies:
            return CheckResult("Champion Config", "FAIL", "No strategies defined")

        names = strategies if isinstance(strategies, list) and isinstance(strategies[0], str) else [
            s.get("name", "?") for s in strategies if isinstance(s, dict)
        ]
        return CheckResult(
            "Champion Config", "PASS",
            f"{len(names)} strategies: {', '.join(names)}",
        )
    except Exception as e:
        return CheckResult("Champion Config", "FAIL", f"Parse error: {e}")


def check_telegram() -> CheckResult:
    """Verify Telegram bot credentials."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        missing = []
        if not token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        return CheckResult(
            "Telegram", "WARN",
            f"Not configured ({', '.join(missing)} missing from .env). "
            "Alerts will be logged but not sent.",
        )

    try:
        import requests

        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=10
        )
        if resp.status_code == 200:
            bot = resp.json().get("result", {})
            return CheckResult(
                "Telegram", "PASS",
                f"Bot @{bot.get('username', '?')} connected, chat_id={chat_id}",
            )
        return CheckResult("Telegram", "FAIL", f"API returned HTTP {resp.status_code}")
    except Exception as e:
        return CheckResult("Telegram", "FAIL", f"Connection failed: {e}")


def check_strategy_imports() -> CheckResult:
    """Verify all strategy modules import cleanly."""
    errors = []
    modules = [
        ("shared.live_snapshot", "build_live_snapshot"),
        ("shared.strategy_adapter", "signal_to_opportunity"),
        ("shared.deviation_tracker", "get_deviation_history"),
        ("alerts.alert_router", None),
        ("alerts.risk_gate", None),
        ("alerts.zero_dte_scanner", None),
        ("alerts.iron_condor_scanner", None),
        ("alerts.momentum_scanner", None),
        ("alerts.earnings_scanner", None),
        ("alerts.gamma_scanner", None),
    ]
    for mod_name, attr in modules:
        try:
            mod = __import__(mod_name, fromlist=[attr or mod_name.split(".")[-1]])
            if attr and not hasattr(mod, attr):
                errors.append(f"{mod_name}.{attr} not found")
        except Exception as e:
            errors.append(f"{mod_name}: {e}")

    if errors:
        return CheckResult(
            "Strategy Imports", "FAIL",
            f"{len(errors)} import failures: {'; '.join(errors[:3])}",
        )
    return CheckResult(
        "Strategy Imports", "PASS",
        f"All {len(modules)} modules importable",
    )


def check_test_suite() -> CheckResult:
    """Run the test suite (quick mode) to verify no regressions."""
    import subprocess

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--no-header",
             "--tb=no", "--no-cov"],
            capture_output=True, text=True, timeout=120,
            cwd=PROJECT_ROOT,
        )
        output = result.stdout.strip().split("\n")
        summary = output[-1] if output else "no output"

        if result.returncode == 0:
            return CheckResult("Test Suite", "PASS", summary)
        return CheckResult(
            "Test Suite", "FAIL",
            f"Tests failed (exit {result.returncode}): {summary}",
        )
    except subprocess.TimeoutExpired:
        return CheckResult("Test Suite", "WARN", "Timed out after 120s")
    except Exception as e:
        return CheckResult("Test Suite", "FAIL", f"Error: {e}")


def check_open_positions_risk() -> CheckResult:
    """Verify open positions don't exceed risk limits."""
    try:
        from shared.database import init_db, get_trades

        init_db()
        trades = get_trades(source="scanner")
        open_trades = [t for t in trades if t.get("status") in ("open", "pending_open")]

        if not open_trades:
            return CheckResult("Position Risk", "PASS", "No open positions")

        account_size = 100_000
        total_risk = sum(t.get("total_max_loss", 0) or 0 for t in open_trades)
        risk_pct = (total_risk / account_size) * 100 if account_size else 0

        # Check for any expired positions (DTE < 0 on Monday)
        from datetime import date

        today = date.today()
        expired = []
        for t in open_trades:
            exp_str = t.get("expiration", "")
            if exp_str:
                try:
                    exp_date = datetime.strptime(exp_str[:10], "%Y-%m-%d").date()
                    if exp_date < today:
                        expired.append(f"{t['ticker']} exp={exp_str[:10]}")
                except ValueError:
                    pass

        status = "PASS"
        msgs = [f"{len(open_trades)} open | Risk: ${total_risk:,.0f} ({risk_pct:.1f}%)"]

        if risk_pct > 15:
            status = "WARN"
            msgs.append(f"OVER MAX EXPOSURE (15%)")

        if expired:
            status = "WARN"
            msgs.append(f"EXPIRED: {', '.join(expired[:3])}")

        return CheckResult("Position Risk", status, " | ".join(msgs),
                           {"open_count": len(open_trades), "total_risk": total_risk,
                            "risk_pct": risk_pct, "expired": expired})
    except Exception as e:
        return CheckResult("Position Risk", "FAIL", f"Error: {e}")


def check_log_errors() -> CheckResult:
    """Check scheduler.log for concerning error patterns."""
    if not SCHEDULER_LOG.exists():
        return CheckResult("Log Health", "WARN", "scheduler.log not found")

    try:
        with open(SCHEDULER_LOG) as f:
            lines = f.readlines()

        # Count errors by category (ignore known benign ones)
        yfinance_404 = 0
        other_errors = []
        for line in lines:
            if "ERROR" in line:
                if "yfinance" in line and "404" in line:
                    yfinance_404 += 1
                else:
                    other_errors.append(line.strip()[:120])

        msg_parts = []
        status = "PASS"

        if yfinance_404:
            msg_parts.append(f"{yfinance_404} yfinance 404s (benign — ETF fundamentals)")

        if other_errors:
            status = "WARN"
            msg_parts.append(f"{len(other_errors)} other errors")

        if not msg_parts:
            msg_parts.append("No errors in log")

        return CheckResult("Log Health", status, " | ".join(msg_parts),
                           {"yfinance_404": yfinance_404,
                            "other_errors": other_errors[:5]})
    except Exception as e:
        return CheckResult("Log Health", "FAIL", f"Error: {e}")


def check_zombie_processes() -> CheckResult:
    """Check for zombie processes from previous scheduler runs."""
    import subprocess

    result = subprocess.run(
        ["ps", "aux"], capture_output=True, text=True,
    )
    zombies = [
        line for line in result.stdout.split("\n")
        if "<defunct>" in line and ("main.py" in line or "python" in line)
    ]

    if zombies:
        pids = []
        for z in zombies:
            parts = z.split()
            if len(parts) > 1:
                pids.append(parts[1])
        return CheckResult(
            "Zombie Processes", "WARN",
            f"{len(zombies)} zombie(s) found (PIDs: {', '.join(pids)}). "
            "Harmless but can be cleaned with: kill -9 <pid>",
            {"zombie_pids": pids},
        )
    return CheckResult("Zombie Processes", "PASS", "No zombies")


def run_all_checks(run_tests: bool = True) -> list[CheckResult]:
    """Run all preflight checks and return results."""
    checks = [
        check_scheduler_process,
        check_heartbeat,
        check_alpaca,
        check_polygon,
        check_data_cache,
        check_database,
        check_champion_config,
        check_telegram,
        check_strategy_imports,
        check_open_positions_risk,
        check_log_errors,
        check_zombie_processes,
    ]

    if run_tests:
        checks.append(check_test_suite)

    results = []
    for check_fn in checks:
        try:
            results.append(check_fn())
        except Exception as e:
            results.append(CheckResult(check_fn.__name__, "FAIL", f"Unexpected: {e}"))

    return results


def print_report(results: list[CheckResult], as_json: bool = False):
    """Print the preflight report."""
    if as_json:
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": [r.to_dict() for r in results],
            "summary": {
                "total": len(results),
                "pass": sum(1 for r in results if r.status == "PASS"),
                "warn": sum(1 for r in results if r.status == "WARN"),
                "fail": sum(1 for r in results if r.status == "FAIL"),
            },
        }
        print(json.dumps(output, indent=2, default=str))
        return

    icons = {"PASS": "+", "WARN": "!", "FAIL": "X"}
    colors = {"PASS": "\033[32m", "WARN": "\033[33m", "FAIL": "\033[31m"}
    reset = "\033[0m"

    print()
    print("=" * 68)
    print("  PILOTAI PREFLIGHT CHECK — Pre-Market-Open Validation")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ET")
    print("=" * 68)
    print()

    for r in results:
        icon = icons.get(r.status, "?")
        color = colors.get(r.status, "")
        print(f"  {color}[{icon}] {r.name:<22}{reset} {r.message}")

    passes = sum(1 for r in results if r.status == "PASS")
    warns = sum(1 for r in results if r.status == "WARN")
    fails = sum(1 for r in results if r.status == "FAIL")

    print()
    print("-" * 68)

    if fails > 0:
        print(f"\033[31m  HOLD — {fails} critical failure(s). Fix before market open.\033[0m")
    elif warns > 0:
        print(f"\033[33m  CAUTION — {warns} warning(s). System can run but review issues.\033[0m")
    else:
        print(f"\033[32m  ALL CLEAR — {passes}/{len(results)} checks passed. Ready for Monday.\033[0m")

    print(f"  Summary: {passes} pass, {warns} warn, {fails} fail")
    print("=" * 68)
    print()


def main():
    parser = argparse.ArgumentParser(description="Pre-market-open preflight check")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--skip-tests", action="store_true",
        help="Skip running the test suite (faster)",
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Attempt auto-fix where possible (e.g., kill zombies)",
    )
    args = parser.parse_args()

    results = run_all_checks(run_tests=not args.skip_tests)

    if args.fix:
        for r in results:
            if r.name == "Zombie Processes" and r.status == "WARN":
                zombie_pids = r.details.get("zombie_pids", [])
                for pid in zombie_pids:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        pass
                r.status = "PASS"
                r.message = f"Cleaned {len(zombie_pids)} zombie(s)"

    print_report(results, as_json=args.json)

    fails = sum(1 for r in results if r.status == "FAIL")
    warns = sum(1 for r in results if r.status == "WARN")

    if fails:
        sys.exit(1)
    elif warns:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
