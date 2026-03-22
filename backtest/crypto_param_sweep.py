"""
crypto_param_sweep.py — Parameter sweep definition for IBIT crypto credit spreads.

Defines the search space and generates every (DTE, delta, profit-target, stop-loss,
regime-profile) combination that the backtester should evaluate for IBIT.

Pattern mirrors grid_search_plateau.py:
    - Flat param dicts compatible with _build_config() in run_optimization.py
    - Arrays for each swept dimension
    - build_sweep() for the Cartesian product → List[dict]
    - PARAM_SPACE (List[ParamDef]) for the optimizer (engine/optimizer.py)

Grid dimensions
───────────────
    DTE              [7, 14, 21, 30, 45]          5 values
    Delta            [0.10, 0.15, 0.20, 0.30]     4 values
    Profit target    [30, 50, 65, 80]  %           4 values
    Stop loss mult   [1.0, 1.5, 2.0, 3.0]  × CR   4 values
    Regime profile   5 named profiles
    ──────────────────────────────────────────────────────
    Default total    5 × 4 × 4 × 4 × 5 = 1,600 combos

    With spread-width dimension (include_width=True):
                     × WIDTH_VALUES [1, 2, 3]      → 4,800 combos

Regime profiles
───────────────
Each profile is a dict of per-band position-size scale factors applied when the
crypto composite score (compass.crypto.regime) places the market in that band.
Band keys use compass.crypto.regime vocabulary:
    "extreme_fear"  composite_score < 25    (≈ Fear & Greed "Extreme Fear")
    "cautious"      25–39                   (≈ "Fear")
    "neutral"       40–59
    "bullish"       60–74                   (≈ "Greed")
    "extreme_greed" 75–100                  (≈ "Extreme Greed")

Usage
─────
    from backtest.crypto_param_sweep import FULL_SWEEP, build_sweep, PARAM_SPACE

    # Full grid — pass to backtester one at a time
    for params in FULL_SWEEP:
        run_backtest(params)

    # Custom sub-grid
    combos = build_sweep(dte_values=[14, 21], regime_profiles=["flat", "contrarian"])

    # Optimizer-compatible search space
    from engine.optimizer import Optimizer
    opt = Optimizer(param_space=PARAM_SPACE)
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Sweep dimensions
# ---------------------------------------------------------------------------

#: DTE (calendar days to expiration) for the short strike.
#: 7 = weekly, 14 = biweekly, 21 = 3-week, 30 = monthly, 45 = 6-week.
DTE_VALUES: List[int] = [7, 14, 21, 30, 45]

#: Target delta for the short strike (absolute value).
#: 0.10 = deep OTM / conservative; 0.30 = closer to ATM / aggressive.
DELTA_VALUES: List[float] = [0.10, 0.15, 0.20, 0.30]

#: Spread width in dollars.  IBIT trades ~$35–60 with $0.50–$1 strike spacing.
#: Width 1 = very tight; 2 = standard; 3 = wider wing for more credit.
WIDTH_VALUES: List[int] = [1, 2, 3]

#: Profit target as % of credit received.
#: 30 % = early exit / high win-rate; 80 % = hold longer / more volatile P&L.
PROFIT_TARGET_VALUES: List[int] = [30, 50, 65, 80]

#: Stop-loss multiplier relative to credit received.
#: 1.0 = exit at 1× credit (100% loss of premium = $0 remaining value).
#: 3.0 = exit at 3× credit (spread approaches max-loss territory).
STOP_LOSS_VALUES: List[float] = [1.0, 1.5, 2.0, 3.0]

# ---------------------------------------------------------------------------
# Regime scaling profiles
# ---------------------------------------------------------------------------
#
# Each profile encodes a different hypothesis about WHEN to be aggressive or
# conservative based on the crypto market sentiment composite score.
# Keys match compass.crypto.regime.classify_regime() output labels.
# Scale 0.0 = skip entries entirely; 1.0 = full position; 1.5 = 50% larger.

REGIME_PROFILES: Dict[str, Dict[str, float]] = {

    # ── Flat ──────────────────────────────────────────────────────────────
    # Regime-agnostic baseline.  Equal size regardless of sentiment.
    # Useful as the control to measure regime-filtering value.
    "flat": {
        "regime_scale_extreme_fear":  1.0,
        "regime_scale_cautious":      1.0,
        "regime_scale_neutral":       1.0,
        "regime_scale_bullish":       1.0,
        "regime_scale_extreme_greed": 1.0,
    },

    # ── Fear premium (contrarian premium seller) ──────────────────────────
    # High IV in fear regimes → richer premium → sell more.
    # Extreme fear is still throttled (tail risk too high to go full size).
    "fear_premium": {
        "regime_scale_extreme_fear":  0.5,
        "regime_scale_cautious":      1.5,
        "regime_scale_neutral":       1.0,
        "regime_scale_bullish":       0.8,
        "regime_scale_extreme_greed": 0.5,
    },

    # ── Momentum / greed (trend-following) ────────────────────────────────
    # Trade full size when sentiment and price are in clear uptrend.
    # Avoid extreme fear entirely; reduced size in cautious zones.
    "greed_momentum": {
        "regime_scale_extreme_fear":  0.0,
        "regime_scale_cautious":      0.5,
        "regime_scale_neutral":       1.0,
        "regime_scale_bullish":       1.5,
        "regime_scale_extreme_greed": 1.0,
    },

    # ── Neutral-only (low-volatility specialist) ──────────────────────────
    # Only deploy capital when sentiment is calm.  Avoids both fear-driven
    # crashes and greed-driven blow-ups.  High Sharpe, lower total return.
    "neutral_only": {
        "regime_scale_extreme_fear":  0.0,
        "regime_scale_cautious":      0.5,
        "regime_scale_neutral":       1.5,
        "regime_scale_bullish":       0.5,
        "regime_scale_extreme_greed": 0.0,
    },

    # ── Contrarian (sell into euphoria, buy fear) ─────────────────────────
    # Max size during extreme fear (highest IV, most pessimism = mean-reversion
    # opportunity).  Scales down into extreme greed (complacency risk).
    "contrarian": {
        "regime_scale_extreme_fear":  1.5,
        "regime_scale_cautious":      1.25,
        "regime_scale_neutral":       1.0,
        "regime_scale_bullish":       0.5,
        "regime_scale_extreme_greed": 0.25,
    },
}

# ---------------------------------------------------------------------------
# Base parameters (fixed for IBIT — not varied by the sweep)
# ---------------------------------------------------------------------------
#
# These match the flat-dict format consumed by _build_config() in
# scripts/run_optimization.py.  Override any of these keys in the combo
# dict returned by build_sweep() to customise a specific run.

BASE_PARAMS: Dict[str, Any] = {
    # Ticker
    "ticker":               "IBIT",

    # Strike selection — delta-based (overrides otm_pct)
    "use_delta_selection":  True,
    "otm_pct":              0.03,       # fallback when delta selection unavailable

    # Spread
    "spread_width":         2,          # default width in $; swept separately if include_width=True
    "min_credit_pct":       8,          # minimum credit as % of spread width

    # Direction — both puts (bull-put) and calls (bear-call)
    "direction":            "both",

    # Trend / regime
    "trend_ma_period":      200,
    "regime_mode":          "crypto_composite",  # uses compass.crypto regime signals
    "regime_config": {
        "signals":          ["price_vs_ma200", "fear_greed_index", "funding_rate"],
        "ma_slow_period":   200,
        "bear_requires_unanimous": True,
        "cooldown_days":    5,
        "vix_extreme":      40.0,       # BTC 30d vol proxy threshold
    },

    # Position sizing
    "max_risk_per_trade":   5.0,        # % of portfolio per spread
    "max_contracts":        10,
    "compound":             True,
    "sizing_mode":          "flat",     # flat-risk sizing (same $ risk per trade)

    # Portfolio guardrails
    "drawdown_cb_pct":      30,         # circuit breaker: halt new entries at -30% DD
    "max_portfolio_exposure_pct": 100.0,

    # Execution costs (IBIT options — liquid ETF)
    "commission_per_contract": 0.65,
    "slippage":             0.05,
    "exit_slippage":        0.10,
}

# ---------------------------------------------------------------------------
# Param space for the Bayesian / random optimizer (engine/optimizer.py)
# ---------------------------------------------------------------------------
#
# Wraps the swept dimensions as ParamDef objects.  Import from strategies.base
# lazily to avoid circular imports when this module is loaded early.

def _build_param_space():
    try:
        from strategies.base import ParamDef
    except ImportError:
        return []

    return [
        ParamDef(
            name="target_dte",
            param_type="int",
            default=21,
            low=7,
            high=45,
            step=7,
            description="Target DTE for new entries (calendar days)",
        ),
        ParamDef(
            name="target_delta",
            param_type="float",
            default=0.15,
            low=0.10,
            high=0.30,
            step=0.05,
            description="Short-strike target delta (absolute value)",
        ),
        ParamDef(
            name="spread_width",
            param_type="int",
            default=2,
            low=1,
            high=3,
            step=1,
            description="Spread width in dollars",
        ),
        ParamDef(
            name="profit_target",
            param_type="int",
            default=50,
            low=30,
            high=80,
            step=5,
            description="Profit target as % of credit received",
        ),
        ParamDef(
            name="stop_loss_multiplier",
            param_type="float",
            default=2.0,
            low=1.0,
            high=3.0,
            step=0.5,
            description="Stop-loss multiplier relative to credit received",
        ),
        ParamDef(
            name="regime_scale_extreme_fear",
            param_type="float",
            default=0.5,
            low=0.0,
            high=2.0,
            step=0.25,
            description="Position-size scale in extreme-fear regime",
        ),
        ParamDef(
            name="regime_scale_cautious",
            param_type="float",
            default=1.0,
            low=0.0,
            high=2.0,
            step=0.25,
            description="Position-size scale in cautious (fear) regime",
        ),
        ParamDef(
            name="regime_scale_neutral",
            param_type="float",
            default=1.0,
            low=0.5,
            high=1.5,
            step=0.25,
            description="Position-size scale in neutral regime",
        ),
        ParamDef(
            name="regime_scale_bullish",
            param_type="float",
            default=1.0,
            low=0.0,
            high=2.0,
            step=0.25,
            description="Position-size scale in bullish (greed) regime",
        ),
        ParamDef(
            name="regime_scale_extreme_greed",
            param_type="float",
            default=0.5,
            low=0.0,
            high=2.0,
            step=0.25,
            description="Position-size scale in extreme-greed regime",
        ),
    ]


PARAM_SPACE = _build_param_space()

# ---------------------------------------------------------------------------
# Sweep builder
# ---------------------------------------------------------------------------

def build_sweep(
    dte_values: Optional[List[int]] = None,
    delta_values: Optional[List[float]] = None,
    profit_target_values: Optional[List[int]] = None,
    stop_loss_values: Optional[List[float]] = None,
    regime_profiles: Optional[List[str]] = None,
    include_width: bool = False,
    width_values: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Return the full list of parameter dicts for the IBIT sweep.

    Each dict is a flat param dict compatible with ``_build_config()`` in
    ``scripts/run_optimization.py``.  It includes:

    * All ``BASE_PARAMS`` (fixed IBIT defaults)
    * Swept values for DTE / delta / profit-target / stop-loss
    * All regime scale factors from the selected profile
    * A ``regime_profile`` label key for easy filtering

    Args:
        dte_values:           Override ``DTE_VALUES`` (default: all 5).
        delta_values:         Override ``DELTA_VALUES`` (default: all 4).
        profit_target_values: Override ``PROFIT_TARGET_VALUES`` (default: all 4).
        stop_loss_values:     Override ``STOP_LOSS_VALUES`` (default: all 4).
        regime_profiles:      Names of profiles to include (default: all 5).
                              See ``REGIME_PROFILES`` keys.
        include_width:        If True, also sweep ``width_values`` (× 3 combos).
        width_values:         Override ``WIDTH_VALUES`` when ``include_width=True``.

    Returns:
        List of flat param dicts, one per combination.
        Default count: 5 × 4 × 4 × 4 × 5 = 1,600.
        With ``include_width=True``: × 3 = 4,800.
    """
    dte_vals    = dte_values           or DTE_VALUES
    delta_vals  = delta_values         or DELTA_VALUES
    pt_vals     = profit_target_values or PROFIT_TARGET_VALUES
    sl_vals     = stop_loss_values     or STOP_LOSS_VALUES
    width_vals  = width_values         or WIDTH_VALUES
    profile_keys = regime_profiles     or list(REGIME_PROFILES.keys())

    # Validate requested profile names
    unknown = set(profile_keys) - set(REGIME_PROFILES)
    if unknown:
        raise ValueError(f"Unknown regime profile(s): {sorted(unknown)}. "
                         f"Valid: {sorted(REGIME_PROFILES)}")

    combos: List[Dict[str, Any]] = []

    # Core dimensions always swept
    core_axes = [dte_vals, delta_vals, pt_vals, sl_vals, profile_keys]

    # Optionally add spread width as an extra axis
    if include_width:
        core_axes.append(width_vals)

    for combo in itertools.product(*core_axes):
        if include_width:
            dte, delta, pt, sl, profile_name, width = combo
        else:
            dte, delta, pt, sl, profile_name = combo
            width = BASE_PARAMS["spread_width"]

        profile = REGIME_PROFILES[profile_name]

        params: Dict[str, Any] = {
            **BASE_PARAMS,
            # Swept dimensions
            "target_dte":           dte,
            "min_dte":              max(2, dte - 7),  # allow entry within 7 days of target
            "target_delta":         delta,
            "spread_width":         width,
            "profit_target":        pt,
            "stop_loss_multiplier": sl,
            # Regime scaling (all 5 bands, flat dict for easy _build_config() forwarding)
            **profile,
            # Metadata — never forwarded to backtester, used for filtering output
            "regime_profile":       profile_name,
        }
        combos.append(params)

    return combos


# ---------------------------------------------------------------------------
# Module-level sweep instance (pre-built, import and iterate)
# ---------------------------------------------------------------------------

#: Full default sweep — 1,600 combos.
#: Re-build with build_sweep() if you need a custom sub-grid.
FULL_SWEEP: List[Dict[str, Any]] = build_sweep()

TOTAL_COMBOS = len(FULL_SWEEP)

# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def sweep_summary() -> str:
    """Return a human-readable summary of the sweep dimensions."""
    lines = [
        "IBIT Crypto Credit Spread Parameter Sweep",
        "=" * 44,
        f"  Ticker            : IBIT",
        f"  DTE values        : {DTE_VALUES}",
        f"  Delta values      : {DELTA_VALUES}",
        f"  Profit target %   : {PROFIT_TARGET_VALUES}",
        f"  Stop-loss mult    : {STOP_LOSS_VALUES}",
        f"  Spread widths     : {WIDTH_VALUES} (not swept by default)",
        f"  Regime profiles   : {list(REGIME_PROFILES)}",
        f"  Default combos    : {TOTAL_COMBOS:,}",
        f"  With width sweep  : {TOTAL_COMBOS * len(WIDTH_VALUES):,}",
        "",
        "Regime profile scales (extreme_fear / cautious / neutral / bullish / extreme_greed):",
    ]
    for name, scales in REGIME_PROFILES.items():
        vals = " / ".join(f"{v:.2f}" for v in scales.values())
        lines.append(f"  {name:<20}: {vals}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# IBIT Backtester sweep — new engine (backtest/ibit_backtester.py)
# ---------------------------------------------------------------------------
#
# Separate from the BTC-sweep above.  Uses the standalone IBITBacktester
# which reads from crypto_options_cache.db and supports:
#   - Iron condors / adaptive direction
#   - 0/1/3/5 DTE
#   - Multi-position (max_concurrent)
#   - Kelly criterion sizing
#   - Same-day re-entry

# New short-dated DTE options
IBIT_DTE_VALUES: List[int] = [0, 1, 3, 5, 7, 14, 21, 30, 45]

# OTM % for short strike (mirrors DELTA_VALUES semantics)
IBIT_OTM_VALUES: List[float] = [0.03, 0.05, 0.08, 0.12]

# Spread width in dollars
IBIT_WIDTH_VALUES: List[float] = [1.0, 2.0, 3.0, 5.0]

# Profit target as fraction of credit received (not %)
IBIT_PT_VALUES: List[float] = [0.25, 0.40, 0.50, 0.65]

# Stop-loss multiplier (× credit)
IBIT_SL_VALUES: List[float] = [1.5, 2.0, 2.5, 3.0]

# Direction
IBIT_DIRECTION_VALUES: List[str] = ["bull_put", "iron_condor", "adaptive"]

# Max concurrent positions
IBIT_MAX_CONCURRENT_VALUES: List[int] = [1, 3, 5, 10]

# Kelly fraction (0 = disabled → use base risk_pct)
IBIT_KELLY_VALUES: List[float] = [0.0, 0.25, 0.50, 0.75]

# Same-day re-entry after profit target
IBIT_REENTRY_VALUES: List[bool] = [False, True]


def build_ibit_sweep(
    dte_values: Optional[List[int]] = None,
    otm_values: Optional[List[float]] = None,
    width_values: Optional[List[float]] = None,
    pt_values: Optional[List[float]] = None,
    sl_values: Optional[List[float]] = None,
    direction_values: Optional[List[str]] = None,
    max_concurrent_values: Optional[List[int]] = None,
    kelly_values: Optional[List[float]] = None,
    reentry_values: Optional[List[bool]] = None,
    regime_filter: str = "none",
    ma_period: int = 50,
    min_credit_pct: float = 5.0,
    risk_pct: float = 0.05,
    starting_capital: float = 100_000.0,
) -> List[Dict[str, Any]]:
    """
    Build parameter combos for the IBITBacktester sweep.

    Each returned dict is a config kwarg compatible with IBITBacktester(config=...).

    Default grid (with all single-value defaults):
        9 DTE × 4 OTM × 3 direction = 108 core combos
        (width/PT/SL/concurrent/kelly/reentry passed as singles by default
         so callers control the explosion size)

    Args:
        dte_values:           DTE targets (default: IBIT_DTE_VALUES)
        otm_values:           OTM % for short put (default: IBIT_OTM_VALUES)
        width_values:         Spread width in $ (default: [2.0])
        pt_values:            Profit target fraction (default: [0.50])
        sl_values:            Stop-loss multiplier (default: [2.0])
        direction_values:     Trade direction (default: IBIT_DIRECTION_VALUES)
        max_concurrent_values: Max concurrent positions (default: [1])
        kelly_values:         Kelly fraction (default: [0.0])
        reentry_values:       Same-day re-entry (default: [False])
        regime_filter:        Regime filter to use (default: "none")
        ma_period:            MA period for regime/adaptive (default: 50)
        min_credit_pct:       Minimum credit threshold (default: 5.0)
        risk_pct:             Base risk per trade (default: 0.05)
        starting_capital:     Starting capital (default: 100_000)
    """
    dte_vals     = dte_values           or IBIT_DTE_VALUES
    otm_vals     = otm_values           or IBIT_OTM_VALUES
    width_vals   = width_values         or [2.0]
    pt_vals      = pt_values            or [0.50]
    sl_vals      = sl_values            or [2.0]
    dir_vals     = direction_values     or IBIT_DIRECTION_VALUES
    conc_vals    = max_concurrent_values or [1]
    kelly_vals   = kelly_values         or [0.0]
    reentry_vals = reentry_values       or [False]

    combos: List[Dict[str, Any]] = []

    for dte, otm, width, pt, sl, direction, max_conc, kelly, reentry in itertools.product(
        dte_vals, otm_vals, width_vals, pt_vals, sl_vals,
        dir_vals, conc_vals, kelly_vals, reentry_vals,
    ):
        dte_min = 0 if dte == 0 else max(0, dte - 3)
        dte_max = dte + 10

        params: Dict[str, Any] = {
            "starting_capital":  starting_capital,
            "compound":          True,
            "direction":         direction,
            "otm_pct":           otm,
            "call_otm_pct":      None,   # symmetric by default
            "spread_width":      width,
            "call_spread_width": None,   # symmetric by default
            "min_credit_pct":    min_credit_pct,
            "dte_target":        dte,
            "dte_min":           dte_min,
            "dte_max":           dte_max,
            "profit_target":     pt,
            "stop_loss_mult":    sl,
            "risk_pct":          risk_pct,
            "max_contracts":     200,
            "max_concurrent":    max_conc,
            "kelly_fraction":    kelly,
            "kelly_min_trades":  10,
            "same_day_reentry":  reentry,
            "regime_filter":     regime_filter,
            "ma_period":         ma_period,
        }
        combos.append(params)

    return combos


#: Pre-built IBIT sweep — default dimensions only (no kelly/concurrent/reentry explosion).
#: 9 DTE × 4 OTM × 3 direction = 108 combos — fast to run for initial sweep.
#: Use build_ibit_sweep(max_concurrent_values=[1,3,5,10], ...) for the full grid.
IBIT_SWEEP: List[Dict[str, Any]] = build_ibit_sweep()

IBIT_TOTAL_COMBOS = len(IBIT_SWEEP)


if __name__ == "__main__":
    print(sweep_summary())
    print(f"\nSample combo #0:\n  {FULL_SWEEP[0]}")
    print(f"\nSample combo #800:\n  {FULL_SWEEP[800]}")
    print(f"\nSample combo #-1:\n  {FULL_SWEEP[-1]}")
    print(f"\nIBIT_SWEEP: {IBIT_TOTAL_COMBOS} combos")
    print(f"Sample IBIT combo #0:\n  {IBIT_SWEEP[0]}")
