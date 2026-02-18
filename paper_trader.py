"""
Paper Trading Engine
Automatically takes signals from the scanner and tracks simulated trades.
Monitors open positions and closes at profit target, stop loss, or expiration.
"""

import logging
import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
from shared.constants import MAX_CONTRACTS_PER_TRADE, MANAGEMENT_DTE_THRESHOLD, DATA_DIR as _DATA_DIR
from shared.io_utils import atomic_json_write
from shared.database import init_db, upsert_trade, get_trades, close_trade as db_close_trade

logger = logging.getLogger(__name__)

DATA_DIR = Path(_DATA_DIR)
TRADES_FILE = DATA_DIR / "trades.json"
PAPER_LOG = DATA_DIR / "paper_trades.json"

MAX_DRAWDOWN_PCT = 0.20  # 20% portfolio-level max drawdown kill switch
EXTRINSIC_DECAY_RATE = 1.2  # Accelerating time-decay multiplier for OTM spreads
BASE_DECAY_FACTOR = 0.3  # Fraction of extrinsic value remaining when ITM


class PaperTrader:
    """Simulated trading engine that auto-executes scanner signals."""

    def __init__(self, config: Dict):
        self.config = config
        self.risk = config.get("risk", {})
        self.account_size = self.risk.get("account_size", 100000)
        self.max_risk_per_trade = self.risk.get("max_risk_per_trade", 2.0) / 100
        self.max_positions = self.risk.get("max_positions", 5)
        self.profit_target_pct = self.risk.get("profit_target", 50) / 100
        self.stop_loss_mult = self.risk.get("stop_loss_multiplier", 2.5)

        # Lock to protect self.trades mutations from concurrent threads
        self._trades_lock = threading.Lock()

        # Initialize Alpaca provider if configured
        self.alpaca = None
        alpaca_cfg = config.get("alpaca", {})
        if alpaca_cfg.get("enabled", False):
            try:
                from strategy.alpaca_provider import AlpacaProvider
                self.alpaca = AlpacaProvider(
                    api_key=alpaca_cfg["api_key"],
                    api_secret=alpaca_cfg["api_secret"],
                    paper=alpaca_cfg.get("paper", True),
                )
                logger.info("Alpaca paper trading ENABLED")
            except Exception as e:
                logger.warning(f"Alpaca init failed, falling back to DB: {e}")
                self.alpaca = None

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        init_db()

        # Load trades from SQLite
        self.trades = self._load_trades()
        self._rebuild_cached_lists()
        logger.info(f"PaperTrader initialized | Balance: ${self.account_size:,.0f} | "
                     f"Open: {len(self.open_trades)} | Closed: {len(self.closed_trades)} | "
                     f"Alpaca: {'ON' if self.alpaca else 'OFF'}")

    def _load_trades(self) -> Dict:
        """Load trades from SQLite database.

        If the database is missing, empty, or corrupted, returns a default
        empty structure so that the PaperTrader can still start cleanly
        (EH-PY-08).
        """
        try:
            db_trades = get_trades(source="scanner")
            trades_list = list(db_trades)
        except Exception as e:
            logger.warning(
                f"Could not load trades from database: {e}. "
                "Starting with empty trade list."
            )
            trades_list = []

        # Compute stats from trade data
        closed = [t for t in trades_list if t.get("status", "") != "open"]
        winners = [t for t in closed if (t.get("pnl") or 0) > 0]
        losers = [t for t in closed if (t.get("pnl") or 0) <= 0]
        total_pnl = sum(t.get("pnl") or 0 for t in closed)

        return {
            "account_size": self.account_size,
            "starting_balance": self.account_size,
            "current_balance": self.account_size + total_pnl,
            "trades": trades_list,
            "stats": {
                "total_trades": len(trades_list),
                "winners": len(winners),
                "losers": len(losers),
                "total_pnl": round(total_pnl, 2),
                "win_rate": round(len(winners) / len(closed) * 100, 1) if closed else 0,
                "best_trade": max((t.get("pnl") or 0 for t in closed), default=0),
                "worst_trade": min((t.get("pnl") or 0 for t in closed), default=0),
                "avg_winner": round(sum(t.get("pnl") or 0 for t in winners) / len(winners), 2) if winners else 0,
                "avg_loser": round(sum(t.get("pnl") or 0 for t in losers) / len(losers), 2) if losers else 0,
                "max_drawdown": 0,
                "peak_balance": self.account_size + total_pnl,
            },
        }

    def _rebuild_cached_lists(self):
        """Build the cached open/closed lists from the trades list."""
        self._open_trades = [t for t in self.trades["trades"] if t.get("status") == "open"]
        self._closed_trades = [t for t in self.trades["trades"] if t.get("status") != "open"]

    def _save_trades(self):
        """Persist all trades to SQLite and export dashboard JSON."""
        with self._trades_lock:
            for trade in self.trades["trades"]:
                upsert_trade(trade, source="scanner")
        self._export_for_dashboard()

    def _export_for_dashboard(self):
        """Write trades in format the web dashboard expects (deprecated — use SQLite)."""
        dashboard_data = {
            "balance": self.trades["current_balance"],
            "starting_balance": self.trades["starting_balance"],
            "total_pnl": self.trades["stats"]["total_pnl"],
            "win_rate": self.trades["stats"]["win_rate"],
            "open_positions": self._open_trades,
            "closed_positions": self._closed_trades,
            "stats": self.trades["stats"],
            "updated_at": datetime.now().isoformat(),
        }
        atomic_json_write(TRADES_FILE, dashboard_data)

    # Keep a thin static wrapper so existing callers (e.g. tests) that
    # reference PaperTrader._atomic_json_write still work.
    _atomic_json_write = staticmethod(atomic_json_write)

    @property
    def open_trades(self) -> List[Dict]:
        return self._open_trades

    @property
    def closed_trades(self) -> List[Dict]:
        return self._closed_trades

    def execute_signals(self, opportunities: List[Dict]) -> List[Dict]:
        """
        Take scanner output and open paper trades for the best signals.

        Args:
            opportunities: List of opportunity dicts from the scanner

        Returns:
            List of newly opened trades
        """
        if not opportunities:
            logger.info("No opportunities to trade")
            return []

        open_count = len(self.open_trades)
        available_slots = self.max_positions - open_count

        if available_slots <= 0:
            logger.info(f"Max positions reached ({self.max_positions}), skipping new entries")
            return []

        # Sort by score, take best available
        sorted_opps = sorted(opportunities, key=lambda x: x.get("score", 0), reverse=True)

        # Filter out exact duplicate positions (same ticker + same short strike + same expiration)
        open_keys = {
            (t["ticker"], t.get("short_strike"), t.get("expiration"))
            for t in self.open_trades
        }
        eligible = [
            o for o in sorted_opps
            if (o["ticker"], o.get("short_strike"), o.get("expiration")) not in open_keys
        ]

        # Also limit max 3 positions per ticker to avoid concentration
        ticker_counts = {}
        for t in self.open_trades:
            ticker_counts[t["ticker"]] = ticker_counts.get(t["ticker"], 0) + 1
        eligible = [
            o for o in eligible
            if ticker_counts.get(o["ticker"], 0) < 3
        ]

        new_trades = []
        for opp in eligible[:available_slots]:
            trade = self._open_trade(opp)
            if trade:
                new_trades.append(trade)

        if new_trades:
            self._save_trades()
            logger.info(f"Opened {len(new_trades)} new paper trades")

        return new_trades

    def _open_trade(self, opp: Dict) -> Optional[Dict]:
        """Open a paper trade from an opportunity."""
        with self._trades_lock:
            current_balance = self.trades["current_balance"]
            starting_balance = self.trades["starting_balance"]

            # EH-TRADE-01: Refuse to open trades when balance is non-positive
            if current_balance <= 0:
                logger.warning(
                    f"TRADE REFUSED: current balance is ${current_balance:,.2f}. "
                    "Cannot open new trades with zero or negative balance."
                )
                return None

            # EH-TRADE-03: Portfolio-level max drawdown kill switch
            drawdown_pct = (starting_balance - current_balance) / starting_balance if starting_balance > 0 else 0
            if drawdown_pct >= MAX_DRAWDOWN_PCT:
                logger.critical(
                    f"TRADE REFUSED — MAX DRAWDOWN KILL SWITCH ACTIVE: "
                    f"drawdown {drawdown_pct:.1%} >= {MAX_DRAWDOWN_PCT:.0%} threshold. "
                    f"Starting: ${starting_balance:,.2f}, Current: ${current_balance:,.2f}. "
                    f"All new trades are blocked until manual review."
                )
                return None

            credit = opp.get("credit", 0)
            max_loss = opp.get("max_loss", 0)

            if credit <= 0 or max_loss <= 0:
                return None

            # EH-TRADE-02: Account for existing open risk exposure in position sizing
            open_risk = sum(t.get("total_max_loss", 0) for t in self.open_trades)
            available_capital = current_balance - open_risk
            if available_capital <= 0:
                logger.warning(
                    f"TRADE REFUSED: insufficient available capital. "
                    f"Balance: ${current_balance:,.2f}, Open risk: ${open_risk:,.2f}, "
                    f"Available: ${available_capital:,.2f}"
                )
                return None

            # Position sizing: max risk per trade (based on available capital, not total balance)
            max_risk_dollars = available_capital * self.max_risk_per_trade
            max_contracts = max(1, int(max_risk_dollars / (max_loss * 100)))
            contracts = min(max_contracts, MAX_CONTRACTS_PER_TRADE)

            # EH-TRADE-07: UUID-based trade IDs to avoid collisions on restart
            trade_id = f"PT-{uuid.uuid4().hex[:12]}"

            trade = {
                "id": trade_id,
                "status": "open",
                "ticker": opp["ticker"],
                "type": opp["type"],
                "short_strike": opp["short_strike"],
                "long_strike": opp["long_strike"],
                "expiration": str(opp.get("expiration", "")),
                "dte_at_entry": opp.get("dte", 0),
                "contracts": contracts,
                "credit_per_spread": credit,
                "credit": credit,
                "total_credit": round(credit * contracts * 100, 2),
                "max_loss_per_spread": max_loss,
                "total_max_loss": round(max_loss * contracts * 100, 2),
                "profit_target": round(credit * self.profit_target_pct * contracts * 100, 2),
                "stop_loss_amount": round(credit * self.stop_loss_mult * contracts * 100, 2),
                "entry_price": opp.get("current_price", 0),
                "entry_date": datetime.now().isoformat(),
                "entry_score": opp.get("score", 0),
                "entry_pop": opp.get("pop", 0),
                "entry_delta": opp.get("short_delta", 0),
                "current_pnl": 0,
                "exit_date": None,
                "exit_reason": None,
                "exit_pnl": None,
            }

            # Submit to Alpaca - ONLY create DB entries for real Alpaca trades
            if not self.alpaca:
                logger.info(
                    f"SKIPPED (Alpaca not configured): {trade['type']} on {trade['ticker']} | "
                    f"{trade['contracts']}x ${trade['short_strike']}/{trade['long_strike']} | "
                    f"Would have been: Credit ${trade['total_credit']:.0f}, Max Loss ${trade['total_max_loss']:.0f}"
                )
                return None

            try:
                alpaca_result = self.alpaca.submit_credit_spread(
                    ticker=trade["ticker"],
                    short_strike=trade["short_strike"],
                    long_strike=trade["long_strike"],
                    expiration=trade["expiration"],
                    spread_type=trade["type"],
                    contracts=trade["contracts"],
                    limit_price=trade["credit_per_spread"],
                )
                trade["alpaca_order_id"] = alpaca_result.get("order_id")
                trade["alpaca_status"] = alpaca_result.get("status")
                
                if alpaca_result["status"] == "error":
                    logger.warning(f"Alpaca order failed: {alpaca_result['message']}. NOT recording in DB.")
                    return None
                    
                logger.info(f"Alpaca order submitted: {alpaca_result['order_id']}")
            except Exception as e:
                logger.warning(f"Alpaca submission failed: {e}. NOT recording in DB.")
                return None

            # Only add to tracking if Alpaca order succeeded
            self.trades["trades"].append(trade)
            self._open_trades.append(trade)
            self.trades["stats"]["total_trades"] += 1

            # Persist to SQLite immediately
            upsert_trade(trade, source="scanner")

            logger.info(
                f"PAPER TRADE OPENED: {trade['type']} on {trade['ticker']} | "
                f"{trade['contracts']}x ${trade['short_strike']}/{trade['long_strike']} | "
                f"Credit: ${trade['total_credit']:.0f} | Max Loss: ${trade['total_max_loss']:.0f}"
            )

            return trade

    def check_positions(self, current_prices: Dict[str, float]) -> List[Dict]:
        """
        Check open positions against current prices and close if needed.

        Args:
            current_prices: Dict of {ticker: current_price}

        Returns:
            List of closed trades
        """
        closed = []
        now = datetime.now()

        for trade in self.open_trades:
            ticker = trade["ticker"]
            current_price = float(current_prices.get(ticker, trade.get("entry_price", 0)))

            # Parse expiration
            exp_str = str(trade.get("expiration", ""))
            exp_str = exp_str.split(" ")[0] if " " in exp_str else exp_str
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            except ValueError:
                try:
                    exp_date = datetime.fromisoformat(exp_str)
                except ValueError:
                    logger.error(f"Could not parse expiration '{trade.get('expiration')}' for trade {trade.get('id')}, defaulting to +30d", exc_info=True)
                    exp_date = now + timedelta(days=30)

            dte = (exp_date - now).days

            # Simulate current spread value based on price movement and time decay
            pnl, close_reason = self._evaluate_position(trade, current_price, dte)
            trade["current_pnl"] = pnl

            if close_reason:
                self._close_trade(trade, pnl, close_reason)
                closed.append(trade)

        if closed:
            self._save_trades()

        return closed

    def _evaluate_position(self, trade: Dict, current_price: float, dte: int):
        """
        Evaluate a position and determine if it should be closed.
        Returns (pnl, close_reason) — close_reason is None if still open.
        """
        credit = trade.get("total_credit", 0)
        contracts = trade.get("contracts", 1)
        short_strike = trade.get("short_strike", 0)
        long_strike = trade.get("long_strike", 0)
        spread_type = trade.get("type", "")

        # Determine if in danger
        if "call" in spread_type.lower():
            # Bear call spread: bad if price goes above short strike
            intrinsic = max(0, current_price - short_strike)
        else:
            # Bull put spread: bad if price goes below short strike
            intrinsic = max(0, short_strike - current_price)

        # Simplified P&L model:
        # If OTM and time has passed, spread value decays toward 0 (we profit)
        # If ITM, spread value approaches intrinsic
        entry_dte = trade.get("dte_at_entry", 35)
        time_passed_pct = max(0, 1 - (dte / max(entry_dte, 1)))

        if intrinsic == 0:
            # OTM — time decay is our friend
            decay_factor = max(0, 1 - time_passed_pct * EXTRINSIC_DECAY_RATE)  # Accelerating decay
            current_value = credit * decay_factor
            pnl = round(credit - current_value, 2)
        else:
            # ITM — losing money
            current_spread_value = min(intrinsic * contracts * 100, trade.get("total_max_loss", 0))
            remaining_extrinsic = credit * max(0, 1 - time_passed_pct) * BASE_DECAY_FACTOR
            pnl = round(-(current_spread_value - remaining_extrinsic), 2)

        # Check exit conditions
        close_reason = None

        # 1. Profit target hit (50% of credit)
        if pnl >= trade.get("profit_target", float('inf')):
            close_reason = "profit_target"

        # 2. Stop loss hit
        elif pnl <= -trade.get("stop_loss_amount", float('inf')):
            close_reason = "stop_loss"

        # 3. Expiration (or close at 1 DTE)
        elif dte <= 1:
            close_reason = "expiration"

        # 4. Manage at DTE threshold — close if profitable
        elif dte <= MANAGEMENT_DTE_THRESHOLD and pnl > 0:
            close_reason = "management_dte"

        return pnl, close_reason

    def _close_trade(self, trade: Dict, pnl: float, reason: str):
        """Close a paper trade."""
        # EH-TRADE-04: If Alpaca is enabled, attempt close and abort local
        # state transition on failure so local and broker state stay in sync.
        if self.alpaca and trade.get("alpaca_order_id"):
            try:
                self.alpaca.close_spread(
                    ticker=trade["ticker"],
                    short_strike=trade["short_strike"],
                    long_strike=trade["long_strike"],
                    expiration=trade["expiration"],
                    spread_type=trade["type"],
                    contracts=trade["contracts"],
                )
                logger.info(f"Alpaca close order submitted for {trade['ticker']}")
            except Exception as e:
                logger.error(
                    f"Alpaca close failed for {trade['ticker']}: {e}. "
                    "Local trade state will NOT be updated to closed.",
                    exc_info=True,
                )
                trade["alpaca_sync_error"] = str(e)
                return  # Do NOT proceed with local state transition

        with self._trades_lock:
            trade["status"] = "closed"
            trade["exit_date"] = datetime.now().isoformat()
            trade["exit_reason"] = reason
            trade["exit_pnl"] = pnl
            trade["pnl"] = pnl

            # Move from open to closed cached lists
            if trade in self._open_trades:
                self._open_trades.remove(trade)
            self._closed_trades.append(trade)

            # Update balance
            self.trades["current_balance"] = round(self.trades["current_balance"] + pnl, 2)

            # Update stats
            stats = self.trades["stats"]
            if pnl > 0:
                stats["winners"] += 1
            else:
                stats["losers"] += 1

            stats["total_pnl"] = round(stats["total_pnl"] + pnl, 2)

            total_closed = stats["winners"] + stats["losers"]
            stats["win_rate"] = round(stats["winners"] / total_closed * 100, 1) if total_closed > 0 else 0

            stats["best_trade"] = max(stats["best_trade"], pnl)
            stats["worst_trade"] = min(stats["worst_trade"], pnl)

            winners = [t.get("exit_pnl") or t.get("pnl") or 0 for t in self.closed_trades if (t.get("exit_pnl") or t.get("pnl") or 0) > 0]
            losers_pnl = [t.get("exit_pnl") or t.get("pnl") or 0 for t in self.closed_trades if (t.get("exit_pnl") or t.get("pnl") or 0) < 0]
            stats["avg_winner"] = round(sum(winners) / len(winners), 2) if winners else 0
            stats["avg_loser"] = round(sum(losers_pnl) / len(losers_pnl), 2) if losers_pnl else 0

            # Track peak and drawdown
            if self.trades["current_balance"] > stats["peak_balance"]:
                stats["peak_balance"] = self.trades["current_balance"]
            drawdown = stats["peak_balance"] - self.trades["current_balance"]
            stats["max_drawdown"] = max(stats["max_drawdown"], drawdown)

        # Persist to SQLite
        db_close_trade(str(trade.get("id", "")), pnl, reason)

        logger.info(
            f"PAPER TRADE CLOSED: {trade['ticker']} {trade.get('type', '')} | "
            f"P&L: ${pnl:+.2f} | Reason: {reason} | "
            f"Balance: ${self.trades['current_balance']:,.2f}"
        )

    def sync_alpaca_orders(self):
        """Sync order statuses from Alpaca and update local DB."""
        if not self.alpaca:
            return

        for trade in self.open_trades:
            order_id = trade.get("alpaca_order_id")
            if not order_id or trade.get("alpaca_status") == "filled":
                continue  # Skip non-Alpaca or already-filled trades

            try:
                status = self.alpaca.get_order_status(order_id)
                old_status = trade.get("alpaca_status")
                new_status = status["status"]

                if old_status != new_status:
                    trade["alpaca_status"] = new_status
                    trade["alpaca_filled_price"] = status.get("filled_avg_price")
                    trade["alpaca_filled_at"] = status.get("filled_at")
                    upsert_trade(trade, source="scanner")
                    logger.info(f"Alpaca sync: {trade['ticker']} order {order_id} → {new_status}")

                    # If order was rejected/cancelled, mark trade for review
                    if new_status in ("cancelled", "expired", "rejected"):
                        trade["alpaca_sync_error"] = f"Order {new_status}"

            except Exception as e:
                logger.warning(f"Alpaca sync failed for {trade['ticker']}: {e}")

    def get_summary(self) -> Dict:
        """Get paper trading summary."""
        stats = self.trades["stats"]
        return {
            "balance": self.trades["current_balance"],
            "starting_balance": self.trades["starting_balance"],
            "total_pnl": stats["total_pnl"],
            "total_trades": stats["total_trades"],
            "open_positions": len(self.open_trades),
            "closed_trades": stats["winners"] + stats["losers"],
            "win_rate": stats["win_rate"],
            "winners": stats["winners"],
            "losers": stats["losers"],
            "best_trade": stats["best_trade"],
            "worst_trade": stats["worst_trade"],
            "avg_winner": stats["avg_winner"],
            "avg_loser": stats["avg_loser"],
            "max_drawdown": stats["max_drawdown"],
            "open_trades": self.open_trades,
        }

    def print_summary(self):
        """Print paper trading summary to console."""
        s = self.get_summary()
        pnl_color = "\033[32m" if s["total_pnl"] >= 0 else "\033[31m"
        reset = "\033[0m"

        print("\n" + "=" * 60)
        print("  PAPER TRADING SUMMARY")
        print("=" * 60)
        print(f"  Balance:        ${s['balance']:>12,.2f}")
        print(f"  Total P&L:      {pnl_color}${s['total_pnl']:>+12,.2f}{reset}")
        print(f"  Total Trades:   {s['total_trades']:>12}")
        print(f"  Open Positions: {s['open_positions']:>12}")
        print(f"  Win Rate:       {s['win_rate']:>11.1f}%")
        print(f"  Winners/Losers: {s['winners']:>5} / {s['losers']}")
        print(f"  Best Trade:     ${s['best_trade']:>+12,.2f}")
        print(f"  Worst Trade:    ${s['worst_trade']:>+12,.2f}")
        print(f"  Max Drawdown:   ${s['max_drawdown']:>12,.2f}")
        print("=" * 60)

        if s["open_trades"]:
            print("\n  OPEN POSITIONS:")
            for t in s["open_trades"]:
                print(f"    {t['ticker']} {t.get('type', '')} "
                      f"${t.get('short_strike', 0)}/{t.get('long_strike', 0)} "
                      f"x{t.get('contracts', 1)} | Credit: ${t.get('total_credit', 0):.0f} | "
                      f"P&L: ${t.get('current_pnl', 0):+.2f}")
        print()
