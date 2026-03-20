# Compatibility shim — canonical module is compass.macro
from compass.macro import *  # noqa: F401,F403
from compass.macro import MacroSnapshotEngine  # noqa: F401 — explicit re-export
