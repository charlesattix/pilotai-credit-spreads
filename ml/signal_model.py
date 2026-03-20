# Compatibility shim — canonical module is compass.signal_model
from compass.signal_model import *  # noqa: F401,F403
from compass.signal_model import SignalModel  # noqa: F401 — explicit re-export
