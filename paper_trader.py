"""
Paper Trading Engine
Automatically takes signals from the scanner and tracks simulated trades.
Monitors open positions and closes at profit target, stop loss, or expiration.
"""

import json
import logging
import os
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from shared.constants import MAX_CONTRACTS_PER_TRADE, MANAGEMENT_DTE_THRESHOLD, DATA_DIR as _DATA_DIR
from shared.database import init_db, upsert_trade, get_trades, close_trade as db_close_trade
from shared.metrics import metrics

logger = logging.getLogger(__name__)

DATA_DIR = Path(_DATA_DIR)
PAPER_LOG = DATA_DIR / "paper_trades.json"  # legacy path, kept for test compatibility
KILL_SWITCH_FILE = DATA_DIR / "kill_switch.json"

MAX_DRAWDOWN_PCT = 0.20  # 20% portfolio-level max drawdown kill switch
EXTRINSIC_DECAY_RATE = 1.2  # Accelerating time-decay multiplier for OTM spreads
BASE_DECAY_FACTOR = 0.3  # Fraction of extrinsic value remaining when ITM

# Stale-order reconciliation: orders unconfirmed for this long are treated as dead
_STALE_ORDER_HOURS = 1
_TERMINAL_ALPACA_STATES = frozenset({
    "cancelled", "expired", "rejected", "replaced", "done_for_day",
})

# Anti-suicide-loop circuit breakers
CONSECUTIVE_LOSS_BLOCK_THRESHOLD = 2   # Block after N consecutive losses on same ticker+direction
CONSECUTIVE_LOSS_LOOKBACK_HOURS = 1    # Only count losses within this window
TICKER_DIRECTION_COOLDOWN_HOURS = 4    # Block ticker+direction for this long after consecutive losses
STRIKE_COOLDOWN_HOURS = 2              # Block exact same strikes after stop-out


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

        # Anti-suicide-loop: track recent losses per (ticker, direction)
        # Key: (ticker, direction_str), Value: list of {"exit_time": datetime, "pnl": float, "strikes": (short, long)}
        self._recent_losses: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
        # Key: (ticker, direction, short_strike, long_strike), Value: datetime of last stop-out
        self._strike_cooldowns: Dict[Tuple, datetime] = {}

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

        # Startup reconciliation: resolve any pending_open rows left by a previous
        # crash before loading in-memory state (so stats are clean from the start).
        reconcile_summary = self._startup_reconcile()

        # Load trades from SQLite (pending_open / failed_open are excluded)
        self.trades = self._load_trades()
        self._rebuild_cached_lists()
        self._seed_loss_tracker()

        logger.info(
            f"PaperTrader initialized | Balance: ${self.account_size:,.0f} | "
            f"Open: {len(self.open_trades)} | Closed: {len(self.closed_trades)} | "
            f"Alpaca: {'ON' if self.alpaca else 'OFF'}"
            + (f" | Reconciled: {reconcile_summary}" if reconcile_summary else "")
        )

    @staticmethod
    def _is_kill_switch_active() -> bool:
        """Check if the kill switch file exists (trading halted externally)."""
        return KILL_SWITCH_FILE.exists()

    def _load_trades(self) -> Dict:
        """Load trades from SQLite database.

        If the database is missing, empty, or corrupted, returns a default
        empty structure so that the PaperTrader can still start cleanly
        (EH-PY-08).
        """
        try:
            db_trades = get_trades(source="scanner")
            # Exclude transient write-ahead states from the live trade list.
            # pending_open trades are resolved by reconcile_positions() on startup.
            # failed_open trades are recorded for audit but should not affect stats.
            trades_list = [
                t for t in db_trades
                if t.get("status") not in ("pending_open", "failed_open")
            ]
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

        # Compute proper peak balance by replaying closed trades chronologically
        peak_balance = self.account_size
        running_balance = self.account_size
        sorted_closed = sorted(closed, key=lambda t: t.get("exit_date") or t.get("entry_date") or "")
        for t in sorted_closed:
            running_balance += (t.get("pnl") or 0)
            if running_balance > peak_balance:
                peak_balance = running_balance

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
                "peak_balance": peak_balance,
            },
        }

    def _rebuild_cached_lists(self):
        """Build the cached open/closed lists from the trades list."""
        self._open_trades = [t for t in self.trades["trades"] if t.get("status") == "open"]
        self._closed_trades = [t for t in self.trades["trades"] if t.get("status") != "open"]

    def _seed_loss_tracker(self):
        """Pre-populate loss tracker from recent closed trades so circuit breakers work across restarts."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=TICKER_DIRECTION_COOLDOWN_HOURS)
        for trade in self._closed_trades:
            if (trade.get("pnl") or 0) >= 0:
                continue
            exit_str = trade.get("exit_date")
            if not exit_str:
                continue
            try:
                exit_time = datetime.fromisoformat(exit_str)
                if exit_time.tzinfo is None:
                    exit_time = exit_time.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if exit_time < cutoff:
                continue
            direction = self._trade_direction(trade)
            key = (trade["ticker"], direction)
            self._recent_losses[key].append({
                "exit_time": exit_time,
                "pnl": trade.get("pnl", 0),
                "strikes": (trade.get("short_strike"), trade.get("long_strike")),
            })
            if trade.get("exit_reason") == "stop_loss":
                strike_key = (trade["ticker"], direction,
                              trade.get("short_strike"), trade.get("long_strike"))
                self._strike_cooldowns[strike_key] = exit_time

    @staticmethod
    def _trade_direction(trade: Dict) -> str:
        """Extract direction (bullish/bearish/neutral) from trade type."""
        t = (trade.get("type") or trade.get("strategy_type") or "").lower()
        if "condor" in t:
            return "neutral"
        if "put" in t:
            return "bullish"
        if "call" in t:
            return "bearish"
        return "unknown"

    def _check_loss_circuit_breaker(self, ticker: str, direction: str) -> Optional[str]:
        """Check if ticker+direction is blocked due to consecutive losses.

        Returns a reason string if blocked, None if clear.
        """
        now = datetime.now(timezone.utc)
        key = (ticker, direction)
        losses = self._recent_losses.get(key, [])

        # Prune entries older than the cooldown window
        lookback_cutoff = now - timedelta(hours=CONSECUTIVE_LOSS_LOOKBACK_HOURS)
        recent = [l for l in losses if l["exit_time"] >= lookback_cutoff]

        if len(recent) >= CONSECUTIVE_LOSS_BLOCK_THRESHOLD:
            latest_loss = max(l["exit_time"] for l in recent)
            block_until = latest_loss + timedelta(hours=TICKER_DIRECTION_COOLDOWN_HOURS)
            if now < block_until:
                remaining = block_until - now
                return (
                    f"{len(recent)} consecutive losses on {ticker} {direction} "
                    f"in the last {CONSECUTIVE_LOSS_LOOKBACK_HOURS}h. "
                    f"Blocked for {remaining.total_seconds()/3600:.1f}h more."
                )
        return None

    def _check_strike_cooldown(self, ticker: str, direction: str,
                                short_strike: float, long_strike: float) -> Optional[str]:
        """Check if exact strikes are on cooldown after a stop-out.

        Returns a reason string if blocked, None if clear.
        """
        now = datetime.now(timezone.utc)
        strike_key = (ticker, direction, short_strike, long_strike)
        last_stopout = self._strike_cooldowns.get(strike_key)
        if last_stopout is None:
            return None
        cooldown_until = last_stopout + timedelta(hours=STRIKE_COOLDOWN_HOURS)
        if now < cooldown_until:
            remaining = cooldown_until - now
            return (
                f"Same strikes {short_strike}/{long_strike} on {ticker} {direction} "
                f"stopped out recently. Cooldown for {remaining.total_seconds()/3600:.1f}h more."
            )
        return None

    def _record_loss(self, trade: Dict):
        """Record a losing trade for circuit breaker tracking."""
        direction = self._trade_direction(trade)
        key = (trade["ticker"], direction)
        exit_time = datetime.now(timezone.utc)
        self._recent_losses[key].append({
            "exit_time": exit_time,
            "pnl": trade.get("pnl", 0),
            "strikes": (trade.get("short_strike"), trade.get("long_strike")),
        })
        # Keep only last 10 entries per key to avoid unbounded growth
        self._recent_losses[key] = self._recent_losses[key][-10:]

        if trade.get("exit_reason") == "stop_loss":
            strike_key = (trade["ticker"], direction,
                          trade.get("short_strike"), trade.get("long_strike"))
            self._strike_cooldowns[strike_key] = exit_time

    def _consecutive_loss_count(self, ticker: str, direction: str) -> int:
        """Count consecutive losses for a ticker+direction (most recent first)."""
        key = (ticker, direction)
        losses = self._recent_losses.get(key, [])
        return len(losses)

    def _save_trades(self):
        """Persist all trades to SQLite."""
        with self._trades_lock:
            for trade in self.trades["trades"]:
                upsert_trade(trade, source="scanner")

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

        # Only trade opportunities that meet the alert-quality threshold (score >= 28)
        # Lowered to generate more trading activity (Carlos directive Feb 21)
        sorted_opps = [o for o in opportunities if o.get("score", 0) >= 28]
        sorted_opps.sort(key=lambda x: x.get("score", 0), reverse=True)

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
            # Kill switch: halt all new trades when externally activated
            if self._is_kill_switch_active():
                logger.warning("TRADE REFUSED: kill switch is active — trading halted")
                return None

            current_balance = self.trades["current_balance"]
            peak_balance = self.trades["stats"]["peak_balance"]

            # EH-TRADE-01: Refuse to open trades when balance is non-positive
            if current_balance <= 0:
                logger.warning(
                    f"TRADE REFUSED: current balance is ${current_balance:,.2f}. "
                    "Cannot open new trades with zero or negative balance."
                )
                return None

            # EH-TRADE-03: Portfolio-level max drawdown kill switch (peak-based)
            drawdown_pct = (peak_balance - current_balance) / peak_balance if peak_balance > 0 else 0
            if drawdown_pct >= MAX_DRAWDOWN_PCT:
                logger.critical(
                    f"TRADE REFUSED — MAX DRAWDOWN KILL SWITCH ACTIVE: "
                    f"drawdown {drawdown_pct:.1%} >= {MAX_DRAWDOWN_PCT:.0%} threshold. "
                    f"Peak: ${peak_balance:,.2f}, Current: ${current_balance:,.2f}. "
                    f"All new trades are blocked until manual review."
                )
                return None

            # Anti-suicide-loop: check circuit breakers
            ticker = opp.get("ticker", "")
            opp_type = (opp.get("type") or "").lower()
            if "condor" in opp_type:
                direction = "neutral"
            elif "put" in opp_type:
                direction = "bullish"
            else:
                direction = "bearish"

            # Check 1: Consecutive losses on same ticker+direction
            cb_reason = self._check_loss_circuit_breaker(ticker, direction)
            if cb_reason:
                logger.warning(f"TRADE BLOCKED (loss circuit breaker): {cb_reason}")
                return None

            # Check 2: Same strikes just stopped out
            sc_reason = self._check_strike_cooldown(
                ticker, direction,
                opp.get("short_strike", 0), opp.get("long_strike", 0),
            )
            if sc_reason:
                logger.warning(f"TRADE BLOCKED (strike cooldown): {sc_reason}")
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

            # Deterministic client_order_id: survives process restarts and lets the
            # reconciler match DB records back to Alpaca orders unambiguously.
            spread_type_slug = (opp.get("type") or "spread").replace("_", "-")
            client_order_id = f"Pilot-{ticker}-{spread_type_slug}-{trade_id[3:]}"

            trade = {
                "id": trade_id,
                "status": "pending_open",  # write-ahead — promoted to "open" after Alpaca confirms
                "alpaca_client_order_id": client_order_id if self.alpaca else None,
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
                "entry_date": datetime.now(timezone.utc).isoformat(),
                "entry_score": opp.get("score", 0),
                "entry_pop": opp.get("pop", 0),
                "entry_delta": opp.get("short_delta", 0),
                "current_pnl": 0,
                "exit_date": None,
                "exit_reason": None,
                "exit_pnl": None,
                "consecutive_loss_count": self._consecutive_loss_count(ticker, direction),
            }

            # Store iron condor call-side fields (go into metadata JSON column)
            if "condor" in opp_type:
                trade["call_short_strike"] = opp.get("call_short_strike")
                trade["call_long_strike"] = opp.get("call_long_strike")
                trade["put_credit"] = opp.get("put_credit")
                trade["call_credit"] = opp.get("call_credit")

            # Write-ahead: persist with status=pending_open BEFORE calling Alpaca.
            # If the process crashes between here and the final upsert below, the
            # reconciler will find this row on next startup and resolve it.
            upsert_trade(trade, source="scanner")

            # Optionally submit to Alpaca broker for real paper execution
            if self.alpaca:
                try:
                    alpaca_result = self.alpaca.submit_credit_spread(
                        ticker=trade["ticker"],
                        short_strike=trade["short_strike"],
                        long_strike=trade["long_strike"],
                        expiration=trade["expiration"],
                        spread_type=trade["type"],
                        contracts=trade["contracts"],
                        limit_price=trade["credit_per_spread"],
                        client_order_id=client_order_id,
                    )
                    trade["alpaca_order_id"] = alpaca_result.get("order_id")
                    trade["alpaca_status"] = alpaca_result.get("status")

                    if alpaca_result["status"] == "error":
                        logger.warning(
                            f"Alpaca order failed: {alpaca_result['message']}. Recording as DB-only trade."
                        )
                    else:
                        logger.info(f"Alpaca order submitted: {alpaca_result['order_id']}")
                except Exception as e:
                    logger.warning(f"Alpaca submission failed: {e}. Recording as DB-only trade.")

            # Promote to open — all submission paths (Alpaca success, Alpaca error,
            # no Alpaca) converge here.  The reconciler will back-fill fill prices.
            trade["status"] = "open"

            # Add to in-memory tracking now that we have a confirmed intent
            self.trades["trades"].append(trade)
            self._open_trades.append(trade)
            self.trades["stats"]["total_trades"] += 1

            # Final SQLite write with status=open
            upsert_trade(trade, source="scanner")

            metrics.inc('trades_opened')

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
        if self._is_kill_switch_active():
            logger.warning("Kill switch active — skipping position management")
            return []

        closed = []
        now = datetime.now(timezone.utc)

        for trade in self.open_trades:
            ticker = trade["ticker"]
            raw_price = current_prices.get(ticker, trade.get("entry_price", 0))
            if hasattr(raw_price, 'iloc'):
                raw_price = raw_price.iloc[0]
            current_price = float(raw_price)

            # Parse expiration
            exp_str = str(trade.get("expiration", ""))
            exp_str = exp_str.split(" ")[0] if " " in exp_str else exp_str
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    exp_date = datetime.fromisoformat(exp_str)
                    if exp_date.tzinfo is None:
                        exp_date = exp_date.replace(tzinfo=timezone.utc)
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
        if "condor" in spread_type.lower():
            # Iron condor: evaluate BOTH wings, take worst case
            put_intrinsic = max(0, short_strike - current_price)
            call_short = trade.get("call_short_strike", 0)
            call_intrinsic = max(0, current_price - call_short) if call_short else 0
            intrinsic = max(put_intrinsic, call_intrinsic)
        elif "call" in spread_type.lower():
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
                    spread_type=trade.get("type", trade.get("strategy_type", "bull_put_spread")),
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
            trade["exit_date"] = datetime.now(timezone.utc).isoformat()
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

        metrics.inc('trades_closed')

        # Anti-suicide-loop: record losing trades for circuit breaker
        if pnl < 0:
            self._record_loss(trade)

        # Log outcome for ML retraining
        self._log_trade_outcome(trade)

        logger.info(
            f"PAPER TRADE CLOSED: {trade['ticker']} {trade.get('type', '')} | "
            f"P&L: ${pnl:+.2f} | Reason: {reason} | "
            f"Balance: ${self.trades['current_balance']:,.2f}"
        )

    def _startup_reconcile(self) -> str:
        """Resolve pending_open DB rows created by write-ahead before last shutdown.

        Called once during __init__, before _load_trades(), so that any resolved
        trades are already in their final status when the in-memory state is built.

        Returns a human-readable summary string (empty string if nothing changed).
        """
        if not self.alpaca:
            return ""
        try:
            from shared.reconciler import PositionReconciler
            result = PositionReconciler(self.alpaca).reconcile()
            if result:
                return (
                    f"resolved={result.pending_resolved}, "
                    f"failed={result.pending_failed}"
                )
        except Exception as e:
            logger.warning("Startup reconciliation error: %s", e)
        return ""

    def reconcile_positions(self) -> None:
        """Run a reconciliation pass and reload in-memory state if anything changed.

        Called periodically from the scheduler (every ~3 scan cycles ≈ 90 min)
        to catch positions that were quietly closed in Alpaca (expiration, manual
        close, etc.) without going through our normal exit path.
        """
        if not self.alpaca:
            return
        try:
            from shared.reconciler import PositionReconciler
            result = PositionReconciler(self.alpaca).reconcile()
            if result:
                logger.info("Reconciliation pass: %s", result)
                # Reload in-memory state to reflect DB changes
                with self._trades_lock:
                    self.trades = self._load_trades()
                    self._rebuild_cached_lists()
        except Exception as e:
            logger.warning("Periodic reconciliation error: %s", e)

    def _reconcile_submitted_orders(self) -> int:
        """Reconcile locally-open trades whose Alpaca orders are not yet confirmed filled.

        Called once on startup.  For each unconfirmed order:
          - Ask Alpaca for the real status.
          - If filled: update alpaca_status; trade stays open (it is a real position).
          - If terminal non-fill (cancelled/rejected/expired/replaced): force-close locally.
          - If Alpaca API errors out OR the order is still "submitted" after
            _STALE_ORDER_HOURS: treat as dead and force-close locally.

        Returns the number of positions removed from open-position tracking.
        """
        if not self.alpaca:
            return 0

        now = datetime.now(timezone.utc)
        removed = 0

        for trade in list(self.open_trades):   # iterate a snapshot — list may shrink
            order_id = trade.get("alpaca_order_id")
            alpaca_status = trade.get("alpaca_status", "")

            if not order_id or alpaca_status == "filled":
                continue

            # How old is this order?
            try:
                entry_time = datetime.fromisoformat(trade.get("entry_date", ""))
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                hours_old = (now - entry_time).total_seconds() / 3600
            except (ValueError, TypeError):
                hours_old = 99   # unknown age → treat as old

            # Ask Alpaca for the real status
            api_error = False
            new_status = alpaca_status
            try:
                result = self.alpaca.get_order_status(order_id)
                new_status = result.get("status", alpaca_status)
            except Exception as e:
                logger.warning("Alpaca order check failed for %s (order=%s): %s",
                               trade["ticker"], order_id, e)
                api_error = True

            # Persist updated status if it changed
            if new_status != alpaca_status:
                trade["alpaca_status"] = new_status
                upsert_trade(trade, source="scanner")
                logger.info("Alpaca order status updated: %s %s → %s",
                            trade["ticker"], alpaca_status, new_status)

            # Determine whether this position should be cleaned up
            is_terminal = new_status in _TERMINAL_ALPACA_STATES
            is_stale = (
                (api_error or new_status not in ("filled", "partially_filled"))
                and hours_old >= _STALE_ORDER_HOURS
            )

            if is_terminal or is_stale:
                self._force_close_stale(trade)
                removed += 1

        if removed:
            self._save_trades()
            logger.warning(
                "Startup reconciliation: %d stale/unconfirmed Alpaca order(s) "
                "removed from open-position tracking.", removed
            )
        return removed

    def _force_close_stale(self, trade: Dict) -> None:
        """Remove a stale/unconfirmed Alpaca order from open-position tracking.

        Unlike _close_trade(), this does NOT call alpaca.close_spread() — the
        order is already in a terminal state or unreachable, so there is nothing
        to close on the broker side.  Updates local state only.
        """
        with self._trades_lock:
            trade["status"] = "closed_manual"
            trade["exit_date"] = datetime.now(timezone.utc).isoformat()
            trade["exit_reason"] = "stale_order"
            trade["pnl"] = 0.0
            trade["exit_pnl"] = 0.0

            if trade in self._open_trades:
                self._open_trades.remove(trade)
            self._closed_trades.append(trade)

        upsert_trade(trade, source="scanner")
        logger.info(
            "Stale order removed from tracking: %s %s | order=%s | was_status=%s",
            trade["ticker"],
            trade.get("strategy_type", ""),
            trade.get("alpaca_order_id"),
            trade.get("alpaca_status"),
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

    def _log_trade_outcome(self, trade: Dict):
        """Log closed trade outcome to ml/training_data/ for future model retraining."""
        try:
            training_dir = DATA_DIR / "ml_training"
            training_dir.mkdir(parents=True, exist_ok=True)

            outcome = {
                "id": trade.get("id"),
                "ticker": trade.get("ticker"),
                "type": trade.get("type"),
                "short_strike": trade.get("short_strike"),
                "long_strike": trade.get("long_strike"),
                "expiration": trade.get("expiration"),
                "entry_date": trade.get("entry_date"),
                "exit_date": trade.get("exit_date"),
                "exit_reason": trade.get("exit_reason"),
                "entry_price": trade.get("entry_price"),
                "credit": trade.get("credit"),
                "contracts": trade.get("contracts"),
                "pnl": trade.get("pnl"),
                "result": "win" if (trade.get("pnl") or 0) > 0 else "loss",
                "entry_score": trade.get("entry_score"),
                "entry_pop": trade.get("entry_pop"),
                "entry_delta": trade.get("entry_delta"),
                "dte_at_entry": trade.get("dte_at_entry"),
                "consecutive_loss_count": trade.get("consecutive_loss_count", 0),
            }

            # Append to JSONL file (one line per outcome)
            log_file = training_dir / "trade_outcomes.jsonl"
            with open(log_file, "a") as f:
                f.write(json.dumps(outcome) + "\n")

            logger.debug(f"Logged trade outcome for {trade.get('ticker')} to {log_file}")
        except Exception as e:
            logger.warning(f"Failed to log trade outcome: {e}")

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
