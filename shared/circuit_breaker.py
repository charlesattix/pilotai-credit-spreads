"""Circuit breaker pattern for external API calls."""

import threading
import time
import logging

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit is open."""


class CircuitBreaker:
    """
    Circuit breaker that wraps external calls.

    States:
      - closed  : normal operation; failures are counted.
      - open    : calls are rejected immediately with CircuitOpenError.
      - half_open: one trial call is allowed to test recovery.

    Parameters:
        failure_threshold: number of consecutive failures before opening.
        reset_timeout: seconds to wait in open state before transitioning
                       to half_open.
    """

    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 60):
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._lock = threading.Lock()
        self._state = "closed"
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == "open":
                if time.time() - self._last_failure_time >= self._reset_timeout:
                    self._state = "half_open"
                    logger.info("Circuit breaker transitioning to half_open")
            return self._state

    def call(self, func, *args, **kwargs):
        """Execute *func* through the circuit breaker.

        Raises CircuitOpenError if the circuit is open.
        """
        current_state = self.state  # property handles open -> half_open

        if current_state == "open":
            raise CircuitOpenError(
                f"Circuit is open; call to {getattr(func, '__name__', func)} rejected"
            )

        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            self._record_failure()
            raise
        else:
            self._record_success()
            return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self._failure_threshold:
                self._state = "open"
                logger.warning(
                    f"Circuit breaker opened after {self._failure_count} consecutive failures"
                )

    def _record_success(self):
        with self._lock:
            if self._state == "half_open":
                logger.info("Circuit breaker reset to closed after successful half_open call")
            self._failure_count = 0
            self._state = "closed"

    def reset(self):
        """Manually reset the circuit breaker to closed."""
        with self._lock:
            self._failure_count = 0
            self._state = "closed"
            self._last_failure_time = 0.0
