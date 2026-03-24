#!/usr/bin/env python3
"""
Backtest Ensemble vs XGBoost — P&L impact comparison.

Runs the champion config backtest on 2020-2025 (real Polygon/IronVault data),
then retroactively evaluates each ML model on every trade to measure the P&L
impact of confidence gating.

Approach:
  1. Run full backtest (no ML gating) → all trades with features
  2. For each model variant, predict on every trade's features
  3. Apply confidence threshold → determine which trades survive gating
  4. Recompute per-year P&L, Sharpe, win rate, max drawdown for gated subset
  5. Generate comparison HTML report

This measures what matters: not just AUC, but actual dollar impact.

Usage:
    python scripts/backtest_ensemble_vs_xgboost.py
    python scripts/backtest_ensemble_vs_xgboost.py --years 2023-2025
    python scripts/backtest_ensemble_vs_xgboost.py --threshold 0.25
"""

import argparse
import json
import logging
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bt_compare")
log.setLevel(logging.INFO)

ANALYSIS_DIR = Path("/home/node/.openclaw/workspace/analysis")
OUTPUT_HTML = ANALYSIS_DIR / "backtest_ensemble_vs_xgboost.html"

# Champion params — the validated config that EXP-400 runs in production.
# Matches configs/champion.json → credit_spread section (flat params format).
CHAMPION_PARAMS = {
    "direction":            "both",
    "regime_mode":          "combo",
    "regime_config": {
        "signals": ["price_vs_ma200", "rsi_momentum", "vix_structure"],
        "ma_slow_period": 80,
        "ma200_neutral_band_pct": 0.5,
    },
    "trend_ma_period":      80,
    "target_dte":           15,
    "min_dte":              15,
    "otm_pct":              0.02,
    "spread_width":         12.0,
    "use_delta_selection":  False,
    "target_delta":         0.12,
    "min_credit_pct":       5,
    "stop_loss_multiplier": 1.25,
    "profit_target":        55,
    "max_risk_per_trade":   8.5,
    "max_contracts":        25,
    "sizing_mode":          "flat",
    "compound":             False,
    "momentum_filter_pct":  2.0,
    "drawdown_cb_pct":      40,
    "iron_condor_enabled":  True,
    "ic_min_combined_credit_pct": 25,
    "ic_neutral_regime_only": False,
    "ic_risk_per_trade":    3.5,
}


# ── Feature builder ──────────────────────────────────────────────────────────

def build_trade_features(trade: dict, price_cache: dict, vix_cache: dict) -> Optional[dict]:
    """Build the feature vector for a single historical trade.

    Reconstructs the features that were available on the trade's entry date,
    using cached price/VIX data. Returns None if data is insufficient.
    """
    entry_date = trade.get("entry_date")
    if entry_date is None:
        return None

    if isinstance(entry_date, str):
        entry_date = pd.Timestamp(entry_date)
    elif isinstance(entry_date, datetime):
        entry_date = pd.Timestamp(entry_date)

    entry_ts = entry_date.normalize()

    features = {}

    # ── Trade-level features
    features["dte_at_entry"] = trade.get("dte_at_entry", 0)
    if features["dte_at_entry"] == 0 and trade.get("expiration") and entry_date:
        exp = pd.Timestamp(trade["expiration"])
        features["dte_at_entry"] = max(0, (exp - entry_ts).days)

    features["day_of_week"] = entry_ts.dayofweek
    features["credit"] = trade.get("credit", 0)
    features["contracts"] = trade.get("contracts", 1)
    features["spread_width"] = trade.get("spread_width", CHAMPION_PARAMS["spread_width"])

    # Strategy type one-hot
    trade_type = (trade.get("type") or "").lower()
    features["strategy_type_CS"] = 1 if "put" in trade_type or "call" in trade_type else 0
    features["strategy_type_IC"] = 1 if "condor" in trade_type else 0
    features["strategy_type_SS"] = 0  # no straddle/strangle in champion

    # ── Price-derived features (from SPY cache)
    spy = price_cache.get("SPY")
    if spy is None or spy.empty:
        return None

    # Find the closest date at or before entry
    valid_dates = spy.index[spy.index <= entry_ts]
    if len(valid_dates) < 50:
        return None

    idx = valid_dates[-1]
    pos = spy.index.get_loc(idx)
    close = spy["Close"]

    current_price = float(close.iloc[pos])
    features["spy_price"] = current_price

    # Returns
    if pos >= 5:
        features["momentum_5d_pct"] = float((close.iloc[pos] / close.iloc[pos - 5] - 1) * 100)
    else:
        features["momentum_5d_pct"] = 0.0

    if pos >= 10:
        features["momentum_10d_pct"] = float((close.iloc[pos] / close.iloc[pos - 10] - 1) * 100)
    else:
        features["momentum_10d_pct"] = 0.0

    # Moving averages
    for window in [20, 50, 80, 200]:
        if pos >= window:
            ma = float(close.iloc[pos - window + 1:pos + 1].mean())
            features[f"dist_from_ma{window}_pct"] = float((current_price - ma) / ma * 100)
        else:
            features[f"dist_from_ma{window}_pct"] = 0.0

    # MA slopes
    for window in [20, 50]:
        if pos >= window + 20:
            ma_now = float(close.iloc[pos - window + 1:pos + 1].mean())
            ma_prev = float(close.iloc[pos - window - 19:pos - 19].mean())
            slope = (ma_now / ma_prev - 1) * (252 / 20) * 100
            features[f"ma{window}_slope_ann_pct"] = slope
        else:
            features[f"ma{window}_slope_ann_pct"] = 0.0

    # RSI(14)
    if pos >= 15:
        delta = close.iloc[pos - 14:pos + 1].diff()
        gain = delta.clip(lower=0).mean()
        loss = (-delta.clip(upper=0)).mean()
        if loss > 0:
            rs = gain / loss
            features["rsi_14"] = float(100 - 100 / (1 + rs))
        else:
            features["rsi_14"] = 100.0
    else:
        features["rsi_14"] = 50.0

    # Realized volatility
    for lookback in [5, 10, 20]:
        if pos >= lookback + 1:
            rets = close.iloc[pos - lookback:pos + 1].pct_change().dropna()
            features[f"realized_vol_{lookback}d"] = float(rets.std() * np.sqrt(252) * 100)
        else:
            features[f"realized_vol_{lookback}d"] = 20.0

    # ATR-based realized vol
    if pos >= 20:
        h = spy["High"].iloc[pos - 19:pos + 1]
        l = spy["Low"].iloc[pos - 19:pos + 1]
        c = close.iloc[pos - 19:pos + 1]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.mean())
        features["realized_vol_atr20"] = atr / current_price * np.sqrt(252) * 100
    else:
        features["realized_vol_atr20"] = 20.0

    # ── VIX features
    vix = vix_cache.get("VIX")
    if vix is not None and not vix.empty:
        vix_valid = vix.index[vix.index <= entry_ts]
        if len(vix_valid) > 0:
            vix_pos = vix.index.get_loc(vix_valid[-1])
            features["vix"] = float(vix["Close"].iloc[vix_pos])

            # VIX percentiles
            for window in [20, 50, 100]:
                if vix_pos >= window:
                    vix_window = vix["Close"].iloc[vix_pos - window + 1:vix_pos + 1]
                    pct = float((vix_window < features["vix"]).mean() * 100)
                    features[f"vix_percentile_{window}d"] = pct
                else:
                    features[f"vix_percentile_{window}d"] = 50.0
        else:
            features["vix"] = 20.0
            for w in [20, 50, 100]:
                features[f"vix_percentile_{w}d"] = 50.0
    else:
        features["vix"] = 20.0
        for w in [20, 50, 100]:
            features[f"vix_percentile_{w}d"] = 50.0

    # IV rank (approximated from VIX percentile)
    features["iv_rank"] = features.get("vix_percentile_100d", 50.0)

    # Regime one-hot (derived from VIX + trend)
    vix_val = features["vix"]
    trend = features.get("dist_from_ma200_pct", 0)
    for regime in ["bull", "bear", "high_vol", "low_vol", "crash"]:
        features[f"regime_{regime}"] = 0
    if vix_val > 40 and trend < -5:
        features["regime_crash"] = 1
    elif vix_val > 30:
        features["regime_high_vol"] = 1
    elif vix_val > 25 and trend < 0:
        features["regime_bear"] = 1
    elif vix_val < 15 and abs(trend) < 3:
        features["regime_low_vol"] = 1
    else:
        features["regime_bull"] = 1

    # Days since last trade (approximate)
    features["days_since_last_trade"] = 1

    return features


# ── ML model loading ─────────────────────────────────────────────────────────

def load_models() -> Dict[str, object]:
    """Load all available ML models. Returns {name: model_instance}."""
    models = {}

    # XGBoost baseline
    try:
        from compass.signal_model import SignalModel
        xgb_model = SignalModel(model_dir=str(ROOT / "ml" / "models"))
        if xgb_model.load():
            models["XGBoost Baseline"] = xgb_model
            log.info("Loaded XGBoost baseline (%d features)", len(xgb_model.feature_names or []))
        else:
            log.warning("XGBoost model not found in ml/models/")
    except Exception as e:
        log.warning("Failed to load XGBoost: %s", e)

    # Ensemble 3-model
    try:
        from compass.ensemble_signal_model import EnsembleSignalModel
        ens_model = EnsembleSignalModel(model_dir=str(ROOT / "ml" / "models"))
        if ens_model.load():
            models["Ensemble 3-Model"] = ens_model
            log.info("Loaded Ensemble 3-model (%d features)", len(ens_model.feature_names or []))
        else:
            log.warning("Ensemble model not found in ml/models/")
    except Exception as e:
        log.warning("Failed to load Ensemble: %s", e)

    return models


# ── Gated P&L calculation ────────────────────────────────────────────────────

def compute_gated_metrics(
    trades: List[dict],
    predictions: List[dict],
    threshold: float,
    starting_capital: float = 100_000,
) -> dict:
    """Recompute P&L metrics for trades that survive ML confidence gating.

    A trade is kept if:
      - The model returned a fallback prediction (model unavailable → pass through)
      - confidence >= threshold

    Returns a dict matching the backtester's result format.
    """
    kept_trades = []
    filtered_count = 0

    for trade, pred in zip(trades, predictions):
        if pred is None:
            kept_trades.append(trade)
            continue
        is_fallback = pred.get("fallback", False)
        confidence = pred.get("confidence", 0.0)
        if is_fallback or confidence >= threshold:
            kept_trades.append(trade)
        else:
            filtered_count += 1

    if not kept_trades:
        return {
            "total_trades": 0, "kept_trades": 0, "filtered_trades": filtered_count,
            "total_pnl": 0, "return_pct": 0, "win_rate": 0, "sharpe_ratio": 0,
            "max_drawdown": 0, "avg_pnl_per_trade": 0,
        }

    # Replay capital curve
    capital = starting_capital
    peak = starting_capital
    worst_dd = 0.0
    daily_returns = []
    wins = 0

    for t in kept_trades:
        pnl = t.get("pnl", 0)
        capital += pnl
        if capital > peak:
            peak = capital
        dd = (capital - peak) / peak if peak > 0 else 0
        worst_dd = min(worst_dd, dd)
        if pnl > 0:
            wins += 1
        if capital > 0:
            daily_returns.append(pnl / max(capital - pnl, 1))

    total_pnl = capital - starting_capital
    return_pct = (total_pnl / starting_capital) * 100
    win_rate = (wins / len(kept_trades)) * 100

    # Sharpe from trade returns
    if len(daily_returns) >= 2:
        arr = np.array(daily_returns)
        sharpe = float(np.mean(arr) / np.std(arr) * np.sqrt(min(len(arr), 252))) if np.std(arr) > 0 else 0
    else:
        sharpe = 0.0

    return {
        "total_trades": len(kept_trades),
        "kept_trades": len(kept_trades),
        "filtered_trades": filtered_count,
        "total_pnl": round(total_pnl, 2),
        "return_pct": round(return_pct, 2),
        "win_rate": round(win_rate, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(worst_dd * 100, 2),
        "avg_pnl_per_trade": round(total_pnl / len(kept_trades), 2),
        "ending_capital": round(capital, 2),
    }


# ── Backtest runner ──────────────────────────────────────────────────────────

def run_backtest_year(year: int) -> Tuple[dict, List[dict]]:
    """Run backtest for a single year, return (results_dict, trades_list)."""
    from scripts.run_optimization import run_year
    result = run_year("SPY", year, CHAMPION_PARAMS, use_real_data=True)
    # Extract individual trades from backtester
    trades = result.get("_trades", [])
    if not trades:
        # Backtester stores trades on the instance — they're embedded in the result
        # under the monthly_pnl structure. Fall back to extracting from result.
        pass
    return result, trades


def run_full_backtest(years: List[int]) -> Tuple[dict, dict]:
    """Run backtest across all years. Returns (results_by_year, trades_by_year)."""
    from scripts.run_optimization import run_year

    results = {}
    all_trades = {}

    for year in years:
        t0 = time.time()
        log.info("Running %d backtest...", year)

        # We need access to the Backtester's trade list, which run_year doesn't
        # directly return. Replicate run_year inline to capture trades.
        from backtest.backtester import Backtester
        from shared.iron_vault import IronVault
        from scripts.run_optimization import _build_config

        config = _build_config(CHAMPION_PARAMS)
        start = datetime(year, 1, 1)
        end = datetime(year, 12, 31)

        try:
            hd = IronVault.instance()
        except Exception as e:
            log.error(
                "IronVault unavailable: %s\n"
                "  This script requires the options_cache.db file.\n"
                "  Run on the machine with Polygon data: python scripts/iron_vault_setup.py",
                e,
            )
            sys.exit(1)

        bt = Backtester(config, historical_data=hd, otm_pct=CHAMPION_PARAMS.get("otm_pct", 0.02))
        result = bt.run_backtest("SPY", start, end) or {}
        result["year"] = year

        elapsed = time.time() - t0
        ret = result.get("return_pct", 0)
        trades = result.get("total_trades", 0)
        log.info("  %d: %+.1f%%  %d trades  (%.0fs)", year, ret, trades, elapsed)

        results[str(year)] = result
        all_trades[str(year)] = list(bt.trades)  # capture from backtester instance

    return results, all_trades


# ── Price data caching ───────────────────────────────────────────────────────

def load_price_caches(years: List[int]) -> Tuple[dict, dict]:
    """Load SPY and VIX price data for feature computation."""
    from backtest.backtester import _curl_yf_chart, _yf_chart_to_df
    import calendar as cal

    start_ts = int(datetime(min(years) - 1, 1, 1).timestamp())
    end_ts = int(datetime(max(years), 12, 31).timestamp())

    price_cache = {}
    vix_cache = {}

    for ticker, cache in [("SPY", price_cache), ("^VIX", vix_cache)]:
        log.info("Fetching %s price data (%d-%d)...", ticker, min(years) - 1, max(years))
        encoded = ticker.replace("^", "%5E")
        chart = _curl_yf_chart(encoded, start_ts, end_ts, timeout_secs=60)
        df = _yf_chart_to_df(chart)
        if df.empty:
            log.warning("No data for %s — features will be incomplete", ticker)
        else:
            log.info("  %s: %d rows (%s → %s)", ticker, len(df), df.index[0].date(), df.index[-1].date())
        name = "VIX" if ticker == "^VIX" else ticker
        cache[name] = df

    return price_cache, vix_cache


# ── HTML report ──────────────────────────────────────────────────────────────

def generate_html(
    years: List[int],
    baseline_results: dict,
    gated_results: Dict[str, Dict[str, dict]],
    threshold: float,
) -> str:
    """Generate comparison HTML report."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    model_names = list(gated_results.keys())

    def _pnl_color(val):
        if val > 0: return "color:#16a34a;"
        if val < 0: return "color:#dc2626;"
        return ""

    def _delta(val, ref, higher_better=True):
        d = val - ref
        if abs(d) < 0.01: return ""
        good = (d > 0) == higher_better
        c = "#16a34a" if good else "#dc2626"
        arrow = "&#9650;" if d > 0 else "&#9660;"
        return f' <span style="color:{c};font-size:11px;">{arrow}{abs(d):.1f}</span>'

    # Per-year comparison tables
    year_tables = ""
    for year in years:
        yr = str(year)
        base = baseline_results.get(yr, {})
        base_pnl = base.get("total_pnl", (base.get("return_pct", 0) / 100) * 100_000)
        base_trades = base.get("total_trades", 0)
        base_wr = base.get("win_rate", 0)
        base_sharpe = base.get("sharpe_ratio", 0)
        base_dd = base.get("max_drawdown", 0)

        rows = f"""<tr style="background:#f9fafb;font-weight:600;">
            <td>No ML (Baseline)</td>
            <td style="text-align:right;">{base_trades}</td>
            <td style="text-align:right;">—</td>
            <td style="text-align:right;{_pnl_color(base_pnl)}">${base_pnl:,.0f}</td>
            <td style="text-align:right;">{base.get('return_pct', 0):+.1f}%</td>
            <td style="text-align:right;">{base_wr:.1f}%</td>
            <td style="text-align:right;">{base_sharpe:.2f}</td>
            <td style="text-align:right;">{base_dd:.1f}%</td>
        </tr>"""

        for mname in model_names:
            g = gated_results[mname].get(yr, {})
            pnl = g.get("total_pnl", 0)
            rows += f"""<tr>
                <td style="font-weight:500;">{mname}</td>
                <td style="text-align:right;">{g.get('total_trades', 0)}</td>
                <td style="text-align:right;color:#dc2626;">{g.get('filtered_trades', 0)}</td>
                <td style="text-align:right;{_pnl_color(pnl)}">${pnl:,.0f}{_delta(pnl, base_pnl)}</td>
                <td style="text-align:right;">{g.get('return_pct', 0):+.1f}%{_delta(g.get('return_pct', 0), base.get('return_pct', 0))}</td>
                <td style="text-align:right;">{g.get('win_rate', 0):.1f}%{_delta(g.get('win_rate', 0), base_wr)}</td>
                <td style="text-align:right;">{g.get('sharpe_ratio', 0):.2f}{_delta(g.get('sharpe_ratio', 0), base_sharpe)}</td>
                <td style="text-align:right;">{g.get('max_drawdown', 0):.1f}%{_delta(g.get('max_drawdown', 0), base_dd, higher_better=False)}</td>
            </tr>"""

        year_tables += f"""
        <h3 style="margin-top:20px;">{year}</h3>
        <table>
        <thead><tr>
            <th>Model</th><th style="text-align:right;">Trades</th><th style="text-align:right;">Filtered</th>
            <th style="text-align:right;">P&amp;L</th><th style="text-align:right;">Return</th>
            <th style="text-align:right;">Win Rate</th><th style="text-align:right;">Sharpe</th>
            <th style="text-align:right;">Max DD</th>
        </tr></thead>
        <tbody>{rows}</tbody>
        </table>"""

    # Aggregate summary
    agg_rows = ""
    # Baseline aggregate
    total_base_pnl = sum(
        r.get("total_pnl", (r.get("return_pct", 0) / 100) * 100_000)
        for r in baseline_results.values() if "error" not in r
    )
    total_base_trades = sum(r.get("total_trades", 0) for r in baseline_results.values())
    agg_rows += f"""<tr style="background:#f9fafb;font-weight:600;">
        <td>No ML (Baseline)</td>
        <td style="text-align:right;">{total_base_trades}</td>
        <td style="text-align:right;">—</td>
        <td style="text-align:right;{_pnl_color(total_base_pnl)}">${total_base_pnl:,.0f}</td>
    </tr>"""

    for mname in model_names:
        total_pnl = sum(g.get("total_pnl", 0) for g in gated_results[mname].values())
        total_trades = sum(g.get("total_trades", 0) for g in gated_results[mname].values())
        total_filtered = sum(g.get("filtered_trades", 0) for g in gated_results[mname].values())
        agg_rows += f"""<tr>
            <td style="font-weight:500;">{mname}</td>
            <td style="text-align:right;">{total_trades}</td>
            <td style="text-align:right;color:#dc2626;">{total_filtered}</td>
            <td style="text-align:right;{_pnl_color(total_pnl)}">${total_pnl:,.0f}{_delta(total_pnl, total_base_pnl)}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtest: Ensemble vs XGBoost P&amp;L Impact</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#fff; color:#1f2937; line-height:1.5; }}
  .container {{ max-width:1000px; margin:0 auto; padding:32px 24px; }}
  h1 {{ font-size:24px; font-weight:800; }}
  h2 {{ font-size:18px; font-weight:700; margin:28px 0 12px; padding-bottom:6px; border-bottom:2px solid #e5e7eb; }}
  h3 {{ font-size:15px; font-weight:600; color:#4b5563; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; margin-bottom:8px; }}
  th {{ text-align:left; padding:8px 10px; background:#f9fafb; border-bottom:2px solid #e5e7eb; font-weight:600; font-size:11px; text-transform:uppercase; letter-spacing:0.05em; color:#6b7280; }}
  td {{ padding:7px 10px; border-bottom:1px solid #f3f4f6; }}
  tr:hover {{ background:#f9fafb; }}
  .ts {{ font-size:12px; color:#9ca3af; margin-bottom:20px; }}
  .note {{ background:#eff6ff; border:1px solid #93c5fd; border-radius:8px; padding:12px 16px; font-size:13px; margin-bottom:20px; }}
</style>
</head>
<body>
<div class="container">

<h1>Backtest: ML Gating P&amp;L Impact</h1>
<div class="ts">Generated {now} &mdash; Champion config (EXP-400) on SPY {min(years)}-{max(years)} &mdash; Confidence threshold: {threshold:.0%}</div>

<div class="note">
    <strong>Methodology:</strong> Full backtest runs without ML gating. Each model then retroactively
    predicts every trade. Trades with ML confidence &lt; {threshold:.0%} are filtered out. P&amp;L is
    recomputed on the surviving trades. This measures the <em>actual dollar impact</em> of ML gating,
    not just classification accuracy.
</div>

<h2>Aggregate ({min(years)}-{max(years)})</h2>
<table>
<thead><tr><th>Model</th><th style="text-align:right;">Trades Kept</th><th style="text-align:right;">Filtered</th><th style="text-align:right;">Total P&amp;L</th></tr></thead>
<tbody>{agg_rows}</tbody>
</table>

<h2>Per-Year Comparison</h2>
{year_tables}

<h2>Interpretation Guide</h2>
<div style="font-size:13px;color:#6b7280;line-height:1.8;">
<p><strong>Trades Kept</strong> = trades that passed ML confidence gating. <strong>Filtered</strong> = trades the model would have blocked.</p>
<p><strong>Green arrows</strong> = improvement vs baseline. <strong>Red arrows</strong> = degradation.</p>
<p>A good ML gate should: (1) filter more losing trades than winning trades, (2) improve win rate, (3) improve or maintain Sharpe, (4) not dramatically reduce total P&amp;L.</p>
<p>If a model filters heavily but P&amp;L drops, it's killing winners — the threshold may be too aggressive.</p>
</div>

</div>
</body>
</html>"""
    return html


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest ensemble vs XGBoost P&L comparison")
    parser.add_argument("--years", default="2020-2025", help="Year range (e.g. 2020-2025)")
    parser.add_argument("--threshold", type=float, default=0.30, help="ML confidence threshold (default 0.30)")
    args = parser.parse_args()

    # Parse years
    if "-" in args.years and "," not in args.years:
        lo, hi = args.years.split("-")
        years = list(range(int(lo), int(hi) + 1))
    else:
        years = [int(y) for y in args.years.split(",")]

    threshold = args.threshold

    log.info("=" * 70)
    log.info("  Backtest: Ensemble vs XGBoost P&L Impact")
    log.info("  Years: %s  |  Threshold: %.0f%%", years, threshold * 100)
    log.info("=" * 70)

    # Step 1: Load ML models
    log.info("\nStep 1: Loading ML models...")
    models = load_models()
    if not models:
        log.error("No ML models found. Train models first (scripts/train_ensemble.py)")
        sys.exit(1)
    log.info("  Loaded: %s", ", ".join(models.keys()))

    # Step 2: Run full backtest
    log.info("\nStep 2: Running full backtest (no ML gating)...")
    t0 = time.time()
    baseline_results, trades_by_year = run_full_backtest(years)
    bt_elapsed = time.time() - t0
    total_trades = sum(len(t) for t in trades_by_year.values())
    log.info("  Backtest complete: %d trades across %d years (%.0fs)", total_trades, len(years), bt_elapsed)

    # Step 3: Load price data for feature computation
    log.info("\nStep 3: Loading price data for feature computation...")
    price_cache, vix_cache = load_price_caches(years)

    # Step 4: Build features for all trades
    log.info("\nStep 4: Building features for %d trades...", total_trades)
    features_by_year = {}
    feat_success = 0
    feat_fail = 0
    for yr, trades in trades_by_year.items():
        year_features = []
        for trade in trades:
            feat = build_trade_features(trade, price_cache, vix_cache)
            year_features.append(feat)
            if feat is not None:
                feat_success += 1
            else:
                feat_fail += 1
        features_by_year[yr] = year_features
    log.info("  Features built: %d success, %d failed (%.1f%%)", feat_success, feat_fail,
             feat_success / max(1, feat_success + feat_fail) * 100)

    # Step 5: Run ML predictions and compute gated metrics
    log.info("\nStep 5: Running ML predictions and computing gated P&L...")
    gated_results = {}

    for model_name, model in models.items():
        log.info("  %s:", model_name)
        model_results = {}

        for yr in [str(y) for y in years]:
            trades = trades_by_year.get(yr, [])
            features = features_by_year.get(yr, [])

            predictions = []
            for feat in features:
                if feat is None:
                    predictions.append(None)
                else:
                    try:
                        pred = model.predict(feat)
                        predictions.append(pred)
                    except Exception:
                        predictions.append(None)

            metrics = compute_gated_metrics(trades, predictions, threshold)
            model_results[yr] = metrics

            kept = metrics["total_trades"]
            filtered = metrics["filtered_trades"]
            pnl = metrics["total_pnl"]
            log.info("    %s: %d kept, %d filtered → $%+,.0f (%.1f%%)",
                     yr, kept, filtered, pnl, metrics["return_pct"])

        gated_results[model_name] = model_results

    # Step 6: Generate HTML report
    log.info("\nStep 6: Generating HTML report...")
    html = generate_html(years, baseline_results, gated_results, threshold)
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html)
    log.info("  Written to %s (%.1f KB)", OUTPUT_HTML, OUTPUT_HTML.stat().st_size / 1024)

    # Step 7: Print summary
    log.info("\n" + "=" * 70)
    log.info("  SUMMARY")
    log.info("=" * 70)

    total_base_pnl = sum(
        r.get("total_pnl", (r.get("return_pct", 0) / 100) * 100_000)
        for r in baseline_results.values() if "error" not in r
    )
    log.info("  Baseline (no ML):  %d trades  $%+,.0f", total_trades, total_base_pnl)

    for mname in models:
        total_pnl = sum(g.get("total_pnl", 0) for g in gated_results[mname].values())
        total_kept = sum(g.get("total_trades", 0) for g in gated_results[mname].values())
        total_filt = sum(g.get("filtered_trades", 0) for g in gated_results[mname].values())
        delta = total_pnl - total_base_pnl
        log.info("  %-20s %d kept, %d filtered  $%+,.0f  (delta: $%+,.0f)",
                 mname + ":", total_kept, total_filt, total_pnl, delta)

    log.info("")
    log.info("  Report: %s", OUTPUT_HTML)
    log.info("=" * 70)


if __name__ == "__main__":
    main()
