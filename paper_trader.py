"""
Paper Trading Engine
Automatically takes signals from the scanner and tracks simulated trades.
Monitors open positions and closes at profit target, stop loss, or expiration.
"""

import json
import logging
import os
import yaml
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
TRADES_FILE = DATA_DIR / "trades.json"
PAPER_LOG = DATA_DIR / "paper_trades.json"


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
                logger.warning(f"Alpaca init failed, falling back to JSON: {e}")
                self.alpaca = None

        DATA_DIR.mkdir(exist_ok=True)
        self.trades = self._load_trades()
        logger.info(f"PaperTrader initialized | Balance: ${self.account_size:,.0f} | "
                     f"Open: {len(self.open_trades)} | Closed: {len(self.closed_trades)} | "
                     f"Alpaca: {'ON' if self.alpaca else 'OFF'}")

    def _load_trades(self) -> Dict:
        if PAPER_LOG.exists():
            with open(PAPER_LOG) as f:
                return json.load(f)
        return {
            "account_size": self.account_size,
            "starting_balance": self.account_size,
            "current_balance": self.account_size,
            "trades": [],
            "stats": {
                "total_trades": 0,
                "winners": 0,
                "losers": 0,
                "total_pnl": 0,
                "win_rate": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "avg_winner": 0,
                "avg_loser": 0,
                "max_drawdown": 0,
                "peak_balance": self.account_size,
            },
        }

    def _save_trades(self):
        with open(PAPER_LOG, "w") as f:
            json.dump(self.trades, f, indent=2, default=str)
        # Also write to trades.json for the web dashboard
        self._export_for_dashboard()

    def _export_for_dashboard(self):
        """Write trades in format the web dashboard expects."""
        dashboard_data = {
            "balance": self.trades["current_balance"],
            "starting_balance": self.trades["starting_balance"],
            "total_pnl": self.trades["stats"]["total_pnl"],
            "win_rate": self.trades["stats"]["win_rate"],
            "open_positions": [t for t in self.trades["trades"] if t["status"] == "open"],
            "closed_positions": [t for t in self.trades["trades"] if t["status"] == "closed"],
            "stats": self.trades["stats"],
            "updated_at": datetime.now().isoformat(),
        }
        with open(TRADES_FILE, "w") as f:
            json.dump(dashboard_data, f, indent=2, default=str)

    @property
    def open_trades(self) -> List[Dict]:
        return [t for t in self.trades["trades"] if t["status"] == "open"]

    @property
    def closed_trades(self) -> List[Dict]:
        return [t for t in self.trades["trades"] if t["status"] == "closed"]

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
        credit = opp.get("credit", 0)
        max_loss = opp.get("max_loss", 0)
        
        if credit <= 0 or max_loss <= 0:
            return None

        # Position sizing: max risk per trade
        max_risk_dollars = self.trades["current_balance"] * self.max_risk_per_trade
        max_contracts = max(1, int(max_risk_dollars / (max_loss * 100)))
        contracts = min(max_contracts, 10)  # Cap at 10 contracts

        trade = {
            "id": len(self.trades["trades"]) + 1,
            "status": "open",
            "ticker": opp["ticker"],
            "type": opp["type"],
            "short_strike": opp["short_strike"],
            "long_strike": opp["long_strike"],
            "expiration": str(opp.get("expiration", "")),
            "dte_at_entry": opp.get("dte", 0),
            "contracts": contracts,
            "credit_per_spread": credit,
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

        # Submit to Alpaca if available
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
                )
                trade["alpaca_order_id"] = alpaca_result.get("order_id")
                trade["alpaca_status"] = alpaca_result.get("status")
                if alpaca_result["status"] == "error":
                    logger.warning(f"Alpaca order failed: {alpaca_result['message']}. Recording in JSON only.")
                else:
                    logger.info(f"Alpaca order submitted: {alpaca_result['order_id']}")
            except Exception as e:
                logger.warning(f"Alpaca submission failed, recording in JSON: {e}")
                trade["alpaca_order_id"] = None
                trade["alpaca_status"] = "fallback_json"

        self.trades["trades"].append(trade)
        self.trades["stats"]["total_trades"] += 1

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
            current_price = current_prices.get(ticker, trade["entry_price"])

            # Parse expiration
            exp_str = trade["expiration"].split(" ")[0] if " " in trade["expiration"] else trade["expiration"]
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            except:
                try:
                    exp_date = datetime.fromisoformat(trade["expiration"])
                except:
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
        credit = trade["total_credit"]
        contracts = trade["contracts"]
        short_strike = trade["short_strike"]
        long_strike = trade["long_strike"]
        spread_type = trade["type"]

        # Determine if in danger
        if "call" in spread_type.lower():
            # Bear call spread: bad if price goes above short strike
            intrinsic = max(0, current_price - short_strike)
            distance_pct = (short_strike - current_price) / current_price if current_price > 0 else 0
        else:
            # Bull put spread: bad if price goes below short strike
            intrinsic = max(0, short_strike - current_price)
            distance_pct = (current_price - short_strike) / current_price if current_price > 0 else 0

        spread_width = abs(long_strike - short_strike)

        # Simplified P&L model:
        # If OTM and time has passed, spread value decays toward 0 (we profit)
        # If ITM, spread value approaches intrinsic
        entry_dte = trade.get("dte_at_entry", 35)
        time_passed_pct = max(0, 1 - (dte / max(entry_dte, 1)))

        if intrinsic == 0:
            # OTM — time decay is our friend
            # Estimate current spread value as fraction of original credit
            decay_factor = max(0, 1 - time_passed_pct * 1.2)  # Accelerating decay
            current_value = credit * decay_factor
            pnl = round(credit - current_value, 2)
        else:
            # ITM — losing money
            current_spread_value = min(intrinsic * contracts * 100, trade["total_max_loss"])
            remaining_extrinsic = credit * max(0, 1 - time_passed_pct) * 0.3
            pnl = round(credit - current_spread_value + remaining_extrinsic - credit, 2)
            # Simplified: pnl = -(current_spread_value - remaining_extrinsic)
            pnl = round(-(current_spread_value - remaining_extrinsic), 2)

        # Check exit conditions
        close_reason = None

        # 1. Profit target hit (50% of credit)
        if pnl >= trade["profit_target"]:
            close_reason = "profit_target"

        # 2. Stop loss hit
        elif pnl <= -trade["stop_loss_amount"]:
            close_reason = "stop_loss"

        # 3. Expiration (or close at 1 DTE)
        elif dte <= 1:
            close_reason = "expiration"

        # 4. Manage at 21 DTE — close if profitable
        elif dte <= 21 and pnl > 0:
            close_reason = "management_dte"

        return pnl, close_reason

    def _close_trade(self, trade: Dict, pnl: float, reason: str):
        """Close a paper trade."""
        # Close on Alpaca if we have an order
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
                logger.warning(f"Alpaca close failed: {e}")

        trade["status"] = "closed"
        trade["exit_date"] = datetime.now().isoformat()
        trade["exit_reason"] = reason
        trade["exit_pnl"] = pnl

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

        winners = [t["exit_pnl"] for t in self.closed_trades if (t.get("exit_pnl") or 0) > 0]
        losers = [t["exit_pnl"] for t in self.closed_trades if (t.get("exit_pnl") or 0) < 0]
        stats["avg_winner"] = round(sum(winners) / len(winners), 2) if winners else 0
        stats["avg_loser"] = round(sum(losers) / len(losers), 2) if losers else 0

        # Track peak and drawdown
        if self.trades["current_balance"] > stats["peak_balance"]:
            stats["peak_balance"] = self.trades["current_balance"]
        drawdown = stats["peak_balance"] - self.trades["current_balance"]
        stats["max_drawdown"] = max(stats["max_drawdown"], drawdown)

        logger.info(
            f"PAPER TRADE CLOSED: {trade['ticker']} {trade['type']} | "
            f"P&L: ${pnl:+.2f} | Reason: {reason} | "
            f"Balance: ${self.trades['current_balance']:,.2f}"
        )

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
        print("  📊 PAPER TRADING SUMMARY")
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
                print(f"    {t['ticker']} {t['type']} "
                      f"${t['short_strike']}/{t['long_strike']} "
                      f"x{t['contracts']} | Credit: ${t['total_credit']:.0f} | "
                      f"P&L: ${t['current_pnl']:+.2f}")
        print()
