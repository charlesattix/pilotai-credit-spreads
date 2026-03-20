# Compatibility shim — canonical module is compass.sizing
from compass.sizing import *  # noqa: F401,F403
from compass.sizing import (  # noqa: F401 — explicit re-exports
    PositionSizer,
    calculate_dynamic_risk,
    get_contract_size,
)
