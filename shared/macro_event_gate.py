# Compatibility shim — canonical module is compass.events
from compass.events import *  # noqa: F401,F403
from compass.events import (  # noqa: F401 — explicit re-exports
    ALL_FOMC_DATES,
    get_upcoming_events,
    compute_composite_scaling,
    run_daily_event_check,
)
