"""
IBIT Credit Spread / Iron Condor Backtester

Uses real IBIT option data from crypto_options_cache.db (Polygon).
All P&L in USD (IBIT options: 100 shares per contract).

Features
────────
  • Bull-put spreads, bear-call spreads, iron condors
  • Direction-adaptive: auto-select direction based on MA regime
  • 0DTE / 1DTE / 3DTE / weekly / monthly support
  • Multi-position: up to max_concurrent simultaneous positions
  • Kelly criterion position sizing (fraction-Kelly with rolling history)
  • Same-day re-entry after profit target
  • Configurable via flat dict — sweep-compatible

Config keys (all optional — defaults below)
────────────────────────────────────────────
  starting_capital       float   100_000
  compound               bool    True   — compound equity for sizing
  direction              str     "bull_put"   — "bull_put" | "bear_call" | "iron_condor" | "adaptive"
  otm_pct                float   0.05   — OTM % for short put
  call_otm_pct           float   None   — OTM % for short call; None = use otm_pct
  spread_width           float   2.0    — put spread width ($)
  call_spread_width      float   None   — call spread width ($); None = use spread_width
  min_credit_pct         float   5.0    — min credit as % of spread width
  dte_target             int     21     — target DTE for entry
  dte_min                int     1      — minimum DTE (0 = same-day)
  dte_max                int     None   — max DTE; default dte_target + 10
  profit_target          float   0.50   — close when spread decays to (1 - profit_target) × credit
  stop_loss_mult         float   2.0    — close when spread >= credit × this
  risk_pct               float   0.05   — fraction of equity per trade
  max_contracts          int     100    — hard cap
  max_concurrent         int     1      — max open positions simultaneously
  kelly_fraction         float   0.0    — Kelly multiplier (0 = disabled; use risk_pct)
  kelly_min_trades       int     10     — min trade history before Kelly kicks in
  same_day_reentry       bool    False  — re-enter on same day after PT close
  regime_filter          str     "none" — "none"|"ma20"|"ma50"|"ma200"|"vol_filter"|"dd_cb"
  ma_period              int     50     — MA period for regime filter / adaptive direction
  adaptive_bull_put_otm_scale   float 0.8  — scale otm_pct in bull regime (tighter = closer to ATM)
  adaptive_bull_call_otm_scale  float 1.2  — scale call_otm_pct in bull regime (wider = more OTM)
  adaptive_bull_width_scale     float 1.25 — scale spread_width in bull regime
  adaptive_bear_put_otm_scale   float 1.2  — scale otm_pct in bear regime (wider)
  adaptive_bear_call_otm_scale  float 0.8  — scale call_otm_pct in bear regime (tighter)
  adaptive_bear_width_scale     float 0.75 — scale spread_width in bear regime
"""
from __future__ import annotations

import logging
import math
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "crypto_options_cache.db"

MULTIPLIER = 100  # shares per IBIT option contract

DEFAULT_CONFIG: Dict[str, Any] = {
    "starting_capital":    100_000.0,
    "compound":            True,
    "direction":           "bull_put",
    "otm_pct":             0.05,
    "call_otm_pct":        None,
    "spread_width":        2.0,
    "call_spread_width":   None,
    "min_credit_pct":      5.0,
    "dte_target":          21,
    "dte_min":             1,
    "dte_max":             None,
    "profit_target":       0.50,
    "stop_loss_mult":      2.0,
    "risk_pct":            0.05,
    "max_contracts":       100,
    "max_concurrent":      1,
    "kelly_fraction":      0.0,
    "kelly_min_trades":    10,
    "same_day_reentry":    False,
    "regime_filter":       "none",
    "ma_period":           50,
    # Adaptive IC scaling
    "adaptive_bull_put_otm_scale":   0.8,
    "adaptive_bull_call_otm_scale":  1.2,
    "adaptive_bull_width_scale":     1.25,
    "adaptive_bear_put_otm_scale":   1.2,
    "adaptive_bear_call_otm_scale":  0.8,
    "adaptive_bear_width_scale":     0.75,
}


# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build_occ_symbol(expiry: str, opt_type: str, strike: float) -> str:
    """O:IBIT{YYMMDD}{P|C}{strike*1000:08d}"""
    dt = datetime.strptime(expiry, "%Y-%m-%d")
    date_str = dt.strftime("%y%m%d")
    letter = "P" if opt_type == "put" else "C"
    strike_int = int(round(strike * 1000))
    return f"O:IBIT{date_str}{letter}{strike_int:08d}"


class IBITBacktester:
    """
    Full-featured IBIT credit spread backtester.
    Thread-safe for a single instance; create separate instances for parallel runs.
    """

    def __init__(self, config: Optional[Dict] = None, db_path: Path = DB_PATH):
        self.cfg: Dict[str, Any] = {**DEFAULT_CONFIG, **(config or {})}
        self.db_path = db_path

        # State — reset per run()
        self.capital: float = 0.0
        self.starting_capital: float = 0.0
        self.open_positions: List[dict] = []
        self.trades: List[dict] = []
        self.equity_curve: List[Tuple[str, float]] = []
        self._ruin = False

        # Pre-cached per run
        self._spots: Dict[str, float] = {}   # date -> IBIT close
        self._sorted_dates: List[str] = []   # all available spot dates sorted

    # ──────────────────────────────────────────────────────────────────────────
    # DB queries (use fresh connection per run to avoid threading issues)
    # ──────────────────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _load_spots(self, conn: sqlite3.Connection, start: str, end: str) -> None:
        """Cache all IBIT close prices (use T-1 for all regime/MA calculations)."""
        rows = conn.execute(
            "SELECT date, close FROM crypto_underlying_daily "
            "WHERE ticker='IBIT' AND date != '0000-00-00' ORDER BY date",
        ).fetchall()
        self._spots = {r["date"]: float(r["close"]) for r in rows if r["close"]}
        self._sorted_dates = sorted(self._spots.keys())

    def _spot(self, dt: str) -> Optional[float]:
        if dt in self._spots:
            return self._spots[dt]
        # nearest prior day
        for d in reversed(self._sorted_dates):
            if d <= dt:
                return self._spots[d]
        return None

    def _trading_days(self, conn: sqlite3.Connection, start: str, end: str) -> List[str]:
        rows = conn.execute(
            "SELECT date FROM crypto_underlying_daily "
            "WHERE ticker='IBIT' AND date >= ? AND date <= ? AND date != '0000-00-00' "
            "ORDER BY date",
            (start, end),
        ).fetchall()
        return [r["date"] for r in rows]

    def _available_expiries(
        self,
        conn: sqlite3.Connection,
        entry_date: str,
        dte_min: int,
        dte_max: int,
    ) -> List[Tuple[str, int]]:
        """Return (expiry_str, dte) pairs within [dte_min, dte_max] sorted by proximity to dte_target."""
        today = datetime.strptime(entry_date, "%Y-%m-%d").date()
        # Include same-day expiry if dte_min == 0
        compare_op = ">=" if dte_min == 0 else ">"
        end_search = (today + timedelta(days=dte_max + 5)).strftime("%Y-%m-%d")
        rows = conn.execute(
            f"SELECT DISTINCT expiration FROM crypto_option_contracts "
            f"WHERE ticker='IBIT' AND expiration {compare_op} ? AND expiration <= ? "
            f"ORDER BY expiration ASC",
            (entry_date, end_search),
        ).fetchall()
        result = []
        for r in rows:
            exp_str = r["expiration"]
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte_min <= dte <= dte_max:
                result.append((exp_str, dte))
        # Sort by closeness to dte_target
        target = self.cfg["dte_target"]
        result.sort(key=lambda x: abs(x[1] - target))
        return result

    def _get_options(
        self,
        conn: sqlite3.Connection,
        expiry: str,
        opt_type: str,
        entry_date: str,
    ) -> List[Dict]:
        """Fetch all available strikes with real closing prices for given expiry/date."""
        rows = conn.execute(
            """
            SELECT cc.strike, cd.close AS price
            FROM crypto_option_contracts cc
            JOIN crypto_option_daily cd ON cc.contract_symbol = cd.contract_symbol
            WHERE cc.ticker      = 'IBIT'
              AND cc.expiration  = ?
              AND cc.option_type = ?
              AND cd.date        = ?
              AND cd.close IS NOT NULL AND cd.close > 0
              AND cd.date != '0000-00-00'
            ORDER BY cc.strike ASC
            """,
            (expiry, opt_type, entry_date),
        ).fetchall()
        return [{"strike": float(r["strike"]), "price": float(r["price"])} for r in rows]

    def _get_option_price(
        self,
        conn: sqlite3.Connection,
        expiry: str,
        strike: float,
        opt_type: str,
        dt: str,
    ) -> Optional[float]:
        symbol = _build_occ_symbol(expiry, opt_type, strike)
        row = conn.execute(
            "SELECT close FROM crypto_option_daily "
            "WHERE contract_symbol = ? AND date = ? AND date != '0000-00-00'",
            (symbol, dt),
        ).fetchone()
        if row and row["close"] is not None and row["close"] > 0:
            return float(row["close"])
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Regime / MA
    # ──────────────────────────────────────────────────────────────────────────

    def _ma(self, dt: str, period: int) -> Optional[float]:
        """T-1 shifted MA — no lookahead."""
        idx = None
        for i, d in enumerate(self._sorted_dates):
            if d < dt:   # strictly less than (T-1)
                idx = i
        if idx is None or idx < period - 1:
            return None
        window = [self._spots[self._sorted_dates[j]] for j in range(idx - period + 1, idx + 1)]
        return sum(window) / len(window)

    def _realized_vol(self, dt: str, period: int = 10) -> Optional[float]:
        """Annualized realized vol over prior `period` trading days."""
        prior = [d for d in self._sorted_dates if d < dt]
        if len(prior) < period + 1:
            return None
        prices = [self._spots[prior[i]] for i in range(len(prior) - period - 1, len(prior))]
        log_rets = [math.log(prices[i+1] / prices[i]) for i in range(len(prices) - 1)]
        mean = sum(log_rets) / len(log_rets)
        variance = sum((r - mean) ** 2 for r in log_rets) / len(log_rets)
        return math.sqrt(variance) * math.sqrt(252) * 100.0

    def _dd_pct(self) -> float:
        """Current drawdown from equity curve peak."""
        if not self.equity_curve:
            return 0.0
        peak = max(e for _, e in self.equity_curve)
        current = self.capital
        if peak <= 0:
            return 0.0
        return (current - peak) / peak * 100.0

    def _regime_check(self, entry_date: str, spot: float) -> Tuple[bool, str]:
        """
        Check regime filters.
        Returns (allowed: bool, ma_direction: str).
        ma_direction: "bull" | "bear" | "neutral" — used for adaptive IC.
        """
        rf = self.cfg.get("regime_filter", "none")
        ma_period = int(self.cfg.get("ma_period", 50))

        ma = self._ma(entry_date, ma_period)
        ma_direction = "neutral"
        if ma is not None:
            ratio = spot / ma
            if ratio > 1.02:
                ma_direction = "bull"
            elif ratio < 0.98:
                ma_direction = "bear"

        if rf == "none":
            return True, ma_direction

        if rf in ("ma20", "ma50", "ma200"):
            period = {"ma20": 20, "ma50": 50, "ma200": 200}[rf]
            m = self._ma(entry_date, period)
            if m is None:
                return False, ma_direction
            return spot >= m, ma_direction

        if rf == "vol_filter":
            rv = self._realized_vol(entry_date, 10)
            if rv is not None and rv > 80.0:
                return False, ma_direction
            return True, ma_direction

        if rf == "dd_cb":
            if self._dd_pct() < -10.0:
                return False, ma_direction
            return True, ma_direction

        return True, ma_direction

    # ──────────────────────────────────────────────────────────────────────────
    # Position sizing
    # ──────────────────────────────────────────────────────────────────────────

    def _kelly_risk_pct(self) -> float:
        """
        Compute fractional-Kelly risk per trade from trade history.
        Falls back to cfg["risk_pct"] when insufficient history.
        """
        kf = self.cfg.get("kelly_fraction", 0.0)
        if kf <= 0:
            return self.cfg["risk_pct"]

        min_trades = int(self.cfg.get("kelly_min_trades", 10))
        if len(self.trades) < min_trades:
            return self.cfg["risk_pct"]

        recent = self.trades[-40:]  # rolling 40-trade window
        wins   = [t for t in recent if t["win"]]
        losers = [t for t in recent if not t["win"]]

        if not wins or not losers:
            return self.cfg["risk_pct"]

        win_rate = len(wins) / len(recent)
        avg_win_pct  = sum(t["pnl_pct"] for t in wins)  / len(wins)
        avg_loss_pct = sum(abs(t["pnl_pct"]) for t in losers) / len(losers)

        if avg_win_pct <= 0 or avg_loss_pct <= 0:
            return self.cfg["risk_pct"]

        # Full Kelly = WR/avg_loss - (1-WR)/avg_win
        b = avg_win_pct / avg_loss_pct  # win/loss ratio
        full_kelly = (win_rate * b - (1 - win_rate)) / b
        full_kelly = max(0.0, full_kelly)

        fractional_kelly = full_kelly * kf
        # Clamp: never risk more than 3× the base risk_pct or less than 0.5%
        clamped = max(0.005, min(fractional_kelly, self.cfg["risk_pct"] * 3.0))
        log.debug("Kelly: WR=%.1f%% b=%.2f full=%.3f frac=%.3f clamped=%.3f",
                  win_rate * 100, b, full_kelly, fractional_kelly, clamped)
        return clamped

    def _size_contracts(self, max_loss_per_contract_usd: float) -> int:
        """Compute n_contracts from Kelly/flat risk and account size."""
        if max_loss_per_contract_usd <= 0:
            return 0
        risk_pct = self._kelly_risk_pct()
        base = self.capital if self.cfg["compound"] else self.starting_capital
        budget = base * risk_pct
        n = int(budget / max_loss_per_contract_usd)
        return max(1, min(n, int(self.cfg["max_contracts"])))

    # ──────────────────────────────────────────────────────────────────────────
    # Spread finders
    # ──────────────────────────────────────────────────────────────────────────

    def _find_bull_put(
        self,
        puts: List[Dict],
        spot: float,
        otm_pct: float,
        width: float,
        min_credit_pct: float,
    ) -> Optional[Dict]:
        target_short = spot * (1.0 - otm_pct)
        strikes = [p["strike"] for p in puts]
        short_cands = [s for s in strikes if s <= target_short * 1.02]
        if not short_cands:
            return None
        short_strike = max(short_cands)
        long_cands = [s for s in strikes if s <= short_strike - width and s < short_strike]
        if not long_cands:
            return None
        long_strike = max(long_cands)
        if long_strike >= short_strike:
            return None
        sp = next((p["price"] for p in puts if p["strike"] == short_strike), None)
        lp = next((p["price"] for p in puts if p["strike"] == long_strike), None)
        if sp is None or lp is None or sp <= 0 or lp < 0 or lp >= sp:
            return None
        credit = sp - lp
        sw = short_strike - long_strike
        if credit / sw * 100.0 < min_credit_pct:
            return None
        return {
            "type": "bull_put",
            "short_strike": short_strike,
            "long_strike":  long_strike,
            "short_price":  sp,
            "long_price":   lp,
            "credit":       credit,
            "spread_width": sw,
            "max_loss":     sw - credit,
        }

    def _find_bear_call(
        self,
        calls: List[Dict],
        spot: float,
        otm_pct: float,
        width: float,
        min_credit_pct: float,
    ) -> Optional[Dict]:
        target_short = spot * (1.0 + otm_pct)
        strikes = [c["strike"] for c in calls]
        short_cands = [s for s in strikes if s >= target_short * 0.98]
        if not short_cands:
            return None
        short_strike = min(short_cands)
        long_cands = [s for s in strikes if s >= short_strike + width and s > short_strike]
        if not long_cands:
            return None
        long_strike = min(long_cands)
        if long_strike <= short_strike:
            return None
        sp = next((c["price"] for c in calls if c["strike"] == short_strike), None)
        lp = next((c["price"] for c in calls if c["strike"] == long_strike), None)
        if sp is None or lp is None or sp <= 0 or lp < 0 or lp >= sp:
            return None
        credit = sp - lp
        sw = long_strike - short_strike
        if credit / sw * 100.0 < min_credit_pct:
            return None
        return {
            "type": "bear_call",
            "short_strike": short_strike,
            "long_strike":  long_strike,
            "short_price":  sp,
            "long_price":   lp,
            "credit":       credit,
            "spread_width": sw,
            "max_loss":     sw - credit,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Entry
    # ──────────────────────────────────────────────────────────────────────────

    def _resolve_direction_and_scales(
        self, direction: str, ma_direction: str
    ) -> Tuple[str, float, float, float, float]:
        """
        Returns (resolved_direction, put_otm_scale, call_otm_scale, put_w_scale, call_w_scale).
        For "adaptive", choose direction based on ma_direction.
        For IC with adaptive scales, apply bull/bear multipliers.
        """
        put_os = call_os = put_ws = call_ws = 1.0

        if direction == "adaptive":
            if ma_direction == "bull":
                resolved = "iron_condor"
                put_os  = self.cfg["adaptive_bull_put_otm_scale"]
                call_os = self.cfg["adaptive_bull_call_otm_scale"]
                put_ws  = self.cfg["adaptive_bull_width_scale"]
                call_ws = 1.0 / self.cfg["adaptive_bull_width_scale"]
            elif ma_direction == "bear":
                resolved = "iron_condor"
                put_os  = self.cfg["adaptive_bear_put_otm_scale"]
                call_os = self.cfg["adaptive_bear_call_otm_scale"]
                put_ws  = self.cfg["adaptive_bear_width_scale"]
                call_ws = 1.0 / self.cfg["adaptive_bear_width_scale"]
            else:
                resolved = "iron_condor"  # neutral → symmetric IC
        else:
            resolved = direction

        return resolved, put_os, call_os, put_ws, call_ws

    def _try_enter(
        self,
        conn: sqlite3.Connection,
        entry_date: str,
        expiry: str,
    ) -> Optional[dict]:
        spot = self._spot(entry_date)
        if not spot:
            return None

        today    = datetime.strptime(entry_date, "%Y-%m-%d").date()
        exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        dte      = (exp_date - today).days

        allowed, ma_direction = self._regime_check(entry_date, spot)
        if not allowed:
            return None

        direction = self.cfg["direction"]
        resolved, put_os, call_os, put_ws, call_ws = self._resolve_direction_and_scales(
            direction, ma_direction
        )

        put_otm    = self.cfg["otm_pct"]      * put_os
        call_otm   = (self.cfg.get("call_otm_pct") or self.cfg["otm_pct"]) * call_os
        put_width  = self.cfg["spread_width"] * put_ws
        call_width = (self.cfg.get("call_spread_width") or self.cfg["spread_width"]) * call_ws
        min_cred   = self.cfg["min_credit_pct"]

        bp = bc = None

        if resolved in ("bull_put", "iron_condor"):
            puts = self._get_options(conn, expiry, "put", entry_date)
            bp = self._find_bull_put(puts, spot, put_otm, put_width, min_cred)
            if resolved == "bull_put" and bp is None:
                return None

        if resolved in ("bear_call", "iron_condor"):
            calls = self._get_options(conn, expiry, "call", entry_date)
            bc = self._find_bear_call(calls, spot, call_otm, call_width, min_cred)
            if resolved == "bear_call" and bc is None:
                return None
            # IC: bear-call is optional (bull-put required; add call side if available)

        if resolved == "iron_condor" and bp is None:
            return None

        total_credit   = (bp["credit"]   if bp else 0.0) + (bc["credit"]   if bc else 0.0)
        total_max_loss = (bp["max_loss"] if bp else 0.0) + (bc["max_loss"] if bc else 0.0)

        if total_max_loss <= 0:
            return None

        max_loss_per_contract = total_max_loss * MULTIPLIER
        n_contracts = self._size_contracts(max_loss_per_contract)

        account_base = self.capital if self.cfg["compound"] else self.starting_capital
        position = {
            "entry_date":     entry_date,
            "expiry":         expiry,
            "dte_at_entry":   dte,
            "spot_at_entry":  spot,
            "n_contracts":    n_contracts,
            "direction":      resolved,
            "ma_direction":   ma_direction,

            # Bull-put leg
            "bp_short_strike": bp["short_strike"] if bp else None,
            "bp_long_strike":  bp["long_strike"]  if bp else None,
            "bp_credit":       bp["credit"]        if bp else 0.0,
            "bp_max_loss":     bp["max_loss"]      if bp else 0.0,

            # Bear-call leg
            "bc_short_strike": bc["short_strike"] if bc else None,
            "bc_long_strike":  bc["long_strike"]  if bc else None,
            "bc_credit":       bc["credit"]        if bc else 0.0,
            "bc_max_loss":     bc["max_loss"]      if bc else 0.0,

            "total_credit":   total_credit,
            "total_max_loss": total_max_loss,

            # Exit thresholds (per-share spread values)
            "profit_target_price": total_credit * (1.0 - self.cfg["profit_target"]),
            "stop_loss_price":     total_credit * self.cfg["stop_loss_mult"],

            "status":        "open",
            "unrealized_pnl": 0.0,
        }

        log.debug(
            "%s ENTRY exp=%s dte=%d dir=%s ma=%s bp=%s/%s bc=%s/%s credit=%.3f×%d",
            entry_date, expiry, dte, resolved, ma_direction,
            bp["short_strike"] if bp else "-", bp["long_strike"] if bp else "-",
            bc["short_strike"] if bc else "-", bc["long_strike"] if bc else "-",
            total_credit, n_contracts,
        )
        return position

    # ──────────────────────────────────────────────────────────────────────────
    # Mark-to-market / exit
    # ──────────────────────────────────────────────────────────────────────────

    def _current_spread_value(
        self, conn: sqlite3.Connection, pos: dict, dt: str
    ) -> Optional[float]:
        """Current combined spread value (per share). None = no data."""
        expiry = pos["expiry"]
        bp_val = bc_val = 0.0

        if pos.get("bp_short_strike") is not None:
            sp = self._get_option_price(conn, expiry, pos["bp_short_strike"], "put", dt)
            lp = self._get_option_price(conn, expiry, pos["bp_long_strike"],  "put", dt)
            if sp is None or lp is None:
                return None
            bp_val = max(0.0, sp - lp)

        if pos.get("bc_short_strike") is not None:
            sc = self._get_option_price(conn, expiry, pos["bc_short_strike"], "call", dt)
            lc = self._get_option_price(conn, expiry, pos["bc_long_strike"],  "call", dt)
            if sc is None or lc is None:
                return None
            bc_val = max(0.0, sc - lc)

        return bp_val + bc_val

    def _check_exit(
        self, conn: sqlite3.Connection, pos: dict, current_date: str
    ) -> Optional[Tuple[float, str]]:
        sv = self._current_spread_value(conn, pos, current_date)
        if sv is None:
            return None

        pnl_per_share = pos["total_credit"] - sv
        pos["unrealized_pnl"] = pnl_per_share * pos["n_contracts"] * MULTIPLIER

        if sv <= pos["profit_target_price"]:
            pnl_usd = pnl_per_share * pos["n_contracts"] * MULTIPLIER
            return pnl_usd, "profit_target"
        if sv >= pos["stop_loss_price"]:
            pnl_usd = pnl_per_share * pos["n_contracts"] * MULTIPLIER
            return pnl_usd, "stop_loss"
        return None

    def _intrinsic_spread(self, pos: dict, spot: float) -> float:
        """Expiry intrinsic value of combined spread."""
        bp_val = 0.0
        if pos.get("bp_short_strike") is not None:
            bp_val = max(0.0, pos["bp_short_strike"] - spot) - max(0.0, pos["bp_long_strike"] - spot)
            bp_val = max(0.0, bp_val)
        bc_val = 0.0
        if pos.get("bc_short_strike") is not None:
            bc_val = max(0.0, spot - pos["bc_short_strike"]) - max(0.0, spot - pos["bc_long_strike"])
            bc_val = max(0.0, bc_val)
        return bp_val + bc_val

    def _close_at_expiry(
        self, conn: sqlite3.Connection, pos: dict
    ) -> Tuple[float, str]:
        expiry = pos["expiry"]
        spot = self._spot(expiry) or pos["spot_at_entry"]
        sv = self._current_spread_value(conn, pos, expiry)

        if sv is not None:
            pnl = (pos["total_credit"] - sv) * pos["n_contracts"] * MULTIPLIER
            return pnl, "expiry_real"

        # Intrinsic fallback
        intr = self._intrinsic_spread(pos, spot)
        pnl = (pos["total_credit"] - intr) * pos["n_contracts"] * MULTIPLIER
        return pnl, "expiry_intrinsic"

    # ──────────────────────────────────────────────────────────────────────────
    # Record close
    # ──────────────────────────────────────────────────────────────────────────

    def _record_close(
        self, pos: dict, exit_date: str, pnl_usd: float, reason: str
    ) -> None:
        self.capital += pnl_usd
        # pnl as % of max risk (for Kelly)
        max_risk = pos["total_max_loss"] * pos["n_contracts"] * MULTIPLIER
        pnl_pct = pnl_usd / max_risk if max_risk > 0 else 0.0

        self.trades.append({
            "entry_date":   pos["entry_date"],
            "exit_date":    exit_date,
            "expiry":       pos["expiry"],
            "dte_at_entry": pos["dte_at_entry"],
            "direction":    pos["direction"],
            "ma_direction": pos.get("ma_direction", "neutral"),
            "n_contracts":  pos["n_contracts"],
            "total_credit": pos["total_credit"],
            "total_max_loss": pos["total_max_loss"],
            "pnl_usd":      round(pnl_usd, 2),
            "pnl_pct":      round(pnl_pct, 4),
            "exit_reason":  reason,
            "win":          pnl_usd > 0,
        })
        pos["status"] = "closed"
        log.debug(
            "%s EXIT %s %s pnl=$%.0f reason=%s",
            exit_date, pos["entry_date"], pos["expiry"], pnl_usd, reason,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Main run loop
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        Run backtest from start_date to end_date (inclusive).
        Returns results dict with full metrics and trade log.
        """
        self.capital          = self.cfg["starting_capital"]
        self.starting_capital = self.cfg["starting_capital"]
        self.open_positions   = []
        self.trades           = []
        self.equity_curve     = []
        self._ruin            = False

        conn = self._connect()
        self._load_spots(conn, start_date, end_date)

        dte_target = int(self.cfg["dte_target"])
        dte_min    = int(self.cfg["dte_min"])
        dte_max    = int(self.cfg.get("dte_max") or dte_target + 10)
        max_conc   = int(self.cfg["max_concurrent"])
        same_day   = bool(self.cfg.get("same_day_reentry", False))

        trading_days = self._trading_days(conn, start_date, end_date)

        for current_date in trading_days:
            if self._ruin:
                break

            today = datetime.strptime(current_date, "%Y-%m-%d").date()

            # ── 1. Close expired positions ─────────────────────────────────
            for pos in list(self.open_positions):
                if pos["status"] != "open":
                    continue
                exp_date = datetime.strptime(pos["expiry"], "%Y-%m-%d").date()
                if today >= exp_date:
                    pnl_usd, reason = self._close_at_expiry(conn, pos)
                    self._record_close(pos, pos["expiry"], pnl_usd, reason)

            self.open_positions = [p for p in self.open_positions if p["status"] == "open"]

            # ── 2. Check PT / SL on open positions ────────────────────────
            newly_closed = []
            for pos in list(self.open_positions):
                result = self._check_exit(conn, pos, current_date)
                if result:
                    pnl_usd, reason = result
                    self._record_close(pos, current_date, pnl_usd, reason)
                    newly_closed.append(pos)

            self.open_positions = [p for p in self.open_positions if p["status"] == "open"]

            # ── 3. Open new positions if capacity available ────────────────
            if not self._ruin:
                # Same-day re-entry: if we just closed via PT, immediately try to fill capacity
                # Also runs on normal days when below capacity
                self._fill_positions(conn, current_date, dte_min, dte_max, max_conc)

                # Same-day re-entry pass: run again only if PT closes happened
                if same_day and newly_closed:
                    pt_closes = [p for p in newly_closed if p["status"] == "closed"]
                    if pt_closes and len(self.open_positions) < max_conc:
                        self._fill_positions(conn, current_date, dte_min, dte_max, max_conc)

            # ── 4. Equity curve ───────────────────────────────────────────
            unrealized = sum(p.get("unrealized_pnl", 0.0) for p in self.open_positions)
            self.equity_curve.append((current_date, self.capital + unrealized))

            if self.capital <= 0:
                self._ruin = True
                log.warning("RUIN on %s capital=%.0f", current_date, self.capital)

        conn.close()
        return self._build_results(start_date, end_date)

    def _fill_positions(
        self,
        conn: sqlite3.Connection,
        current_date: str,
        dte_min: int,
        dte_max: int,
        max_conc: int,
    ) -> None:
        """
        Try to open new positions until max_concurrent is reached.
        Attempts each available expiry in order of proximity to dte_target.
        Already-used expiries for open positions are skipped to avoid duplicates.
        """
        if len(self.open_positions) >= max_conc:
            return

        open_expiries = {p["expiry"] for p in self.open_positions}
        expiries = self._available_expiries(conn, current_date, dte_min, dte_max)

        for exp_str, dte in expiries:
            if len(self.open_positions) >= max_conc:
                break
            if exp_str in open_expiries:
                continue  # already have a position on this expiry
            pos = self._try_enter(conn, current_date, exp_str)
            if pos:
                self.open_positions.append(pos)
                open_expiries.add(exp_str)

    # ──────────────────────────────────────────────────────────────────────────
    # Results
    # ──────────────────────────────────────────────────────────────────────────

    def _build_results(self, start_date: str, end_date: str) -> Dict[str, Any]:
        trades   = self.trades
        n_trades = len(trades)

        final_cap  = self.capital
        return_pct = (final_cap - self.starting_capital) / self.starting_capital * 100.0

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt   = datetime.strptime(end_date,   "%Y-%m-%d")
        days     = max(1, (end_dt - start_dt).days)
        years    = days / 365.25
        ann_return = (
            ((final_cap / self.starting_capital) ** (1.0 / years) - 1.0) * 100.0
            if years > 0 and self.starting_capital > 0 else 0.0
        )

        if self.equity_curve:
            equities = [e for _, e in self.equity_curve]
            peak = equities[0]
            max_dd = 0.0
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (eq - peak) / peak * 100.0 if peak > 0 else 0.0
                if dd < max_dd:
                    max_dd = dd
        else:
            max_dd = 0.0

        wins   = [t for t in trades if t["win"]]
        losers = [t for t in trades if not t["win"]]
        win_rate = len(wins) / n_trades * 100.0 if n_trades > 0 else 0.0
        avg_win  = sum(t["pnl_usd"] for t in wins)  / len(wins)   if wins   else 0.0
        avg_loss = sum(abs(t["pnl_usd"]) for t in losers) / len(losers) if losers else 0.0
        gross_win  = sum(t["pnl_usd"] for t in wins)   if wins   else 0.0
        gross_loss = sum(t["pnl_usd"] for t in losers) if losers else 0.0
        profit_factor = (
            abs(gross_win / gross_loss) if gross_loss != 0 else 999.0
        )

        # Monthly breakdown
        month_stats = self._monthly_breakdown(trades)

        return {
            "start_date":      start_date,
            "end_date":        end_date,
            "days":            days,
            "years":           round(years, 3),
            "return_pct":      round(return_pct, 2),
            "ann_return":      round(ann_return, 2),
            "max_drawdown":    round(max_dd, 2),
            "total_trades":    n_trades,
            "win_rate":        round(win_rate, 2),
            "avg_win":         round(avg_win, 2),
            "avg_loss":        round(avg_loss, 2),
            "profit_factor":   round(profit_factor, 4),
            "ending_capital":  round(final_cap, 2),
            "ruin":            self._ruin,
            "month_stats":     month_stats,
            "trades":          trades,
        }

    def _monthly_breakdown(self, trades: List[dict]) -> Dict[str, dict]:
        months: Dict[str, list] = {}
        for t in trades:
            ym = t["entry_date"][:7]
            months.setdefault(ym, []).append(t)
        result = {}
        for ym, ts in sorted(months.items()):
            wins = [t for t in ts if t["win"]]
            result[ym] = {
                "trades":   len(ts),
                "wins":     len(wins),
                "win_rate": round(len(wins) / len(ts) * 100, 1) if ts else 0.0,
                "pnl_usd":  round(sum(t["pnl_usd"] for t in ts), 2),
            }
        return result
