"""
Minimal HTTP health check server for the credit spread system.

Provides two endpoints:
  GET /health          — simple liveness check (status + uptime)
  GET /health/detailed — component status, open positions, circuit breaker state

Usage::

    from shared.healthcheck import HealthCheckServer

    server = HealthCheckServer(port=8080)
    server.start()   # non-blocking — runs in background daemon thread
    # ...
    server.stop()

The server can be given callback functions to supply detailed status:

    def my_detailed() -> dict:
        return {
            "status": "healthy",
            "components": {"alpaca": "connected", "db": "connected"},
            "open_positions": 3,
        }

    server = HealthCheckServer(port=8080, detailed_callback=my_detailed)
"""

import json
import logging
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    """HTTP request handler that delegates to the HealthCheckServer's callbacks."""

    def do_GET(self):
        if self.path in ("/health", "/"):
            body = self.server._health_cb()
            status_str = body.get("status", "unknown")
            http_status = 200 if status_str in ("healthy", "ok") else 503
            self._respond(http_status, body)
        elif self.path == "/health/detailed":
            body = self.server._detailed_cb()
            status_str = body.get("status", "unknown")
            http_status = 200 if status_str in ("healthy", "ok") else 503
            self._respond(http_status, body)
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, status: int, body: Dict) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass  # suppress noisy default access logging


class HealthCheckServer:
    """Background HTTP server exposing /health endpoints.

    Thread-safe: callbacks should return a snapshot of state without blocking.
    """

    def __init__(
        self,
        port: int = 8080,
        health_callback: Optional[Callable[[], Dict]] = None,
        detailed_callback: Optional[Callable[[], Dict]] = None,
    ):
        """
        Args:
            port: TCP port to listen on.
            health_callback: Returns basic health dict. Defaults to built-in.
            detailed_callback: Returns detailed component status dict. Defaults to built-in.
        """
        self._port = port
        self._start_time = datetime.now(timezone.utc)
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._health_cb = health_callback or self._default_health
        self._detailed_cb = detailed_callback or self._default_detailed

    def start(self) -> None:
        """Start the health check server in a background daemon thread."""
        self._server = HTTPServer(("", self._port), _Handler)
        # Attach callbacks to the server object so _Handler can access them
        self._server._health_cb = self._health_cb
        self._server._detailed_cb = self._detailed_cb
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="healthcheck"
        )
        self._thread.start()
        logger.info("HealthCheckServer listening on port %d", self._port)

    def stop(self) -> None:
        """Shut down the HTTP server."""
        if self._server:
            self._server.shutdown()
            logger.info("HealthCheckServer stopped")

    # ------------------------------------------------------------------
    # Default callbacks
    # ------------------------------------------------------------------

    def _default_health(self) -> Dict:
        uptime = int((datetime.now(timezone.utc) - self._start_time).total_seconds())
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": uptime,
        }

    def _default_detailed(self) -> Dict:
        base = self._default_health()
        base["components"] = {}
        return base
