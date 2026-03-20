"""Binance perpetual futures funding rate collector.

Public endpoints — no API key required.
Docs: https://binance-docs.github.io/apidocs/futures/en/#get-funding-rate-history

All functions return None / [] on any error — never raise.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Dict, List, Optional

import requests

_LOG = logging.getLogger(__name__)

_BASE_URL = "https://fapi.binance.com/fapi/v1"
_TIMEOUT = 10
_MAX_RETRIES = 3


def _get(path: str, params: Optional[Dict] = None):
    """GET {_BASE_URL}/{path} with retries."""
    url = f"{_BASE_URL}/{path}"
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt < _MAX_RETRIES - 1:
                wait = 2 ** attempt
                _LOG.warning(
                    "Binance request failed (attempt %d/%d): %s — retry in %ds",
                    attempt + 1, _MAX_RETRIES, exc, wait,
                )
                time.sleep(wait)
            else:
                _LOG.error(
                    "Binance request failed after %d attempts: %s", _MAX_RETRIES, exc
                )
    return None


def _current_funding(symbol: str) -> Optional[float]:
    """Return the most recent settled funding rate for *symbol*."""
    # fundingRate endpoint returns most recent records; limit=1 gives the latest settled rate.
    data = _get("fundingRate", {"symbol": symbol, "limit": 1})
    if not data:
        return None
    try:
        return float(data[0]["fundingRate"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        _LOG.error("Unexpected Binance funding rate payload for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_btc_funding() -> Optional[float]:
    """Return the current BTC/USDT perpetual funding rate as a float, or None on error."""
    return _current_funding("BTCUSDT")


def get_eth_funding() -> Optional[float]:
    """Return the current ETH/USDT perpetual funding rate as a float, or None on error."""
    return _current_funding("ETHUSDT")


def get_funding_history(symbol: str, days: int = 30) -> List[Dict]:
    """Return historical funding rates for *symbol* over the past *days* days.

    Binance settles funding every 8 hours (3 × per day), so 30 days ≈ 90 records.

    Each entry::

        {"symbol": str, "funding_rate": float, "funding_time": int (ms epoch)}

    Returns [] on error.
    """
    start_ms = int(
        (datetime.datetime.utcnow() - datetime.timedelta(days=days)).timestamp() * 1000
    )
    data = _get("fundingRate", {"symbol": symbol, "startTime": start_ms, "limit": 1000})
    if data is None:
        return []
    try:
        return [
            {
                "symbol": entry["symbol"],
                "funding_rate": float(entry["fundingRate"]),
                "funding_time": int(entry["fundingTime"]),
            }
            for entry in data
        ]
    except (KeyError, TypeError, ValueError) as exc:
        _LOG.error("Unexpected Binance funding history payload: %s", exc)
        return []
