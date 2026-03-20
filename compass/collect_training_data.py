#!/usr/bin/env python3
"""
EXP-500 Phase 1 — ML Training Data Collection

Runs the EXP-400 backtest (credit_spread + iron_condor on SPY, 2020-2025)
and captures EVERY trade with full market context as ML training data.

Output:
  ml/training_data.csv   — Chronological trade-level dataset
  ml/feature_analysis.md — Feature distributions and signal quality patterns

Usage:
    cd /home/node/openclaw/workspace/pilotai-credit-spreads
    PYTHONPATH=. python3 ml/collect_training_data.py
"""

import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ── Paths ───────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.portfolio_backtester import PortfolioBacktester
from strategies import STRATEGY_REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ml_data")

# ── Config ──────────────────────────────────────────────────────────────────
CHAMPION_PATH = ROOT / "configs" / "champion.json"
OUTPUT_DIR = ROOT / "ml"
TICKERS = ["SPY"]
STARTING_CAPITAL = 100_000
YEARS = list(range(2020, 2026))


def load_champion_params() -> Dict:
    """Load strategy_params from champion.json."""
    with open(CHAMPION_PATH) as f:
        return json.load(f)["strategy_params"]


def run_year_backtest(year: int) -> Tuple[PortfolioBacktester, Dict]:
    """Run CS + IC backtest for one year, return (backtester, results)."""
    params = load_champion_params()

    cs_params = dict(params["credit_spread"])
    ic_params = dict(params["iron_condor"])

    cs_cls = STRATEGY_REGISTRY["credit_spread"]
    ic_cls = STRATEGY_REGISTRY["iron_condor"]

    cs_strategy = cs_cls(cs_params)
    ic_strategy = ic_cls(ic_params)

    bt = PortfolioBacktester(
        strategies=[
            ("credit_spread", cs_strategy),
            ("iron_condor", ic_strategy),
        ],
        tickers=TICKERS,
        start_date=datetime(year, 1, 1),
        end_date=datetime(year, 12, 31),
        starting_capital=STARTING_CAPITAL,
        max_positions=10,
        max_positions_per_strategy=5,
    )
    raw = bt.run()
    combined = raw.get("combined", raw)
    return bt, combined


def _prev_val(d: dict, before_ts: pd.Timestamp, default):
    """Get the most recent value in dict d with key strictly < before_ts."""
    keys = [k for k in d if k < before_ts]
    return d[max(keys)] if keys else default


def _compute_vix_percentile(vix_series: pd.Series, date_ts: pd.Timestamp, window: int) -> float:
    """Compute VIX percentile rank over trailing window days."""
    if vix_series is None or date_ts not in vix_series.index:
        return 50.0
    # Get all dates up to and including this date
    hist = vix_series.loc[vix_series.index <= date_ts].tail(window)
    if len(hist) < 10:
        return 50.0
    current = float(vix_series.loc[date_ts])
    below = (hist < current).sum()
    return round((below / len(hist)) * 100, 2)


def _compute_ma(closes: pd.Series, date_ts: pd.Timestamp, period: int) -> Optional[float]:
    """Compute moving average at a specific date."""
    hist = closes.loc[closes.index <= date_ts]
    if len(hist) < period:
        return None
    return float(hist.tail(period).mean())


def _compute_ma_slope(closes: pd.Series, date_ts: pd.Timestamp, ma_period: int, lookback: int = 20) -> Optional[float]:
    """Compute annualized slope of a moving average (%)."""
    hist = closes.loc[closes.index <= date_ts]
    if len(hist) < ma_period + lookback:
        return None
    ma_now = float(hist.tail(ma_period).mean())
    earlier = hist.iloc[:-lookback]
    if len(earlier) < ma_period:
        return None
    ma_then = float(earlier.tail(ma_period).mean())
    if ma_then == 0:
        return 0.0
    pct_change = (ma_now - ma_then) / ma_then
    annualized = pct_change * (252 / lookback) * 100
    return round(annualized, 4)


def _compute_returns_vol(closes: pd.Series, date_ts: pd.Timestamp, window: int) -> Optional[float]:
    """Compute returns-based realized vol (annualized %) over trailing window."""
    hist = closes.loc[closes.index <= date_ts]
    if len(hist) < window + 1:
        return None
    returns = hist.pct_change().dropna().tail(window)
    if len(returns) < window:
        return None
    return round(float(returns.std() * math.sqrt(252) * 100), 4)


def enrich_trades(bt: PortfolioBacktester, year: int) -> List[Dict]:
    """Enrich closed trades with full market context."""
    enriched = []
    spy_data = bt._price_data.get("SPY")
    if spy_data is None or spy_data.empty:
        logger.warning("No SPY price data for year %d", year)
        return enriched

    spy_closes = spy_data["Close"]
    vix_series = bt._vix_series

    # Sort trades by entry date (chronological)
    sorted_trades = sorted(bt.closed_trades, key=lambda t: t.entry_date or datetime.min)

    prev_entry_date = None

    for trade in sorted_trades:
        if trade.entry_date is None or trade.exit_date is None:
            continue

        entry_dt = trade.entry_date
        exit_dt = trade.exit_date
        entry_ts = pd.Timestamp(entry_dt)

        # Strategy type
        strat_name = trade.strategy_name
        is_ic = "iron" in strat_name.lower() or "condor" in strat_name.lower()
        strategy_type = "IC" if is_ic else "CS"

        # Spread type from metadata
        spread_type = (trade.metadata or {}).get("spread_type", "unknown")

        # DTE at entry
        dte_at_entry = None
        if trade.legs:
            exp = trade.legs[0].expiration
            if exp:
                dte_at_entry = (exp - entry_dt).days

        # Hold duration
        hold_days = (exit_dt - entry_dt).days

        # Entry price context
        spy_price = None
        if entry_ts in spy_closes.index:
            spy_price = float(spy_closes.loc[entry_ts])
        elif len(spy_closes.loc[spy_closes.index <= entry_ts]) > 0:
            spy_price = float(spy_closes.loc[spy_closes.index <= entry_ts].iloc[-1])

        # Moving averages
        ma_20 = _compute_ma(spy_closes, entry_ts, 20)
        ma_50 = _compute_ma(spy_closes, entry_ts, 50)
        ma_80 = _compute_ma(spy_closes, entry_ts, 80)
        ma_200 = _compute_ma(spy_closes, entry_ts, 200)

        # Distance from MA (%)
        dist_ma_20 = round((spy_price - ma_20) / ma_20 * 100, 4) if spy_price and ma_20 else None
        dist_ma_50 = round((spy_price - ma_50) / ma_50 * 100, 4) if spy_price and ma_50 else None
        dist_ma_80 = round((spy_price - ma_80) / ma_80 * 100, 4) if spy_price and ma_80 else None
        dist_ma_200 = round((spy_price - ma_200) / ma_200 * 100, 4) if spy_price and ma_200 else None

        # MA slopes (annualized %)
        ma_20_slope = _compute_ma_slope(spy_closes, entry_ts, 20)
        ma_50_slope = _compute_ma_slope(spy_closes, entry_ts, 50)

        # VIX at entry
        vix_val = None
        if vix_series is not None and entry_ts in vix_series.index:
            vix_val = float(vix_series.loc[entry_ts])
        elif vix_series is not None:
            prior = vix_series.loc[vix_series.index <= entry_ts]
            if len(prior) > 0:
                vix_val = float(prior.iloc[-1])

        # VIX percentile ranks
        vix_pctile_20 = _compute_vix_percentile(vix_series, entry_ts, 20)
        vix_pctile_50 = _compute_vix_percentile(vix_series, entry_ts, 50)
        vix_pctile_100 = _compute_vix_percentile(vix_series, entry_ts, 100)

        # IV rank
        iv_rank = bt._iv_rank_by_date.get(entry_ts, None)
        if iv_rank is None:
            # Try nearest prior date
            prior_keys = [k for k in bt._iv_rank_by_date if k <= entry_ts]
            if prior_keys:
                iv_rank = bt._iv_rank_by_date[max(prior_keys)]

        # Realized vol (ATR-based, from backtester)
        rv_map = bt._realized_vol_by_date.get("SPY", {})
        realized_vol_atr = rv_map.get(entry_ts, None)
        if realized_vol_atr is None:
            prior_keys = [k for k in rv_map if k <= entry_ts]
            if prior_keys:
                realized_vol_atr = rv_map[max(prior_keys)]

        # Returns-based realized vol (5/10/20 day)
        rv_5d = _compute_returns_vol(spy_closes, entry_ts, 5)
        rv_10d = _compute_returns_vol(spy_closes, entry_ts, 10)
        rv_20d = _compute_returns_vol(spy_closes, entry_ts, 20)

        # RSI
        rsi_map = bt._rsi_by_date.get("SPY", {})
        rsi_val = rsi_map.get(entry_ts, None)
        if rsi_val is None:
            prior_keys = [k for k in rsi_map if k <= entry_ts]
            if prior_keys:
                rsi_val = rsi_map[max(prior_keys)]

        # Regime at entry
        regime = (trade.metadata or {}).get("regime", None)

        # Day of week (0=Mon, 4=Fri)
        day_of_week = entry_dt.weekday()

        # Days since last trade
        days_since_last = None
        if prev_entry_date is not None:
            days_since_last = (entry_dt - prev_entry_date).days
        prev_entry_date = entry_dt

        # Premium collected, spread width
        net_credit = trade.net_credit
        max_loss = trade.max_loss_per_unit

        # Spread width from legs
        spread_width = None
        if trade.legs and len(trade.legs) >= 2:
            strikes = sorted([leg.strike for leg in trade.legs])
            spread_width = strikes[-1] - strikes[0]
            # For IC with 4 legs, take max width between pairs
            if len(trade.legs) == 4:
                # IC: 2 spread widths
                spread_width = max(
                    abs(trade.legs[0].strike - trade.legs[1].strike),
                    abs(trade.legs[2].strike - trade.legs[3].strike),
                )

        # Short strike delta proxy (OTM distance)
        short_strike = None
        if trade.legs:
            short_legs = [l for l in trade.legs if "short" in l.leg_type.value]
            if short_legs:
                short_strike = short_legs[0].strike

        otm_pct = None
        if short_strike and spy_price:
            otm_pct = round(abs(spy_price - short_strike) / spy_price * 100, 4)

        # Contracts
        contracts = trade.contracts

        # Momentum (10-day return)
        mom_10d = None
        hist = spy_closes.loc[spy_closes.index <= entry_ts]
        if len(hist) >= 11:
            mom_10d = round((float(hist.iloc[-1]) - float(hist.iloc[-11])) / float(hist.iloc[-11]) * 100, 4)

        # 5-day return
        mom_5d = None
        if len(hist) >= 6:
            mom_5d = round((float(hist.iloc[-1]) - float(hist.iloc[-6])) / float(hist.iloc[-6]) * 100, 4)

        # OUTCOME
        pnl = trade.realized_pnl
        max_risk = max_loss * contracts * 100 if max_loss and contracts else 0
        return_pct = round((pnl / max_risk) * 100, 4) if max_risk > 0 else 0
        win = 1 if pnl > 0 else 0

        row = {
            # Identity
            "entry_date": entry_dt.strftime("%Y-%m-%d"),
            "exit_date": exit_dt.strftime("%Y-%m-%d"),
            "year": year,
            "strategy_type": strategy_type,
            "spread_type": spread_type,

            # Timing
            "dte_at_entry": dte_at_entry,
            "hold_days": hold_days,
            "day_of_week": day_of_week,
            "days_since_last_trade": days_since_last,

            # Regime & signals
            "regime": regime,
            "rsi_14": round(rsi_val, 2) if rsi_val is not None else None,
            "momentum_5d_pct": mom_5d,
            "momentum_10d_pct": mom_10d,

            # VIX
            "vix": round(vix_val, 2) if vix_val is not None else None,
            "vix_percentile_20d": vix_pctile_20,
            "vix_percentile_50d": vix_pctile_50,
            "vix_percentile_100d": vix_pctile_100,
            "iv_rank": round(iv_rank, 2) if iv_rank is not None else None,

            # Price & MAs
            "spy_price": round(spy_price, 2) if spy_price else None,
            "dist_from_ma20_pct": dist_ma_20,
            "dist_from_ma50_pct": dist_ma_50,
            "dist_from_ma80_pct": dist_ma_80,
            "dist_from_ma200_pct": dist_ma_200,
            "ma20_slope_ann_pct": ma_20_slope,
            "ma50_slope_ann_pct": ma_50_slope,

            # Volatility
            "realized_vol_atr20": round(realized_vol_atr * 100, 2) if realized_vol_atr else None,
            "realized_vol_5d": rv_5d,
            "realized_vol_10d": rv_10d,
            "realized_vol_20d": rv_20d,

            # Trade structure
            "net_credit": round(net_credit, 4) if net_credit else None,
            "spread_width": spread_width,
            "max_loss_per_unit": round(max_loss, 4) if max_loss else None,
            "short_strike": short_strike,
            "otm_pct": otm_pct,
            "contracts": contracts,

            # Outcome
            "exit_reason": trade.exit_reason,
            "pnl": round(pnl, 2),
            "return_pct": return_pct,
            "win": win,
        }

        enriched.append(row)

    return enriched


def generate_feature_analysis(df: pd.DataFrame) -> str:
    """Generate markdown feature analysis report."""
    lines = [
        "# EXP-500 Phase 1 — Feature Analysis",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Total trades:** {len(df)}",
        f"**Date range:** {df['entry_date'].min()} to {df['entry_date'].max()}",
        f"**Overall win rate:** {df['win'].mean() * 100:.1f}%",
        f"**Avg return per trade:** {df['return_pct'].mean():.2f}%",
        "",
        "---",
        "",
        "## 1. Feature Distributions",
        "",
    ]

    # Numeric columns for summary stats
    numeric_cols = [
        "dte_at_entry", "hold_days", "vix", "iv_rank",
        "spy_price", "dist_from_ma20_pct", "dist_from_ma80_pct",
        "dist_from_ma200_pct", "realized_vol_20d",
        "rsi_14", "momentum_10d_pct", "net_credit", "spread_width",
        "otm_pct", "return_pct",
    ]

    lines.append("| Feature | Count | Mean | Std | Min | 25% | 50% | 75% | Max |")
    lines.append("|---------|-------|------|-----|-----|-----|-----|-----|-----|")
    for col in numeric_cols:
        if col in df.columns:
            s = df[col].dropna()
            if len(s) > 0:
                desc = s.describe()
                lines.append(
                    f"| {col} | {int(desc['count'])} | {desc['mean']:.2f} | {desc['std']:.2f} | "
                    f"{desc['min']:.2f} | {desc['25%']:.2f} | {desc['50%']:.2f} | "
                    f"{desc['75%']:.2f} | {desc['max']:.2f} |"
                )

    # Strategy breakdown
    lines.extend([
        "",
        "## 2. Strategy Breakdown",
        "",
    ])
    for strat in df["strategy_type"].unique():
        subset = df[df["strategy_type"] == strat]
        lines.append(f"### {strat}")
        lines.append(f"- Trades: {len(subset)}")
        lines.append(f"- Win rate: {subset['win'].mean() * 100:.1f}%")
        lines.append(f"- Avg return: {subset['return_pct'].mean():.2f}%")
        lines.append(f"- Avg hold days: {subset['hold_days'].mean():.1f}")
        lines.append("")

    # Win rate by regime
    lines.extend([
        "## 3. Win Rate by Regime",
        "",
        "| Regime | Trades | Win Rate | Avg Return |",
        "|--------|--------|----------|------------|",
    ])
    for regime in sorted(df["regime"].dropna().unique()):
        subset = df[df["regime"] == regime]
        lines.append(
            f"| {regime} | {len(subset)} | {subset['win'].mean() * 100:.1f}% | "
            f"{subset['return_pct'].mean():.2f}% |"
        )

    # Win rate by DTE bucket
    lines.extend([
        "",
        "## 4. Win Rate by DTE Bucket",
        "",
        "| DTE Range | Trades | Win Rate | Avg Return |",
        "|-----------|--------|----------|------------|",
    ])
    dte_col = df["dte_at_entry"].dropna()
    if len(dte_col) > 0:
        bins = [0, 10, 15, 20, 30, 45, 100]
        labels = ["0-10", "11-15", "16-20", "21-30", "31-45", "46+"]
        df["dte_bucket"] = pd.cut(df["dte_at_entry"], bins=bins, labels=labels, right=True)
        for bucket in labels:
            subset = df[df["dte_bucket"] == bucket]
            if len(subset) > 0:
                lines.append(
                    f"| {bucket} | {len(subset)} | {subset['win'].mean() * 100:.1f}% | "
                    f"{subset['return_pct'].mean():.2f}% |"
                )

    # Win rate by VIX bucket
    lines.extend([
        "",
        "## 5. Win Rate by VIX Bucket",
        "",
        "| VIX Range | Trades | Win Rate | Avg Return |",
        "|-----------|--------|----------|------------|",
    ])
    vix_col = df["vix"].dropna()
    if len(vix_col) > 0:
        bins = [0, 15, 20, 25, 30, 40, 100]
        labels = ["<15", "15-20", "20-25", "25-30", "30-40", "40+"]
        df["vix_bucket"] = pd.cut(df["vix"], bins=bins, labels=labels, right=True)
        for bucket in labels:
            subset = df[df["vix_bucket"] == bucket]
            if len(subset) > 0:
                lines.append(
                    f"| {bucket} | {len(subset)} | {subset['win'].mean() * 100:.1f}% | "
                    f"{subset['return_pct'].mean():.2f}% |"
                )

    # Win rate by year
    lines.extend([
        "",
        "## 6. Win Rate by Year",
        "",
        "| Year | Trades | Win Rate | Avg Return | Total PnL |",
        "|------|--------|----------|------------|-----------|",
    ])
    for year in sorted(df["year"].unique()):
        subset = df[df["year"] == year]
        lines.append(
            f"| {year} | {len(subset)} | {subset['win'].mean() * 100:.1f}% | "
            f"{subset['return_pct'].mean():.2f}% | ${subset['pnl'].sum():,.0f} |"
        )

    # Exit reason breakdown
    lines.extend([
        "",
        "## 7. Exit Reason Breakdown",
        "",
        "| Exit Reason | Trades | Win Rate | Avg Return |",
        "|-------------|--------|----------|------------|",
    ])
    for reason in sorted(df["exit_reason"].dropna().unique()):
        subset = df[df["exit_reason"] == reason]
        lines.append(
            f"| {reason} | {len(subset)} | {subset['win'].mean() * 100:.1f}% | "
            f"{subset['return_pct'].mean():.2f}% |"
        )

    # Feature correlations with outcome
    lines.extend([
        "",
        "## 8. Feature Correlations with Win/Loss",
        "",
        "Pearson correlation between each feature and the binary win outcome:",
        "",
        "| Feature | Correlation | p-value (approx) |",
        "|---------|-------------|------------------|",
    ])
    corr_cols = [
        "vix", "iv_rank", "rsi_14", "dte_at_entry",
        "dist_from_ma20_pct", "dist_from_ma80_pct", "dist_from_ma200_pct",
        "realized_vol_20d", "momentum_10d_pct", "vix_percentile_50d",
        "otm_pct", "net_credit", "day_of_week",
    ]
    for col in corr_cols:
        if col in df.columns:
            valid = df[[col, "win"]].dropna()
            if len(valid) > 5:
                corr = valid[col].corr(valid["win"])
                n = len(valid)
                # Approximate t-statistic for significance
                if abs(corr) < 1:
                    t_stat = corr * math.sqrt(n - 2) / math.sqrt(1 - corr**2)
                    # Two-tailed p-value approximation
                    p_approx = "< 0.05" if abs(t_stat) > 2.0 else ">= 0.05"
                else:
                    p_approx = "< 0.01"
                lines.append(f"| {col} | {corr:+.4f} | {p_approx} |")

    # Key signal quality patterns
    lines.extend([
        "",
        "## 9. Signal Quality Patterns",
        "",
    ])

    # High VIX vs low VIX
    if len(vix_col) > 0:
        median_vix = vix_col.median()
        low_vix = df[df["vix"] <= median_vix]
        high_vix = df[df["vix"] > median_vix]
        lines.append(f"### VIX Split (median = {median_vix:.1f})")
        lines.append(f"- Low VIX (n={len(low_vix)}): WR={low_vix['win'].mean()*100:.1f}%, "
                      f"Avg ret={low_vix['return_pct'].mean():.2f}%")
        lines.append(f"- High VIX (n={len(high_vix)}): WR={high_vix['win'].mean()*100:.1f}%, "
                      f"Avg ret={high_vix['return_pct'].mean():.2f}%")
        lines.append("")

    # Trend filter effectiveness
    if "dist_from_ma80_pct" in df.columns:
        above_ma = df[df["dist_from_ma80_pct"] > 0]
        below_ma = df[df["dist_from_ma80_pct"] <= 0]
        if len(above_ma) > 0 and len(below_ma) > 0:
            lines.append("### Price vs 80-day MA (trend filter)")
            lines.append(f"- Above MA80 (n={len(above_ma)}): WR={above_ma['win'].mean()*100:.1f}%, "
                          f"Avg ret={above_ma['return_pct'].mean():.2f}%")
            lines.append(f"- Below MA80 (n={len(below_ma)}): WR={below_ma['win'].mean()*100:.1f}%, "
                          f"Avg ret={below_ma['return_pct'].mean():.2f}%")
            lines.append("")

    # Day of week effect
    lines.append("### Day of Week Effect")
    lines.append("| Day | Trades | Win Rate | Avg Return |")
    lines.append("|-----|--------|----------|------------|")
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    for dow in range(5):
        subset = df[df["day_of_week"] == dow]
        if len(subset) > 0:
            lines.append(
                f"| {day_names[dow]} | {len(subset)} | {subset['win'].mean()*100:.1f}% | "
                f"{subset['return_pct'].mean():.2f}% |"
            )

    lines.extend([
        "",
        "---",
        "",
        "*Generated by ml/collect_training_data.py — EXP-500 Phase 1*",
    ])

    return "\n".join(lines)


def _download_full_spy_history() -> Tuple[pd.DataFrame, pd.Series]:
    """Download full SPY + VIX history (2018-2026) for feature computation.

    Returns (spy_ohlcv, vix_series) with enough history for MA200 warmup.
    """
    import yfinance as yf

    logger.info("Downloading full SPY history (2018-2026) for feature computation...")
    spy = yf.download("SPY", start="2018-01-01", end="2026-01-01", progress=False, auto_adjust=True)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if spy.index.tz is not None:
        spy.index = spy.index.tz_localize(None)

    vix_raw = yf.download("^VIX", start="2018-01-01", end="2026-01-01", progress=False, auto_adjust=True)
    if isinstance(vix_raw.columns, pd.MultiIndex):
        vix_raw.columns = vix_raw.columns.get_level_values(0)
    vix = vix_raw["Close"].dropna()
    if vix.index.tz is not None:
        vix.index = vix.index.tz_localize(None)

    logger.info("SPY: %d rows, VIX: %d rows", len(spy), len(vix))
    return spy, vix


def main():
    t0 = time.time()
    logger.info("EXP-500 Phase 1 — ML Training Data Collection")
    logger.info("Running EXP-400 backtest (CS + IC on SPY, %d-%d)", YEARS[0], YEARS[-1])

    # Download full history once for accurate MA200 + VIX percentiles
    full_spy, full_vix = _download_full_spy_history()

    all_trades = []

    for year in YEARS:
        logger.info("=" * 60)
        logger.info("Year %d", year)
        logger.info("=" * 60)

        bt, results = run_year_backtest(year)

        # Override the backtester's short-window data with full history
        bt._price_data["SPY"] = full_spy
        bt._vix_series = full_vix

        trades = enrich_trades(bt, year)
        logger.info(
            "Year %d: %d trades, return=%.2f%%, WR=%.1f%%",
            year,
            len(trades),
            results.get("return_pct", 0),
            results.get("win_rate", 0),
        )
        all_trades.extend(trades)

    # Build DataFrame (chronological — NO shuffling)
    df = pd.DataFrame(all_trades)

    # Sort by entry date to ensure strict chronological order
    df = df.sort_values("entry_date").reset_index(drop=True)

    # Save CSV
    csv_path = OUTPUT_DIR / "training_data.csv"
    df.to_csv(csv_path, index=False)
    logger.info("Saved %d trades to %s", len(df), csv_path)

    # Generate feature analysis
    analysis = generate_feature_analysis(df)
    analysis_path = OUTPUT_DIR / "feature_analysis.md"
    with open(analysis_path, "w") as f:
        f.write(analysis)
    logger.info("Saved feature analysis to %s", analysis_path)

    # Summary
    elapsed = time.time() - t0
    logger.info("")
    logger.info("=" * 60)
    logger.info("COLLECTION COMPLETE")
    logger.info("=" * 60)
    logger.info("Total trades: %d", len(df))
    logger.info("Date range: %s to %s", df["entry_date"].min(), df["entry_date"].max())
    logger.info("Strategy split: %s", df["strategy_type"].value_counts().to_dict())
    logger.info("Overall win rate: %.1f%%", df["win"].mean() * 100)
    logger.info("Elapsed: %.1f seconds", elapsed)


if __name__ == "__main__":
    main()
