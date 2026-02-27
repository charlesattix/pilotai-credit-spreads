"""
Gamma/lotto play configuration overlay.

Builds a gamma-tuned config from the base system config by deep-copying
and overriding strategy/risk parameters for buying cheap 0DTE/1DTE OTM
options before major economic events.

Key difference from all prior phases: gamma lottos are single-leg debit plays
(buying one naked OTM call or put), not spreads.
"""

import copy
from datetime import time
from typing import List, Tuple

# Tickers scanned for gamma lottos — high-liquidity index ETFs
GAMMA_TICKERS: List[str] = ["SPY", "QQQ", "IWM"]

# Market hours gate for gamma scanning (ET)
SCAN_HOURS: Tuple[time, time] = (time(9, 35), time(15, 30))


def build_gamma_config(base_config: dict) -> dict:
    """Deep-copy *base_config* and override for gamma/lotto plays.

    Returns:
        A new config dict tuned for gamma lotto scanning.
    """
    cfg = copy.deepcopy(base_config)

    # --- Strategy overrides ---
    strategy = cfg.setdefault("strategy", {})
    strategy["min_dte"] = 0
    strategy["max_dte"] = 1        # 0DTE / 1DTE only

    # Disable iron condor construction
    strategy.setdefault("iron_condor", {})["enabled"] = False

    # Gamma-specific parameters
    strategy["gamma"] = {
        "price_min": 0.10,                    # cheapest option to consider
        "price_max": 0.50,                    # most expensive option to consider
        "max_risk_pct": 0.005,                # 0.5% max risk per MASTERPLAN
        "trailing_stop_activation": 3.0,      # activate trailing stop at 3x entry
        "trailing_stop_level": 2.0,           # trail at 2x entry
        "min_otm_pct": 0.02,                 # minimum 2% OTM
        "max_otm_pct": 0.10,                 # maximum 10% OTM
    }

    # --- Tickers ---
    cfg["tickers"] = list(GAMMA_TICKERS)

    return cfg
