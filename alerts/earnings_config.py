"""
Earnings volatility play configuration overlay.

Builds an earnings-tuned config from the base system config by deep-copying
and overriding strategy/risk parameters for selling iron condors at 1.2x
expected move before earnings to profit from IV crush.

Key difference from Phase 3 iron condors: earnings condors use price-based
strike placement rather than delta-based, and target 1-7 DTE (just after
earnings).
"""

import copy
from typing import List

# 18 high-liquidity names for earnings volatility plays
EARNINGS_TICKERS: List[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "NFLX",
    "AMD", "CRM", "COIN", "SQ", "SHOP", "UBER", "ABNB", "PLTR",
    "SNAP", "ROKU",
]

# Look ahead 14 days for upcoming earnings
EARNINGS_LOOKAHEAD_DAYS = 14


def build_earnings_config(base_config: dict) -> dict:
    """Deep-copy *base_config* and override for earnings volatility plays.

    The returned config can be passed directly to ``OptionsAnalyzer``
    without mutating the original.

    Returns:
        A new config dict tuned for earnings iron condors.
    """
    cfg = copy.deepcopy(base_config)

    # --- Strategy overrides ---
    strategy = cfg.setdefault("strategy", {})
    strategy["min_dte"] = 1
    strategy["max_dte"] = 7          # expiration just after earnings
    strategy["min_iv_rank"] = 60     # high IV required (req 5.4)

    # Disable delta-based iron condor (we use price-based construction)
    strategy.setdefault("iron_condor", {})["enabled"] = False

    # Earnings-specific parameters
    strategy["earnings"] = {
        "expected_move_multiplier": 1.2,      # 1.2x expected move (req 5.4)
        "min_stay_in_range_pct": 65,          # 65% historical stay-in-range (req 5.4)
        "min_historical_quarters": 4,
        "spread_width": 5,
        "max_risk_pct": 0.02,                 # 1-2% per trade
        "profit_target_pct": 0.50,            # 50% of credit
        "stop_loss_multiplier": 2.0,          # 2x credit
        "min_entry_days_before": 1,
        "max_entry_days_before": 3,
    }

    # --- Tickers ---
    cfg["tickers"] = list(EARNINGS_TICKERS)

    return cfg
