"""
Momentum swing scanner configuration overlay.

Builds a momentum-tuned config from the base system config by deep-copying
and overriding strategy/risk parameters for debit spread swing plays on
high-beta, liquid-options names.
"""

import copy
from datetime import time
from typing import Dict, List

# 28 high-beta, liquid-options tickers for momentum scanning
MOMENTUM_TICKERS: List[str] = [
    "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL",
    "AMD", "NFLX", "CRM", "COIN", "SQ", "SHOP", "UBER",
    "ABNB", "PLTR", "MARA", "RIOT", "SNAP", "ROKU", "DKNG",
    "SOFI", "RIVN", "LUCID", "ARKK", "XLF", "XLE", "SMH",
]

# Market hours gate: only scan 9:35 ET – 15:30 ET
SCAN_HOURS = (time(9, 35), time(15, 30))


def build_momentum_config(base_config: dict) -> dict:
    """Deep-copy *base_config* and override for momentum swing scanning.

    The returned config can be passed directly to ``OptionsAnalyzer``
    without mutating the original.

    Returns:
        A new config dict tuned for momentum debit spreads.
    """
    cfg = copy.deepcopy(base_config)

    # --- Strategy overrides ---
    strategy = cfg.setdefault("strategy", {})
    strategy["min_dte"] = 7
    strategy["max_dte"] = 14

    # Iron condors not relevant for momentum plays
    strategy.setdefault("iron_condor", {})["enabled"] = False

    # Momentum-specific parameters
    strategy["momentum"] = {
        "min_relative_volume": 1.5,
        "min_momentum_score": 60,
        "min_adx": 25,
        "consolidation_lookback": 20,
        "spread_width": 5,
        "profit_target_pct": 1.0,       # 100% of debit = 2:1 R:R
        "stop_loss_pct": 0.50,           # 50% of debit
        "time_decay_warning_dte": 3,
        "ema_fast": 8,
        "ema_slow": 21,
        "rsi_divergence_lookback": 10,
        "vwap_gap_threshold": 0.02,      # 2% gap-down for VWAP reclaim
        "days_to_earnings_min": 5,
    }

    # --- Tickers ---
    cfg["tickers"] = list(MOMENTUM_TICKERS)

    return cfg
