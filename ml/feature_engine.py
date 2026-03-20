# Compatibility shim — canonical module is compass.features
from compass.features import *  # noqa: F401,F403
from compass.features import FeatureEngine  # noqa: F401 — explicit re-export
