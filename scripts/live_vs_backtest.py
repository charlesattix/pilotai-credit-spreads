"""Live vs backtest comparison utilities.

Stub module — functions are used by shared/deviation_tracker.py and patched
in tests/test_deviation_tracker.py.
"""


def load_live_trades(db_path, **kwargs):
    """Load closed trades from the live trading database."""
    raise NotImplementedError("stub — implement or use via mock.patch")


def compute_live_metrics(trades):
    """Compute aggregate metrics from a list of closed trades."""
    raise NotImplementedError("stub — implement or use via mock.patch")


def run_backtest_for_range(start, end, **kwargs):
    """Run backtester over the same date range as live trades."""
    raise NotImplementedError("stub — implement or use via mock.patch")


def compare_metrics(live_metrics, bt_metrics):
    """Compare live vs backtest metrics and produce deviation report."""
    raise NotImplementedError("stub — implement or use via mock.patch")
