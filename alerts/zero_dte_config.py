"""
0DTE/1DTE credit spread configuration overlay.

Builds a 0DTE-tuned config from the base system config by deep-copying
and overriding strategy/risk parameters for same-day expiration trades
on SPY and SPX.
"""

import copy
from typing import Dict

# SPX index properties — used by the scanner to annotate alerts
SPX_PROPERTIES: Dict = {
    "settlement": "cash",
    "exercise_style": "european",
    "tax_treatment": "section_1256",
    "price_ticker": "^GSPC",        # yfinance symbol for S&P 500 index price
    "multiplier": 100,
    "description": "S&P 500 Index options (cash-settled, European-style)",
}


def build_zero_dte_config(base_config: dict) -> dict:
    """Deep-copy *base_config* and override for 0DTE/1DTE scanning.

    The returned config can be passed directly to ``CreditSpreadStrategy``,
    ``OptionsAnalyzer``, etc. without mutating the original.

    Returns:
        A new config dict tuned for 0DTE credit spreads on SPY/SPX.
    """
    cfg = copy.deepcopy(base_config)

    # --- Strategy overrides ---
    strategy = cfg.setdefault("strategy", {})
    strategy["min_dte"] = 0
    strategy["max_dte"] = 1
    strategy["min_delta"] = 0.08           # 10-15 delta target (tighter than regular 20-30)
    strategy["max_delta"] = 0.16
    strategy["spread_width"] = 5           # $5 wide for both SPY and SPX
    strategy["spread_width_high_iv"] = 5
    strategy["spread_width_low_iv"] = 3
    strategy["min_iv_rank"] = 8            # lower bar (less time value in 0DTE)
    strategy["min_iv_percentile"] = 8
    # Iron condors too complex for 0DTE
    strategy.setdefault("iron_condor", {})["enabled"] = False

    # --- Risk overrides ---
    risk = cfg.setdefault("risk", {})
    risk["stop_loss_multiplier"] = 2.0     # 2x credit (not 2.5x like regular)
    risk["min_credit_pct"] = 10            # lower minimum credit

    # --- Tickers ---
    cfg["tickers"] = ["SPY", "SPX"]

    return cfg
