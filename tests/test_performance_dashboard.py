"""Tests for scripts/performance_dashboard.py data aggregation functions."""

from unittest.mock import patch

import pytest

from scripts.performance_dashboard import (
    compute_avg_credit_comparison,
    compute_cumulative_pnl,
    compute_rolling_win_rate,
    compute_strategy_breakdown,
    generate_dashboard,
    load_closed_trades,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _trade(status="closed_profit", pnl=50, exit_date="2026-01-15", strategy_type="credit_spread", credit=0.45):
    return {
        "id": f"t-{exit_date}-{pnl}",
        "status": status,
        "pnl": pnl,
        "exit_date": exit_date,
        "entry_date": "2026-01-01",
        "strategy_type": strategy_type,
        "credit": credit,
        "ticker": "SPY",
    }


# ── TestLoadClosedTrades ─────────────────────────────────────────────────────

class TestLoadClosedTrades:
    @patch("scripts.performance_dashboard.get_trades")
    def test_filters_out_open_trades(self, mock_get):
        mock_get.return_value = [
            _trade(status="open", pnl=0),
            _trade(status="closed_profit", pnl=50),
            _trade(status="pending", pnl=0),
            _trade(status="closed_loss", pnl=-30),
        ]
        result = load_closed_trades()
        assert len(result) == 2
        assert all(t["status"].startswith("closed") for t in result)

    @patch("scripts.performance_dashboard.get_trades")
    def test_sorts_by_exit_date(self, mock_get):
        mock_get.return_value = [
            _trade(status="closed_profit", exit_date="2026-03-01"),
            _trade(status="closed_loss", exit_date="2026-01-15"),
            _trade(status="closed_expiry", exit_date="2026-02-10"),
        ]
        result = load_closed_trades()
        dates = [t["exit_date"] for t in result]
        assert dates == ["2026-01-15", "2026-02-10", "2026-03-01"]


# ── TestComputeCumulativePnl ─────────────────────────────────────────────────

class TestComputeCumulativePnl:
    def test_empty_trades(self):
        assert compute_cumulative_pnl([]) == []

    def test_single_trade(self):
        trades = [_trade(pnl=100, exit_date="2026-01-10")]
        result = compute_cumulative_pnl(trades, account_size=50_000)
        assert len(result) == 1
        assert result[0]["cumulative_pnl"] == 100
        assert result[0]["balance"] == 50_100

    def test_multiple_trades_same_day_grouped(self):
        trades = [
            _trade(pnl=50, exit_date="2026-01-10"),
            _trade(pnl=-20, exit_date="2026-01-10"),
            _trade(pnl=30, exit_date="2026-01-11"),
        ]
        result = compute_cumulative_pnl(trades, account_size=100_000)
        assert len(result) == 2  # two distinct dates
        assert result[0]["date"] == "2026-01-10"
        assert result[0]["cumulative_pnl"] == 30  # 50 + (-20)
        assert result[1]["cumulative_pnl"] == 60  # 30 + 30


# ── TestComputeRollingWinRate ────────────────────────────────────────────────

class TestComputeRollingWinRate:
    def test_fewer_than_window(self):
        trades = [_trade() for _ in range(5)]
        assert compute_rolling_win_rate(trades, window=20) == []

    def test_exactly_window_size(self):
        trades = [_trade(pnl=10) for _ in range(20)]
        result = compute_rolling_win_rate(trades, window=20)
        assert len(result) == 1
        assert result[0]["win_rate"] == 100.0
        assert result[0]["trade_num"] == 20

    def test_correct_win_rate_calculation(self):
        # 15 winners, 5 losers = 75% in first window
        trades = [_trade(pnl=10) for _ in range(15)] + [_trade(pnl=-10) for _ in range(5)]
        result = compute_rolling_win_rate(trades, window=20)
        assert len(result) == 1
        assert result[0]["win_rate"] == 75.0


# ── TestComputeStrategyBreakdown ─────────────────────────────────────────────

class TestComputeStrategyBreakdown:
    def test_groups_by_strategy(self):
        trades = [
            _trade(strategy_type="credit_spread", pnl=50),
            _trade(strategy_type="iron_condor", pnl=-20),
            _trade(strategy_type="credit_spread", pnl=30),
        ]
        result = compute_strategy_breakdown(trades)
        assert len(result) == 2
        strats = {s["strategy"] for s in result}
        assert strats == {"credit_spread", "iron_condor"}

    def test_correct_win_rate_and_avg_pnl(self):
        trades = [
            _trade(strategy_type="credit_spread", pnl=100),
            _trade(strategy_type="credit_spread", pnl=-50),
            _trade(strategy_type="credit_spread", pnl=80),
        ]
        result = compute_strategy_breakdown(trades)
        assert len(result) == 1
        s = result[0]
        assert s["count"] == 3
        assert s["wins"] == 2
        assert s["win_rate"] == pytest.approx(66.7, abs=0.1)
        assert s["total_pnl"] == 130
        assert s["avg_pnl"] == pytest.approx(43.33, abs=0.01)


# ── TestComputeAvgCreditComparison ───────────────────────────────────────────

class TestComputeAvgCreditComparison:
    def test_avg_credit(self):
        trades = [
            _trade(strategy_type="credit_spread", credit=0.40),
            _trade(strategy_type="credit_spread", credit=0.60),
            _trade(strategy_type="iron_condor", credit=1.20),
        ]
        result = compute_avg_credit_comparison(trades)
        assert result["credit_spread"] == pytest.approx(0.50)
        assert result["iron_condor"] == pytest.approx(1.20)


# ── TestGenerateDashboard ────────────────────────────────────────────────────

class TestGenerateDashboard:
    @patch("scripts.performance_dashboard.get_deviation_history", return_value=[])
    @patch("scripts.performance_dashboard.get_trades")
    def test_returns_valid_html_with_expected_sections(self, mock_trades, mock_dev):
        mock_trades.return_value = [
            _trade(status="closed_profit", pnl=100, exit_date="2026-01-10"),
            _trade(status="closed_loss", pnl=-40, exit_date="2026-01-11"),
            _trade(status="open", pnl=0),
        ]
        html = generate_dashboard(report_date="2026-03-07")
        assert "<!DOCTYPE html>" in html
        assert "Paper Trading Dashboard" in html
        assert "Key Metrics" in html
        assert "Strategy Breakdown" in html
        assert "2026-03-07" in html

    @patch("scripts.performance_dashboard.get_deviation_history", return_value=[])
    @patch("scripts.performance_dashboard.get_trades", return_value=[])
    def test_handles_zero_trades_gracefully(self, mock_trades, mock_dev):
        html = generate_dashboard(report_date="2026-03-07")
        assert "<!DOCTYPE html>" in html
        assert "No closed trades yet" in html
