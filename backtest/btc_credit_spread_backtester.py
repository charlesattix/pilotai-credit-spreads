"""
BTC Put Credit Spread Backtester — Real Deribit Data (2020–2024)

Uses real historical OHLCV from Deribit (deribit_btc_cache.db).
All option prices in BTC (Deribit native). P&L tracked in USD via daily spot conversion.

Strategy: Monthly bull-put spreads
  - Entry: ~DTE_TARGET days before last-Friday-of-month expiry
  - Short put: nearest confirmed strike to spot × (1 - otm_pct)
  - Long put:  nearest confirmed strike at or below short_strike × (1 - spread_width_pct)
  - Credit filter: min_credit_pct of spread width
  - Exit: profit target, stop loss, or hold to expiry
  - Sizing: flat-risk, n_contracts = floor(equity × risk_pct / max_loss_per_contract_usd)

P&L is in USD: pnl_usd = pnl_btc × btc_spot_at_close
"""

import calendar
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "deribit_btc_cache.db"

MONTH_ABBR = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}

DEFAULT_CONFIG = {
    "starting_capital":    100_000.0,
    "otm_pct":             0.05,   # 5% OTM short put
    "spread_width_pct":    0.05,   # long put = short_strike × (1 - spread_width_pct)
    "min_credit_pct":      8.0,    # minimum credit as % of (short_strike - long_strike)
    "stop_loss_multiplier": 2.5,   # close when spread value > entry_credit × this
    "profit_target_pct":   0.50,   # close when 50% of credit captured
    "dte_target":          35,     # target entry ~35 DTE from expiry
    "dte_min":             7,      # do not enter if DTE < this
    "risk_per_trade_pct":  0.05,   # 5% of equity per trade
    "max_contracts":       20,
    "compound":            True,
    "commission_rate":     0.0003, # 0.03% of underlying notional per side (Deribit taker)
    "slippage_btc":        0.0002, # flat BTC slippage per leg at exit
    # --- Regime gate (new) ---
    # "none"         : no filtering (original behavior)
    # "ma200_bull_only" : only enter when BTC price > 200-day MA (bull regime)
    # "ma200_scaled" : enter always but scale risk by regime (1.5x bull, 0.5x bear)
    # "ma200_skip_bear" : skip entries when price < 90% of MA200 (strong bear)
    "regime_filter":       "none",
    "ma_period":           200,    # MA period for regime detection
}


def last_friday_of_month(year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    days_back = (d.weekday() - 4) % 7
    return d - timedelta(days=days_back)


class BTCCreditSpreadBacktester:

    def __init__(self, config: dict = None, db_path: Path = DB_PATH):
        self.cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row

        # State reset per run
        self.capital: float = 0.0
        self.starting_capital: float = 0.0
        self.open_positions: List[dict] = []
        self.trades: List[dict] = []
        self.equity_curve: List[Tuple[str, float]] = []
        self._ruin = False

        # Regime: MA cache — populated in run()
        self._ma_cache: Dict[str, Optional[float]] = {}  # date -> MA value or None

    def _spot(self, dt: str) -> Optional[float]:
        """BTC/USD spot price for a given date (or nearest prior trading day)."""
        row = self._conn.execute(
            "SELECT price_usd FROM btc_spot WHERE date <= ? ORDER BY date DESC LIMIT 1",
            (dt,),
        ).fetchone()
        return row["price_usd"] if row else None

    def _puts_for_expiry(self, expiry_str: str, entry_date: str) -> List[sqlite3.Row]:
        """
        All confirmed put strikes with a real close price on entry_date for the given expiry.
        Returns rows sorted ascending by strike.
        """
        return self._conn.execute("""
            SELECT c.instrument_name, c.strike, d.close AS price_btc
            FROM btc_contracts c
            JOIN btc_option_daily d ON c.instrument_name = d.instrument_name
            WHERE c.expiration_date = ?
              AND c.option_type    = 'P'
              AND d.date           = ?
              AND d.close          IS NOT NULL
              AND d.close          > 0
              AND d.date           != '0000-00-00'
            ORDER BY c.strike ASC
        """, (expiry_str, entry_date)).fetchall()

    def _option_price(self, instrument_name: str, dt: str) -> Optional[float]:
        """Close price in BTC for an instrument on a given date."""
        row = self._conn.execute(
            "SELECT close FROM btc_option_daily WHERE instrument_name = ? AND date = ?",
            (instrument_name, dt),
        ).fetchone()
        if row and row["close"] is not None:
            return row["close"]
        return None

    def _trading_days(self, year: int) -> List[str]:
        """All dates in year that have BTC spot data (proxy for trading days)."""
        rows = self._conn.execute(
            "SELECT date FROM btc_spot WHERE date >= ? AND date <= ? ORDER BY date",
            (f"{year}-01-01", f"{year}-12-31"),
        ).fetchall()
        return [r["date"] for r in rows]

    def _build_ma_cache(self, all_dates: List[str]) -> None:
        """
        Pre-compute the N-day simple moving average of BTC spot for every date
        in all_dates. Uses a rolling window over the full spot table so the MA
        is always computed from real historical data (no lookahead).

        Stores results in self._ma_cache[date] = ma_value | None.
        """
        if self.cfg.get("regime_filter", "none") == "none":
            return  # nothing to compute

        ma_period = int(self.cfg.get("ma_period", 200))

        if not all_dates:
            return

        # Fetch all spot data from (min_date - ma_period trading days) to max_date
        min_date = all_dates[0]
        max_date = all_dates[-1]

        rows = self._conn.execute(
            "SELECT date, price_usd FROM btc_spot WHERE date <= ? ORDER BY date",
            (max_date,),
        ).fetchall()

        # Build a sliding window
        prices: List[float] = []
        dates_prices: List[Tuple[str, float]] = [(r["date"], r["price_usd"]) for r in rows]

        # Build lookup: date -> MA
        ma_lookup: Dict[str, float] = {}
        price_window: List[float] = []
        for dt, px in dates_prices:
            price_window.append(px)
            if len(price_window) >= ma_period:
                ma_lookup[dt] = sum(price_window[-ma_period:]) / ma_period

        for dt in all_dates:
            self._ma_cache[dt] = ma_lookup.get(dt)

    def _regime_risk_scale(self, entry_date: str, spot: float) -> float:
        """
        Return the risk-per-trade scale factor for this entry date based on
        the configured regime_filter.

        Returns:
            1.0  → full size
            0.0  → skip entry entirely
            other positive float → scaled size
        """
        regime_filter = self.cfg.get("regime_filter", "none")
        if regime_filter == "none":
            return 1.0

        ma = self._ma_cache.get(entry_date)
        if ma is None:
            # Not enough history to compute MA — be conservative
            return 0.5

        ratio = spot / ma  # >1 = price above MA (bull), <1 = below MA (bear)

        if regime_filter == "ma200_bull_only":
            # Only enter in bull regime (price > MA200)
            return 1.0 if ratio >= 1.0 else 0.0

        if regime_filter == "ma200_skip_bear":
            # Skip when price is deeply below MA (< 90% of MA)
            return 1.0 if ratio >= 0.90 else 0.0

        if regime_filter == "ma200_scaled":
            # Scale risk continuously: bull = up to 1.5x, bear = down to 0.25x
            if ratio >= 1.10:
                return 1.5   # strongly bullish
            elif ratio >= 1.0:
                return 1.25  # mildly bullish
            elif ratio >= 0.90:
                return 0.75  # mildly bearish
            else:
                return 0.25  # strongly bearish

        return 1.0  # fallback

    def _find_spread(
        self,
        puts: List[sqlite3.Row],
        spot: float,
    ) -> Optional[dict]:
        """
        Find the best put credit spread from available puts.
        Returns spread details or None if no valid spread exists.
        """
        otm_pct = self.cfg["otm_pct"]
        width_pct = self.cfg["spread_width_pct"]
        min_credit_pct = self.cfg["min_credit_pct"]

        target_short = spot * (1 - otm_pct)
        strikes = [r["strike"] for r in puts]

        # Nearest strike at or below target_short
        short_candidates = [s for s in strikes if s <= target_short * 1.02]
        if not short_candidates:
            return None
        short_strike = max(short_candidates)  # closest to target (highest below)

        # Target long strike
        target_long = short_strike * (1 - width_pct)
        long_candidates = [s for s in strikes if s < short_strike and s <= target_long * 1.02]
        if not long_candidates:
            return None
        long_strike = max(long_candidates)  # closest long below short

        # Skip if strikes are the same (can't form a spread)
        if long_strike >= short_strike:
            return None

        # Look up prices
        short_row = next((r for r in puts if r["strike"] == short_strike), None)
        long_row  = next((r for r in puts if r["strike"] == long_strike),  None)
        if not short_row or not long_row:
            return None

        short_price = short_row["price_btc"]
        long_price  = long_row["price_btc"]

        if short_price <= 0 or long_price < 0:
            return None
        if long_price >= short_price:
            return None  # degenerate spread

        credit_btc = short_price - long_price
        spread_width_usd = short_strike - long_strike  # width in USD (strike space)

        # Credit as % of spread width in USD terms
        # credit_pct = credit_usd / spread_width_usd × 100
        # We need BTC spot to convert credit to USD
        # Approximate: credit_usd ≈ credit_btc × spot
        # credit_pct = (credit_btc × spot) / spread_width_usd × 100
        # But spread_width is in USD already (K1 - K2), so this is correct
        # credit_pct will be recalculated with actual spot in _try_enter

        return {
            "short_instrument": short_row["instrument_name"],
            "long_instrument":  long_row["instrument_name"],
            "short_strike":     short_strike,
            "long_strike":      long_strike,
            "spread_width_usd": spread_width_usd,
            "short_price_btc":  short_price,
            "long_price_btc":   long_price,
            "credit_btc":       credit_btc,
        }

    def _try_enter(self, entry_date: str, expiry: date) -> Optional[dict]:
        """
        Attempt to open a put credit spread for the given expiry.
        Returns position dict on success, None otherwise.
        """
        expiry_str = expiry.strftime("%Y-%m-%d")
        dte = (expiry - datetime.strptime(entry_date, "%Y-%m-%d").date()).days
        if dte < self.cfg["dte_min"]:
            return None

        spot = self._spot(entry_date)
        if not spot:
            return None

        # --- Regime gate ---
        regime_scale = self._regime_risk_scale(entry_date, spot)
        if regime_scale <= 0.0:
            log.debug("%s: regime filter blocks entry (scale=%.2f)", entry_date, regime_scale)
            return None

        puts = self._puts_for_expiry(expiry_str, entry_date)
        if not puts:
            return None

        spread = self._find_spread(puts, spot)
        if not spread:
            return None

        # Credit filter: credit_usd / spread_width_usd must meet minimum
        credit_usd = spread["credit_btc"] * spot
        credit_pct = credit_usd / spread["spread_width_usd"] * 100.0
        if credit_pct < self.cfg["min_credit_pct"]:
            log.debug("%s: credit %.1f%% < min %.1f%%", entry_date, credit_pct, self.cfg["min_credit_pct"])
            return None

        # Position sizing: risk_pct of equity (scaled by regime), capped by max_contracts
        # max_loss per contract ≈ spread_width_usd - credit_usd
        max_loss_usd = spread["spread_width_usd"] - credit_usd
        if max_loss_usd <= 0:
            return None

        account_base = self.capital if self.cfg["compound"] else self.starting_capital
        effective_risk_pct = self.cfg["risk_per_trade_pct"] * regime_scale
        risk_budget = account_base * effective_risk_pct
        n_contracts = int(risk_budget / max_loss_usd)
        n_contracts = max(1, min(n_contracts, self.cfg["max_contracts"]))

        # Commission: 0.03% of underlying notional per leg per side
        # Deribit charges on the notional = 1 BTC per contract
        comm_per_contract_btc = self.cfg["commission_rate"] * 2  # 2 legs × entry + 2 × exit ≈ 4 sides total
        # We'll charge entry + planned exit commission upfront
        commission_usd = comm_per_contract_btc * spot * n_contracts

        # Deduct commission from capital at entry
        self.capital -= commission_usd

        position = {
            "entry_date":        entry_date,
            "expiry":            expiry_str,
            "short_instrument":  spread["short_instrument"],
            "long_instrument":   spread["long_instrument"],
            "short_strike":      spread["short_strike"],
            "long_strike":       spread["long_strike"],
            "spread_width_usd":  spread["spread_width_usd"],
            "credit_btc":        spread["credit_btc"],
            "credit_usd":        credit_usd,
            "credit_pct":        credit_pct,
            "max_loss_usd":      max_loss_usd,
            "n_contracts":       n_contracts,
            "btc_spot_at_entry": spot,
            "commission_usd":    commission_usd,
            "profit_target_btc": spread["credit_btc"] * (1.0 - self.cfg["profit_target_pct"]),
            "stop_loss_btc":     spread["credit_btc"] * self.cfg["stop_loss_multiplier"],
            "status":            "open",
        }

        log.debug(
            "%s ENTRY: exp=%s short=%d long=%d credit=%.4f BTC (%.1f%%) x%d",
            entry_date, expiry_str,
            int(spread["short_strike"]), int(spread["long_strike"]),
            spread["credit_btc"], credit_pct, n_contracts,
        )
        return position

    def _check_exit(self, pos: dict, current_date: str) -> Optional[Tuple[float, str]]:
        """
        Check if position should be exited today.
        Returns (pnl_usd, reason) or None to keep holding.
        """
        spot = self._spot(current_date)
        if not spot:
            return None

        short_price = self._option_price(pos["short_instrument"], current_date)
        long_price  = self._option_price(pos["long_instrument"],  current_date)

        if short_price is None or long_price is None:
            return None  # no data — skip today

        current_spread_btc = max(0.0, short_price - long_price)
        slippage_btc = self.cfg["slippage_btc"] * 2 * pos["n_contracts"]  # 2 legs at exit

        reason = None
        if current_spread_btc <= pos["profit_target_btc"]:
            reason = "profit_target"
        elif current_spread_btc >= pos["stop_loss_btc"]:
            reason = "stop_loss"

        if reason:
            exit_spread_btc = current_spread_btc + slippage_btc / pos["n_contracts"]
            pnl_btc = (pos["credit_btc"] - exit_spread_btc) * pos["n_contracts"]
            pnl_usd = pnl_btc * spot
            return pnl_usd, reason

        # Update unrealized P&L for equity curve
        unrealized_btc = (pos["credit_btc"] - current_spread_btc) * pos["n_contracts"]
        pos["unrealized_usd"] = unrealized_btc * spot
        return None

    def _close_at_expiry(self, pos: dict, expiry_str: str) -> Tuple[float, str]:
        """
        Close position at expiry using intrinsic value.
        Falls back to real option prices on expiry date if available.
        """
        spot = self._spot(expiry_str)
        if not spot:
            spot = pos["btc_spot_at_entry"]  # emergency fallback

        # Try real prices first
        short_price = self._option_price(pos["short_instrument"], expiry_str)
        long_price  = self._option_price(pos["long_instrument"],  expiry_str)

        if short_price is not None and long_price is not None:
            exit_spread_btc = max(0.0, short_price - long_price)
            slippage_btc = self.cfg["slippage_btc"] * 2 * pos["n_contracts"]
            if exit_spread_btc > 0.0005:  # has residual value
                exit_spread_btc += slippage_btc / pos["n_contracts"]
            pnl_btc = (pos["credit_btc"] - exit_spread_btc) * pos["n_contracts"]
            return pnl_btc * spot, "expiry_real"

        # Intrinsic value at expiry (using spot)
        short_intrinsic = max(0.0, pos["short_strike"] - spot) / spot  # in BTC
        long_intrinsic  = max(0.0, pos["long_strike"]  - spot) / spot
        intrinsic_spread = short_intrinsic - long_intrinsic
        pnl_btc = (pos["credit_btc"] - intrinsic_spread) * pos["n_contracts"]
        return pnl_btc * spot, "expiry_intrinsic"

    def _record_close(self, pos: dict, exit_date: str, pnl_usd: float, reason: str):
        self.capital += pnl_usd
        self.trades.append({
            "entry_date":    pos["entry_date"],
            "exit_date":     exit_date,
            "expiry":        pos["expiry"],
            "short_strike":  pos["short_strike"],
            "long_strike":   pos["long_strike"],
            "credit_btc":    pos["credit_btc"],
            "credit_usd":    pos["credit_usd"],
            "credit_pct":    pos["credit_pct"],
            "n_contracts":   pos["n_contracts"],
            "btc_at_entry":  pos["btc_spot_at_entry"],
            "btc_at_exit":   self._spot(exit_date) or pos["btc_spot_at_entry"],
            "pnl_usd":       pnl_usd,
            "exit_reason":   reason,
            "win":           pnl_usd > 0,
        })
        pos["status"] = "closed"

    def run(self, years: List[int]) -> dict:
        """
        Run the backtest for the given years.
        Returns results dict compatible with the existing leaderboard format.
        """
        self.capital          = self.cfg["starting_capital"]
        self.starting_capital = self.cfg["starting_capital"]
        self.open_positions   = []
        self.trades           = []
        self.equity_curve     = []
        self._ruin            = False
        self._ma_cache        = {}

        # Monthly expiries within our years, sorted
        all_expiries: Dict[str, date] = {}
        for year in years:
            for month in range(1, 13):
                exp = last_friday_of_month(year, month)
                all_expiries[exp.strftime("%Y-%m-%d")] = exp

        # Get sorted trading days across all years
        all_dates = []
        for year in years:
            all_dates.extend(self._trading_days(year))
        all_dates = sorted(set(all_dates))

        # Build MA cache for regime filtering
        self._build_ma_cache(all_dates)

        for current_date in all_dates:
            if self._ruin:
                break

            today = datetime.strptime(current_date, "%Y-%m-%d").date()

            # --- Close expiring positions ---
            for pos in list(self.open_positions):
                if pos["status"] != "open":
                    continue
                exp_str = pos["expiry"]
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                if today >= exp_date:
                    pnl_usd, reason = self._close_at_expiry(pos, exp_str)
                    self._record_close(pos, exp_str, pnl_usd, reason)

            self.open_positions = [p for p in self.open_positions if p["status"] == "open"]

            # --- Check stop-loss / profit-target on open positions ---
            for pos in list(self.open_positions):
                result = self._check_exit(pos, current_date)
                if result:
                    pnl_usd, reason = result
                    self._record_close(pos, current_date, pnl_usd, reason)

            self.open_positions = [p for p in self.open_positions if p["status"] == "open"]

            # --- Entry: one open position at a time (monthly spread strategy) ---
            if len(self.open_positions) == 0 and not self._ruin:
                # Find the next monthly expiry with DTE near target
                for exp_str, exp_date in sorted(all_expiries.items()):
                    dte = (exp_date - today).days
                    if dte < self.cfg["dte_min"]:
                        continue
                    # Enter if DTE is within dte_target ± 10
                    dte_target = self.cfg["dte_target"]
                    if abs(dte - dte_target) <= 10 or dte_target - 5 <= dte <= dte_target + 15:
                        pos = self._try_enter(current_date, exp_date)
                        if pos:
                            self.open_positions.append(pos)
                        break  # one entry attempt per day

            # --- Equity curve: cash + unrealized MTM ---
            unrealized = sum(p.get("unrealized_usd", 0.0) for p in self.open_positions)
            total_equity = self.capital + unrealized
            self.equity_curve.append((current_date, total_equity))

            if self.capital <= 0:
                self._ruin = True
                log.warning("RUIN triggered on %s (capital=%.0f)", current_date, self.capital)

        return self._build_results(years)

    def run_year(self, year: int) -> dict:
        """Convenience: run a single year."""
        return self.run([year])

    def _build_results(self, years: List[int]) -> dict:
        import numpy as np

        trades = self.trades
        n_trades = len(trades)
        if n_trades == 0:
            return {
                "years": years, "total_trades": 0, "win_rate": 0.0,
                "return_pct": 0.0, "max_drawdown": 0.0,
                "starting_capital": self.starting_capital,
                "ending_capital": self.capital, "trades": [],
            }

        wins = [t for t in trades if t["win"]]
        win_rate = len(wins) / n_trades * 100.0

        total_pnl = sum(t["pnl_usd"] for t in trades)
        avg_win  = sum(t["pnl_usd"] for t in wins) / len(wins) if wins else 0.0
        losers   = [t for t in trades if not t["win"]]
        avg_loss = sum(abs(t["pnl_usd"]) for t in losers) / len(losers) if losers else 0.0
        profit_factor = abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losers)) \
            if losers and sum(t["pnl_usd"] for t in losers) != 0 else 999.0

        return_pct = (self.capital - self.starting_capital) / self.starting_capital * 100.0

        # Max drawdown from equity curve
        if self.equity_curve:
            equities = np.array([e for _, e in self.equity_curve])
            cummax = np.maximum.accumulate(equities)
            dd = (equities - cummax) / cummax
            max_drawdown = float(dd.min() * 100.0)
        else:
            max_drawdown = 0.0

        # Per-year breakdown
        year_stats: Dict[int, dict] = {}
        for year in years:
            yr_trades = [t for t in trades if t["entry_date"].startswith(str(year))]
            yr_wins = [t for t in yr_trades if t["win"]]
            yr_pnl = sum(t["pnl_usd"] for t in yr_trades)
            # Equity at start/end of year
            yr_equity = [(dt, eq) for dt, eq in self.equity_curve
                         if dt.startswith(str(year))]
            yr_start_eq = yr_equity[0][1]  if yr_equity else self.starting_capital
            yr_end_eq   = yr_equity[-1][1] if yr_equity else self.capital
            yr_ret = (yr_end_eq - yr_start_eq) / yr_start_eq * 100.0 if yr_start_eq > 0 else 0.0

            yr_equities = np.array([e for _, e in yr_equity]) if yr_equity else np.array([self.starting_capital])
            yr_cummax = np.maximum.accumulate(yr_equities)
            yr_dd_arr = (yr_equities - yr_cummax) / yr_cummax
            yr_dd = float(yr_dd_arr.min() * 100.0)

            year_stats[year] = {
                "return_pct":   yr_ret,
                "max_drawdown": yr_dd,
                "trade_count":  len(yr_trades),
                "win_rate":     len(yr_wins) / len(yr_trades) * 100.0 if yr_trades else 0.0,
                "pnl_usd":      yr_pnl,
            }

        return {
            "years":             years,
            "total_trades":      n_trades,
            "winning_trades":    len(wins),
            "losing_trades":     len(losers),
            "win_rate":          win_rate,
            "total_pnl":         total_pnl,
            "avg_win":           avg_win,
            "avg_loss":          avg_loss,
            "profit_factor":     profit_factor,
            "max_drawdown":      max_drawdown,
            "return_pct":        return_pct,
            "starting_capital":  self.starting_capital,
            "ending_capital":    self.capital,
            "year_stats":        year_stats,
            "trades":            trades,
            "equity_curve":      [{"date": d, "equity": e} for d, e in self.equity_curve],
            "ruin_triggered":    self._ruin,
        }
