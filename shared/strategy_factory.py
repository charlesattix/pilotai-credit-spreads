"""
Config → flat params extractor for strategy classes.

Translates nested YAML config (config["strategy"]["min_dte"]) into
flat param dicts that strategies read via self._p("target_dte", 35).
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _extract_credit_spread_params(config: Dict) -> Dict[str, Any]:
    """Extract CreditSpreadStrategy params from nested config."""
    strategy = config.get("strategy", {})
    risk = config.get("risk", {})
    technical = strategy.get("technical", {})

    params = {
        "direction": strategy.get("direction", "both"),
        "target_dte": strategy.get("target_dte", strategy.get("min_dte", 35)),
        "min_dte": strategy.get("min_dte", 25),
        "otm_pct": strategy.get("otm_pct", 0.05),
        "spread_width": strategy.get("spread_width", 10.0),
        "credit_fraction": strategy.get("credit_fraction", 0.35),
        "profit_target_pct": risk.get("profit_target", 50) / 100.0,
        "stop_loss_multiplier": risk.get("stop_loss_multiplier", 2.5),
        "momentum_filter_pct": risk.get("momentum_filter_pct", 5.0),
        "trend_ma_period": technical.get("slow_ma", 20),
        "max_risk_pct": risk.get("max_risk_per_trade", 2.0) / 100.0,
        "scan_weekday": "any",  # Live scanner runs on all market days
        "manage_dte": strategy.get("manage_dte", 0),
    }

    # Regime-adaptive per-regime overrides
    for regime in ("bull", "bear", "high_vol", "low_vol", "crash"):
        dir_key = f"regime_dir_{regime}"
        if dir_key in strategy:
            params[dir_key] = strategy[dir_key]
        scale_key = f"regime_scale_{regime}"
        if scale_key in risk:
            params[scale_key] = risk[scale_key]

    return params


def _extract_iron_condor_params(config: Dict) -> Dict[str, Any]:
    """Extract IronCondorStrategy params from nested config."""
    strategy = config.get("strategy", {})
    risk = config.get("risk", {})
    ic = strategy.get("iron_condor", {})

    return {
        "rsi_min": ic.get("rsi_min", 35),
        "rsi_max": ic.get("rsi_max", 60),
        "min_iv_rank": ic.get("min_iv_rank", 30.0),
        "target_dte": ic.get("target_dte", 35),
        "min_dte": ic.get("min_dte", 25),
        "otm_pct_put": ic.get("otm_pct_put", 0.05),
        "otm_pct_call": ic.get("otm_pct_call", 0.05),
        "spread_width": ic.get("spread_width", 10.0),
        "min_combined_credit_pct": ic.get("min_combined_credit_pct", 0.20),
        "profit_target_pct": ic.get("profit_target_pct", 0.50),
        "stop_loss_multiplier": ic.get("stop_loss_multiplier", 2.0),
        "max_risk_pct": ic.get("max_risk_pct", 3.5) / 100.0,
        "high_vol_size_scale": ic.get("high_vol_size_scale", 0.5),
        "manage_dte": strategy.get("manage_dte", 0),
    }


def _extract_straddle_strangle_params(config: Dict) -> Dict[str, Any]:
    """Extract StraddleStrangleStrategy params from nested config."""
    strategy = config.get("strategy", {})
    risk = config.get("risk", {})
    ss = strategy.get("straddle_strangle", {})

    params = {
        "mode": ss.get("mode", "short_post_event"),
        "target_dte": ss.get("target_dte", 7),
        "otm_pct": ss.get("otm_pct", 0.0),
        "event_iv_boost": ss.get("event_iv_boost", 0.30),
        "iv_crush_pct": ss.get("iv_crush_pct", 0.40),
        "profit_target_pct": ss.get("profit_target_pct", 0.50),
        "stop_loss_pct": ss.get("stop_loss_pct", 0.50),
        "max_risk_pct": risk.get("straddle_strangle_risk_pct", ss.get("max_risk_pct", 3.0)) / 100.0,
        "event_types": ss.get("event_types", "all"),
        "manage_dte": strategy.get("manage_dte", 0),
    }

    # SS regime scales
    for regime in ("bull", "bear", "high_vol", "low_vol", "crash"):
        key = f"regime_scale_{regime}"
        ss_key = f"ss_regime_scale_{regime}"
        if ss_key in risk:
            params[key] = risk[ss_key]
        elif key in ss:
            params[key] = ss[key]

    return params


def build_strategy_list(config: Dict) -> List:
    """Build strategy instances from config.

    Returns a list of (strategy_instance, strategy_name) tuples.
    Only includes strategies that are enabled in config.
    """
    from strategies.credit_spread import CreditSpreadStrategy
    from strategies.iron_condor import IronCondorStrategy
    from strategies.straddle_strangle import StraddleStrangleStrategy

    strategies = []

    # Credit spread — always enabled
    cs_params = _extract_credit_spread_params(config)
    strategies.append(CreditSpreadStrategy(cs_params))
    logger.info("Strategy factory: CreditSpreadStrategy enabled (direction=%s)", cs_params["direction"])

    # Iron condor — enabled if config section exists and enabled=true
    ic_config = config.get("strategy", {}).get("iron_condor", {})
    if ic_config.get("enabled", False):
        ic_params = _extract_iron_condor_params(config)
        strategies.append(IronCondorStrategy(ic_params))
        logger.info("Strategy factory: IronCondorStrategy enabled")

    # Straddle/strangle — enabled if config section exists and enabled=true
    ss_config = config.get("strategy", {}).get("straddle_strangle", {})
    if ss_config.get("enabled", False):
        ss_params = _extract_straddle_strangle_params(config)
        strategies.append(StraddleStrangleStrategy(ss_params))
        logger.info("Strategy factory: StraddleStrangleStrategy enabled (mode=%s)", ss_params["mode"])

    return strategies
