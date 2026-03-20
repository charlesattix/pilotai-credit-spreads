# Compatibility shim — canonical module is compass.regime
from compass.regime import *  # noqa: F401,F403
from compass.regime import Regime, RegimeClassifier, REGIME_INFO  # noqa: F401 — explicit re-exports
