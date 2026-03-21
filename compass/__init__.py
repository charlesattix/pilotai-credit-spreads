"""compass — market regime, sizing, and risk analysis package."""

from compass.regime import Regime, RegimeClassifier, REGIME_INFO, ComboRegimeDetector
from compass.macro import MacroSnapshotEngine
from compass.macro_db import (
    init_db,
    get_db,
    get_current_macro_score,
    get_sector_rankings,
    get_event_scaling_factor,
    get_eligible_underlyings,
    save_snapshot,
    MACRO_DB_PATH,
    LIQUID_SECTOR_ETFS,
)
from compass.events import (
    get_upcoming_events,
    compute_composite_scaling,
    run_daily_event_check,
    ALL_FOMC_DATES,
)
from compass.risk_gate import RiskGate
from compass.sizing import calculate_dynamic_risk, get_contract_size, PositionSizer
from compass.signal_model import SignalModel
from compass.features import FeatureEngine
from compass.iv_surface import IVAnalyzer
from compass.ml_strategy import MLEnhancedStrategy

__all__ = [
    # regime
    "Regime",
    "RegimeClassifier",
    "REGIME_INFO",
    "ComboRegimeDetector",
    # macro
    "MacroSnapshotEngine",
    # macro_db
    "init_db",
    "get_db",
    "get_current_macro_score",
    "get_sector_rankings",
    "get_event_scaling_factor",
    "get_eligible_underlyings",
    "save_snapshot",
    "MACRO_DB_PATH",
    "LIQUID_SECTOR_ETFS",
    # events
    "get_upcoming_events",
    "compute_composite_scaling",
    "run_daily_event_check",
    "ALL_FOMC_DATES",
    # risk
    "RiskGate",
    # sizing
    "calculate_dynamic_risk",
    "get_contract_size",
    "PositionSizer",
    # ML
    "SignalModel",
    "FeatureEngine",
    "IVAnalyzer",
    "MLEnhancedStrategy",
]
