# Compatibility shim — canonical module is compass.risk_gate
from compass.risk_gate import *  # noqa: F401,F403
from compass.risk_gate import RiskGate, _directions_match  # noqa: F401 — explicit re-exports
