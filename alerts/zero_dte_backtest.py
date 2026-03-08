"""
0DTE/1DTE credit spread backtest validator.

Runs the existing ``Backtester`` with the 0DTE config overlay and validates
that the strategy meets the MASTERPLAN target of 78%+ win rate on SPY/SPX.

Heavy dependencies (backtest module) are imported lazily inside methods
so that importing this module does not pull in pytz, requests, etc.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from alerts.zero_dte_config import build_zero_dte_config

logger = logging.getLogger(__name__)

# MASTERPLAN Phase 2 target thresholds
_TARGET_WIN_RATE = 78.0     # minimum acceptable win rate (%)
_TARGET_PROFIT_FACTOR = 1.5  # minimum acceptable profit factor


class ZeroDTEBacktestValidator:
    """Run and validate the 0DTE credit spread strategy via backtest.

    Wraps ``Backtester`` with the 0DTE config overlay and checks that
    backtest results meet MASTERPLAN success criteria.
    """

    def __init__(self, base_config: dict, historical_data=None):
        """
        Args:
            base_config: System-level configuration dict.
            historical_data: Optional ``HistoricalOptionsData`` for real
                Polygon data.  Falls back to heuristic mode if None.
        """
        self._base_config = base_config
        self._zero_dte_config = build_zero_dte_config(base_config)
        self._historical_data = historical_data

    def run(
        self,
        ticker: str = "SPY",
        lookback_days: int = 365,
    ) -> Dict:
        """Run the 0DTE backtest and return enriched results.

        Args:
            ticker: Ticker to backtest (SPY or SPX).
            lookback_days: Number of historical days.

        Returns:
            Results dict from ``Backtester.run_backtest`` enriched with
            ``validation`` sub-dict containing pass/fail status.
        """
        from backtest import Backtester

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=lookback_days)

        logger.info(
            "Running 0DTE backtest: ticker=%s, lookback=%d days",
            ticker, lookback_days,
        )

        backtester = Backtester(
            self._zero_dte_config,
            historical_data=self._historical_data,
        )
        results = backtester.run_backtest(ticker, start_date, end_date)

        if not results:
            logger.error("Backtest returned empty results")
            return {
                "total_trades": 0,
                "win_rate": 0,
                "validation": {
                    "passed": False,
                    "reason": "Backtest returned no results",
                },
            }

        # Enrich with validation
        results["validation"] = self._validate(results)
        return results

    def print_report(self, results: Dict) -> None:
        """Print a summary of 0DTE backtest results and validation."""
        from backtest import PerformanceMetrics

        perf = PerformanceMetrics(self._zero_dte_config)
        perf.print_summary(results)

        validation = results.get("validation", {})
        status = "PASS" if validation.get("passed") else "FAIL"
        print(f"\n0DTE Validation: {status}")
        print(f"  Win Rate:      {results.get('win_rate', 0):.1f}% (target: {_TARGET_WIN_RATE}%)")
        print(f"  Profit Factor: {results.get('profit_factor', 0):.2f} (target: {_TARGET_PROFIT_FACTOR})")
        print(f"  Total Trades:  {results.get('total_trades', 0)}")
        if not validation.get("passed"):
            print(f"  Reason:        {validation.get('reason', 'unknown')}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(results: Dict) -> Dict:
        """Check results against MASTERPLAN 0DTE targets.

        Returns:
            Dict with ``passed`` (bool) and ``reason`` (str).
        """
        total_trades = results.get("total_trades", 0)
        win_rate = results.get("win_rate", 0)
        profit_factor = results.get("profit_factor", 0)

        if total_trades < 10:
            return {
                "passed": False,
                "reason": f"Insufficient trades ({total_trades} < 10 minimum)",
            }

        if win_rate < _TARGET_WIN_RATE:
            return {
                "passed": False,
                "reason": (
                    f"Win rate {win_rate:.1f}% below target {_TARGET_WIN_RATE}%"
                ),
            }

        if profit_factor < _TARGET_PROFIT_FACTOR:
            return {
                "passed": False,
                "reason": (
                    f"Profit factor {profit_factor:.2f} below target "
                    f"{_TARGET_PROFIT_FACTOR}"
                ),
            }

        return {"passed": True, "reason": "All targets met"}
