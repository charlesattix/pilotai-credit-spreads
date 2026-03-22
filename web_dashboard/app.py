"""
app.py — PilotAI Paper Trading Dashboard

FastAPI web app serving:
  GET /                                 — Live HTML dashboard (public)
  GET /api/v1/health                    — Health check (public)
  GET /api/v1/experiments               — All experiments (auth required)
  GET /api/v1/experiments/{id}/trades   — Trade history (auth required)
  GET /api/v1/experiments/{id}/positions — Open positions (auth required)
  GET /api/v1/summary                   — Combined summary (auth required)

Environment variables:
  PILOTAI_ROOT     — path to pilotai-credit-spreads repo (default: parent dir)
  DASHBOARD_API_KEY — API key for /api/ endpoints (default: dev-pilotai-2026)
  PORT             — listen port (default: 8000)
  STARTING_EQUITY  — account size for % calculations (default: 100000)

Run locally:
  cd ~/projects/pilotai-credit-spreads
  uvicorn web_dashboard.app:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader

from .data import (
    get_all_experiments,
    get_positions,
    get_trades,
    load_registry,
    query_all_live,
    query_experiment,
    summary_all,
)
from .html import render_dashboard

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)

_DEFAULT_API_KEY = "dev-pilotai-2026"
_API_KEY         = os.environ.get("DASHBOARD_API_KEY", _DEFAULT_API_KEY)
_RATE_LIMIT      = 120      # requests per 60s per key
_RATE_WINDOW     = 60.0

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PilotAI Paper Trading Dashboard",
    description="Live dashboard for paper trading experiments",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth + rate limiting
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_rate_windows: dict[str, deque] = defaultdict(deque)


def _check_rate(key: str) -> None:
    now = time.time()
    win = _rate_windows[key]
    while win and win[0] < now - _RATE_WINDOW:
        win.popleft()
    if len(win) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    win.append(now)


def require_api_key(api_key: Optional[str] = Depends(_api_key_header)) -> str:
    if not api_key or api_key != _API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    _check_rate(api_key)
    return api_key


# ---------------------------------------------------------------------------
# Cache (simple in-memory, TTL 60s for dashboard, 30s for API)
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, fn):
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < ttl:
        return entry[1]
    result = fn()
    _cache[key] = (time.time(), result)
    return result


# ---------------------------------------------------------------------------
# Routes — public
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    """Live paper trading dashboard — public, auto-refreshes every 5 minutes."""
    try:
        all_stats = _cached("dashboard_stats", 60.0, query_all_live)
        html = render_dashboard(all_stats)
        return HTMLResponse(content=html, status_code=200)
    except Exception as e:
        logger.exception("Dashboard render failed")
        return HTMLResponse(
            content=f"<pre>Dashboard error: {e}</pre>",
            status_code=500,
        )


@app.get("/api/v1/health")
async def health():
    """Health check — no auth required."""
    try:
        registry = load_registry()
        live_count = sum(
            1 for e in registry["experiments"].values()
            if e.get("status") == "paper_trading"
        )
        return {
            "status":           "ok",
            "live_experiments": live_count,
            "registry_version": registry.get("schema_version"),
            "timestamp":        datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(e)},
        )


# ---------------------------------------------------------------------------
# Routes — authenticated
# ---------------------------------------------------------------------------

@app.get("/api/v1/experiments")
async def list_experiments(_key: str = Depends(require_api_key)):
    """All experiments from registry (all statuses)."""
    registry = _cached("registry", 30.0, load_registry)
    exps = get_all_experiments(registry)
    return {
        "schema_version": registry.get("schema_version"),
        "last_updated":   registry.get("last_updated"),
        "count":          len(exps),
        "experiments":    exps,
    }


@app.get("/api/v1/experiments/{exp_id}/trades")
async def experiment_trades(
    exp_id: str,
    limit: int = 100,
    _key: str = Depends(require_api_key),
):
    """Trade history for one experiment (closed trades, newest first)."""
    registry = _cached("registry", 30.0, load_registry)
    exp = registry["experiments"].get(exp_id.upper())
    if not exp:
        raise HTTPException(status_code=404, detail=f"{exp_id} not found in registry")
    trades = get_trades(exp, limit=min(limit, 500))
    return {
        "experiment_id": exp["id"],
        "name":          exp["name"],
        "count":         len(trades),
        "trades":        trades,
    }


@app.get("/api/v1/experiments/{exp_id}/positions")
async def experiment_positions(
    exp_id: str,
    _key: str = Depends(require_api_key),
):
    """Open positions for one experiment."""
    registry = _cached("registry", 30.0, load_registry)
    exp = registry["experiments"].get(exp_id.upper())
    if not exp:
        raise HTTPException(status_code=404, detail=f"{exp_id} not found in registry")
    positions = get_positions(exp)
    return {
        "experiment_id": exp["id"],
        "name":          exp["name"],
        "count":         len(positions),
        "positions":     positions,
    }


@app.get("/api/v1/summary")
async def summary(_key: str = Depends(require_api_key)):
    """Combined P&L summary across all live experiments."""
    return _cached("summary", 30.0, summary_all)


# ---------------------------------------------------------------------------
# Startup log
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _on_startup():
    from .data import PROJECT_ROOT, REGISTRY_PATH
    logger.info("=" * 60)
    logger.info("PilotAI Paper Trading Dashboard starting")
    logger.info(f"  PILOTAI_ROOT  : {PROJECT_ROOT}")
    logger.info(f"  Registry      : {REGISTRY_PATH} (exists={REGISTRY_PATH.exists()})")
    logger.info(f"  API key set   : {'custom' if _API_KEY != _DEFAULT_API_KEY else 'default (dev)'}")
    logger.info("=" * 60)

    if REGISTRY_PATH.exists():
        try:
            registry = load_registry()
            live = [e for e in registry["experiments"].values()
                    if e.get("status") == "paper_trading"]
            logger.info(f"  Live experiments: {[e['id'] for e in live]}")
        except Exception as e:
            logger.warning(f"  Could not load registry: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("web_dashboard.app:app", host="0.0.0.0", port=port, reload=False)
