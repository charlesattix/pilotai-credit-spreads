"""Tests for shared/deviation_tracker.py — persistent deviation tracking."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from shared.database import init_db
from shared.deviation_tracker import (
    _upsert_snapshot,
    check_deviation_alerts,
    get_deviation_history,
    get_latest_deviation,
    record_deviation_snapshot,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Create a temp DB with schema initialized."""
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def _make_live_metrics(total=10, win_rate=65.0, pnl=500.0, pf=1.8, dd=-3.5, ret=0.5):
    """Build a realistic live metrics dict."""
    return {
        "total_trades": total,
        "winning_trades": int(total * win_rate / 100),
        "losing_trades": total - int(total * win_rate / 100),
        "win_rate": win_rate,
        "total_pnl": pnl,
        "avg_win": 100.0,
        "avg_loss": 50.0,
        "profit_factor": pf,
        "return_pct": ret,
        "max_drawdown": dd,
        "per_strategy": {"credit_spread": {"total_trades": total, "win_rate": win_rate, "total_pnl": pnl}},
        "start_date": "2026-03-01",
        "end_date": "2026-03-07",
    }


def _make_backtest_results(total=12, win_rate=70.0, pnl=600.0, pf=2.0, dd=-4.0, ret=0.6):
    """Build a realistic backtest results dict."""
    return {
        "combined": {
            "total_trades": total,
            "win_rate": win_rate,
            "total_pnl": pnl,
            "avg_win": 110.0,
            "avg_loss": 55.0,
            "profit_factor": pf,
            "return_pct": ret,
            "max_drawdown": dd,
        },
        "per_strategy": {"credit_spread": {"total_trades": total, "win_rate": win_rate, "total_pnl": pnl}},
    }


def _make_trades(n=10, pnl_each=50.0):
    """Build a list of mock trade dicts."""
    trades = []
    for i in range(n):
        trades.append({
            "id": f"trade-{i}",
            "ticker": "SPY",
            "strategy_type": "credit_spread",
            "status": "closed_profit" if pnl_each > 0 else "closed_loss",
            "pnl": pnl_each,
            "entry_date": f"2026-03-0{min(i+1, 9)}",
            "exit_date": f"2026-03-0{min(i+2, 9)}",
        })
    return trades


# ---------------------------------------------------------------------------
# TestRecordDeviation
# ---------------------------------------------------------------------------

class TestRecordDeviation:
    """Tests for record_deviation_snapshot()."""

    @patch("scripts.live_vs_backtest.load_live_trades")
    @patch("scripts.live_vs_backtest.compute_live_metrics")
    @patch("scripts.live_vs_backtest.run_backtest_for_range")
    @patch("scripts.live_vs_backtest.compare_metrics")
    def test_snapshot_persisted(self, mock_compare, mock_bt, mock_metrics, mock_trades, db_path):
        """Full snapshot with backtest is persisted correctly."""
        mock_trades.return_value = _make_trades(10)
        mock_metrics.return_value = _make_live_metrics()
        mock_bt.return_value = _make_backtest_results()
        mock_compare.return_value = [
            {"metric": "Win Rate", "status": "PASS", "live_str": "65.0%", "backtest_str": "70.0%",
             "live_value": 65.0, "backtest_value": 70.0, "deviation_str": "-5.0pp", "deviation_pct": -5.0},
        ]

        result = record_deviation_snapshot(db_path=db_path)

        assert result is not None
        assert result["live_trades"] == 10
        assert result["overall_status"] == "PASS"

        # Verify persisted in DB
        stored = get_latest_deviation(db_path)
        assert stored is not None
        assert stored["live_trades"] == 10
        assert stored["overall_status"] == "PASS"

    @patch("scripts.live_vs_backtest.load_live_trades")
    @patch("scripts.live_vs_backtest.compute_live_metrics")
    def test_empty_trades_returns_none(self, mock_metrics, mock_trades, db_path):
        """No closed trades → returns None."""
        mock_trades.return_value = []
        mock_metrics.return_value = {"total_trades": 0}

        result = record_deviation_snapshot(db_path=db_path)
        assert result is None

    @patch("scripts.live_vs_backtest.load_live_trades")
    @patch("scripts.live_vs_backtest.compute_live_metrics")
    def test_few_trades_live_only(self, mock_metrics, mock_trades, db_path):
        """< 5 trades → live-only snapshot, bt fields null."""
        mock_trades.return_value = _make_trades(3)
        mock_metrics.return_value = _make_live_metrics(total=3)

        result = record_deviation_snapshot(db_path=db_path)

        assert result is not None
        assert result["live_trades"] == 3
        assert result["bt_trades"] is None
        assert result["bt_win_rate"] is None
        assert result["overall_status"] == "INFO"

    @patch("scripts.live_vs_backtest.load_live_trades")
    @patch("scripts.live_vs_backtest.compute_live_metrics")
    def test_snapshot_date_populated(self, mock_metrics, mock_trades, db_path):
        """snapshot_date is today's date."""
        mock_trades.return_value = _make_trades(3)
        mock_metrics.return_value = _make_live_metrics(total=3)

        result = record_deviation_snapshot(db_path=db_path)
        assert result["snapshot_date"] == datetime.now().strftime("%Y-%m-%d")

    @patch("scripts.live_vs_backtest.load_live_trades")
    @patch("scripts.live_vs_backtest.compute_live_metrics")
    @patch("scripts.live_vs_backtest.run_backtest_for_range")
    @patch("scripts.live_vs_backtest.compare_metrics")
    def test_overall_status_worst(self, mock_compare, mock_bt, mock_metrics, mock_trades, db_path):
        """overall_status reflects the worst metric status."""
        mock_trades.return_value = _make_trades(10)
        mock_metrics.return_value = _make_live_metrics()
        mock_bt.return_value = _make_backtest_results()
        mock_compare.return_value = [
            {"metric": "Win Rate", "status": "PASS", "live_str": "65%", "backtest_str": "70%",
             "live_value": 65, "backtest_value": 70, "deviation_str": "-5pp", "deviation_pct": -5},
            {"metric": "Profit Factor", "status": "FAIL", "live_str": "0.8", "backtest_str": "2.0",
             "live_value": 0.8, "backtest_value": 2.0, "deviation_str": "-60%", "deviation_pct": -60},
        ]

        result = record_deviation_snapshot(db_path=db_path)
        assert result["overall_status"] == "FAIL"


# ---------------------------------------------------------------------------
# TestGetHistory
# ---------------------------------------------------------------------------

class TestGetHistory:
    """Tests for get_deviation_history()."""

    def test_ordered_newest_first(self, db_path):
        """Snapshots returned newest-first."""
        for i in range(3):
            _upsert_snapshot({
                "snapshot_date": f"2026-03-0{i+1}",
                "live_trades": 10 + i,
                "overall_status": "PASS",
                "details": {},
            }, db_path)

        history = get_deviation_history(days=30, db_path=db_path)
        assert len(history) == 3
        assert history[0]["snapshot_date"] == "2026-03-03"
        assert history[2]["snapshot_date"] == "2026-03-01"

    def test_respects_days_param(self, db_path):
        """Only returns snapshots within the last N days."""
        today = datetime.now()
        _upsert_snapshot({
            "snapshot_date": today.strftime("%Y-%m-%d"),
            "live_trades": 10,
            "overall_status": "PASS",
            "details": {},
        }, db_path)
        _upsert_snapshot({
            "snapshot_date": (today - timedelta(days=60)).strftime("%Y-%m-%d"),
            "live_trades": 5,
            "overall_status": "WARN",
            "details": {},
        }, db_path)

        history = get_deviation_history(days=30, db_path=db_path)
        assert len(history) == 1
        assert history[0]["live_trades"] == 10

    def test_empty_db(self, db_path):
        """Empty DB → empty list."""
        history = get_deviation_history(db_path=db_path)
        assert history == []


# ---------------------------------------------------------------------------
# TestGetLatest
# ---------------------------------------------------------------------------

class TestGetLatest:
    """Tests for get_latest_deviation()."""

    def test_returns_most_recent(self, db_path):
        """Returns the most recent snapshot."""
        _upsert_snapshot({"snapshot_date": "2026-03-01", "live_trades": 5, "overall_status": "PASS", "details": {}}, db_path)
        _upsert_snapshot({"snapshot_date": "2026-03-05", "live_trades": 15, "overall_status": "WARN", "details": {}}, db_path)

        latest = get_latest_deviation(db_path)
        assert latest["snapshot_date"] == "2026-03-05"
        assert latest["live_trades"] == 15

    def test_empty_db_returns_none(self, db_path):
        """Empty DB → None."""
        assert get_latest_deviation(db_path) is None


# ---------------------------------------------------------------------------
# TestCheckAlerts
# ---------------------------------------------------------------------------

class TestCheckAlerts:
    """Tests for check_deviation_alerts()."""

    def test_all_pass_empty(self):
        """All PASS → empty list."""
        snapshot = {
            "details": {
                "comparisons": [
                    {"metric": "Win Rate", "status": "PASS", "live_str": "65%", "backtest_str": "70%"},
                    {"metric": "Profit Factor", "status": "PASS", "live_str": "1.8", "backtest_str": "2.0"},
                ]
            }
        }
        assert check_deviation_alerts(snapshot) == []

    def test_warn_metrics(self):
        """WARN metrics → warning strings."""
        snapshot = {
            "details": {
                "comparisons": [
                    {"metric": "Win Rate", "status": "WARN", "live_str": "55.0%", "backtest_str": "70.0%"},
                ]
            }
        }
        alerts = check_deviation_alerts(snapshot)
        assert len(alerts) == 1
        assert "Win Rate" in alerts[0]
        assert "WARN" in alerts[0]

    def test_fail_metrics(self):
        """FAIL metrics → failure strings."""
        snapshot = {
            "details": {
                "comparisons": [
                    {"metric": "Profit Factor", "status": "FAIL", "live_str": "0.5", "backtest_str": "2.0"},
                ]
            }
        }
        alerts = check_deviation_alerts(snapshot)
        assert len(alerts) == 1
        assert "FAIL" in alerts[0]
        assert "Profit Factor" in alerts[0]

    def test_mixed_statuses(self):
        """Mixed statuses → only WARN/FAIL included."""
        snapshot = {
            "details": {
                "comparisons": [
                    {"metric": "Win Rate", "status": "PASS", "live_str": "65%", "backtest_str": "70%"},
                    {"metric": "Profit Factor", "status": "WARN", "live_str": "1.2", "backtest_str": "2.0"},
                    {"metric": "Max Drawdown", "status": "FAIL", "live_str": "-15%", "backtest_str": "-5%"},
                    {"metric": "Total Trades", "status": "INFO", "live_str": "10", "backtest_str": "12"},
                ]
            }
        }
        alerts = check_deviation_alerts(snapshot)
        assert len(alerts) == 2
        metrics = [a.split(" deviation")[0] for a in alerts]
        assert "Profit Factor" in metrics
        assert "Max Drawdown" in metrics

    def test_per_strategy_deviations(self):
        """Per-strategy WARN/FAIL included in alerts."""
        snapshot = {
            "details": {
                "comparisons": [
                    {"metric": "credit_spread WR", "status": "WARN",
                     "live_str": "50.0%", "backtest_str": "70.0%"},
                    {"metric": "iron_condor WR", "status": "PASS",
                     "live_str": "68.0%", "backtest_str": "65.0%"},
                ]
            }
        }
        alerts = check_deviation_alerts(snapshot)
        assert len(alerts) == 1
        assert "credit_spread WR" in alerts[0]
