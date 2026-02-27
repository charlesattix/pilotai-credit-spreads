"""
Iron condor alert configuration overlay.

Builds a weekly iron condor config from the base system config by deep-copying
and overriding strategy/risk parameters for high-IV, range-bound environments.
Targets 4-10 DTE weekly options on an expanded ticker list.
"""

import copy
from typing import Dict

# Entry/exit day-of-week constants (Monday=0 … Friday=4)
ENTRY_DAYS = {0, 1}    # Monday, Tuesday  (req 3.6)
CLOSE_DAYS = {3, 4}    # Thursday, Friday  (req 3.6)


def build_iron_condor_config(base_config: dict) -> dict:
    """Deep-copy *base_config* and override for weekly iron condor scanning.

    The returned config can be passed directly to ``CreditSpreadStrategy``,
    ``OptionsAnalyzer``, etc. without mutating the original.

    Returns:
        A new config dict tuned for iron condors in high-IV environments.
    """
    cfg = copy.deepcopy(base_config)

    # --- Strategy overrides ---
    strategy = cfg.setdefault("strategy", {})
    strategy["min_dte"] = 4
    strategy["max_dte"] = 10                  # weekly cycle
    strategy["min_delta"] = 0.12              # 16-delta wings (req 3.2)
    strategy["max_delta"] = 0.20
    strategy["spread_width"] = 5              # all widths uniform
    strategy["spread_width_high_iv"] = 5
    strategy["spread_width_low_iv"] = 5
    strategy["min_iv_rank"] = 50              # high-IV filter (req 3.1)
    strategy["min_iv_percentile"] = 50

    # Iron condor specific
    ic = strategy.setdefault("iron_condor", {})
    ic["enabled"] = True
    ic["min_combined_credit_pct"] = 34        # 1/3 of width (req 3.3)

    # --- Risk overrides ---
    risk = cfg.setdefault("risk", {})
    risk["profit_target"] = 50                # 50% profit close (req 3.4)
    risk["stop_loss_multiplier"] = 2.0        # 2x credit stop

    # --- Tickers (req 3.5) ---
    cfg["tickers"] = ["SPY", "QQQ", "TSLA", "AMZN", "META", "GOOGL"]

    return cfg
