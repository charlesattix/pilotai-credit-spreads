"""Tests for shared/reconciler.py — PositionReconciler."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from shared.reconciler import (
    PositionReconciler,
    ReconciliationResult,
    _PENDING_MAX_AGE_HOURS,
    _TERMINAL_ORDER_STATES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(
    trade_id="t-001",
    status="pending_open",
    client_order_id="abc-123",
    entry_date=None,
    ticker="SPY",
):
    """Return a minimal trade dict matching database shape."""
    if entry_date is None:
        entry_date = datetime.now(timezone.utc).isoformat()
    return {
        "id": trade_id,
        "ticker": ticker,
        "status": status,
        "alpaca_client_order_id": client_order_id,
        "entry_date": entry_date,
    }


def _make_alpaca():
    """Return a mock AlpacaProvider."""
    return MagicMock()


# Patch targets for the database functions imported inside reconciler methods
_DB_PATCH_BASE = "shared.database"
_GET_TRADES = f"{_DB_PATCH_BASE}.get_trades"
_UPSERT_TRADE = f"{_DB_PATCH_BASE}.upsert_trade"
_INSERT_EVENT = f"{_DB_PATCH_BASE}.insert_reconciliation_event"


# ===================================================================
# ReconciliationResult
# ===================================================================

class TestReconciliationResult:

    def test_empty_is_falsy(self):
        r = ReconciliationResult()
        assert not r

    def test_resolved_is_truthy(self):
        r = ReconciliationResult()
        r.pending_resolved = 1
        assert r

    def test_failed_is_truthy(self):
        r = ReconciliationResult()
        r.pending_failed = 1
        assert r

    def test_errors_is_truthy(self):
        r = ReconciliationResult()
        r.errors.append("something broke")
        assert r

    def test_repr(self):
        r = ReconciliationResult()
        r.pending_resolved = 2
        r.pending_failed = 1
        r.errors = ["e1"]
        s = repr(r)
        assert "resolved=2" in s
        assert "failed=1" in s
        assert "errors=1" in s


# ===================================================================
# _trade_age_hours
# ===================================================================

class TestTradeAgeHours:

    def test_recent_trade(self):
        now = datetime.now(timezone.utc)
        trade = _make_trade(entry_date=(now - timedelta(hours=2)).isoformat())
        age = PositionReconciler._trade_age_hours(trade, now)
        assert 1.9 < age < 2.1

    def test_old_trade(self):
        now = datetime.now(timezone.utc)
        trade = _make_trade(entry_date=(now - timedelta(hours=10)).isoformat())
        age = PositionReconciler._trade_age_hours(trade, now)
        assert 9.9 < age < 10.1

    def test_missing_entry_date_returns_large(self):
        """Missing entry_date should return 99 (treat as old)."""
        now = datetime.now(timezone.utc)
        trade = {"id": "t-001"}
        age = PositionReconciler._trade_age_hours(trade, now)
        assert age == 99.0

    def test_invalid_date_string_returns_large(self):
        now = datetime.now(timezone.utc)
        trade = {"id": "t-001", "entry_date": "not-a-date"}
        age = PositionReconciler._trade_age_hours(trade, now)
        assert age == 99.0

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetime string should be promoted to UTC."""
        now = datetime.now(timezone.utc)
        naive = (now - timedelta(hours=3)).replace(tzinfo=None).isoformat()
        trade = _make_trade(entry_date=naive)
        age = PositionReconciler._trade_age_hours(trade, now)
        assert 2.9 < age < 3.1

    def test_uses_created_at_fallback(self):
        """If entry_date is missing, should use created_at."""
        now = datetime.now(timezone.utc)
        trade = {
            "id": "t-001",
            "created_at": (now - timedelta(hours=5)).isoformat(),
        }
        age = PositionReconciler._trade_age_hours(trade, now)
        assert 4.9 < age < 5.1


# ===================================================================
# reconcile — no pending trades
# ===================================================================

class TestReconcileNoPending:

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES, return_value=[])
    def test_no_pending_trades(self, mock_get, mock_upsert, mock_event):
        """With no pending_open trades, result should be empty."""
        alpaca = _make_alpaca()
        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()
        assert not result
        assert result.pending_resolved == 0
        assert result.pending_failed == 0
        mock_upsert.assert_not_called()


# ===================================================================
# reconcile — DB-only trade (no alpaca_client_order_id)
# ===================================================================

class TestReconcileDBOnly:

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_no_order_id_promotes_to_open(self, mock_get, mock_upsert, mock_event):
        """Trade without alpaca_client_order_id should be promoted to open."""
        trade = _make_trade(client_order_id=None)
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()

        assert result.pending_resolved == 1
        assert result.pending_failed == 0
        mock_upsert.assert_called_once()
        saved = mock_upsert.call_args[0][0]
        assert saved["status"] == "open"

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_empty_string_order_id_promotes(self, mock_get, mock_upsert, mock_event):
        """Empty string alpaca_client_order_id should also promote."""
        trade = _make_trade(client_order_id="")
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()

        assert result.pending_resolved == 1


# ===================================================================
# reconcile — filled order
# ===================================================================

class TestReconcileFilledOrder:

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_filled_order_promotes_to_open(self, mock_get, mock_upsert, mock_event):
        """Alpaca order filled → promote trade to open with fill price."""
        trade = _make_trade()
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        alpaca.get_order_by_client_id.return_value = {
            "id": "alpaca-order-1",
            "status": "filled",
            "filled_avg_price": "4.52",
        }

        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()

        assert result.pending_resolved == 1
        assert result.pending_failed == 0
        saved = mock_upsert.call_args[0][0]
        assert saved["status"] == "open"
        assert saved["alpaca_fill_price"] == "4.52"

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_filled_order_records_event(self, mock_get, mock_upsert, mock_event):
        """Should insert a reconciliation event for confirmed fills."""
        trade = _make_trade(trade_id="t-filled")
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        alpaca.get_order_by_client_id.return_value = {
            "id": "alpaca-order-1",
            "status": "filled",
            "filled_avg_price": "4.52",
        }

        reconciler = PositionReconciler(alpaca)
        reconciler.reconcile()

        mock_event.assert_called_once()
        args = mock_event.call_args[0]
        assert args[0] == "t-filled"
        assert args[1] == "confirmed_filled"


# ===================================================================
# reconcile — terminal order states
# ===================================================================

class TestReconcileTerminalStates:

    @pytest.mark.parametrize("status", sorted(_TERMINAL_ORDER_STATES))
    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_terminal_state_marks_failed(self, mock_get, mock_upsert, mock_event, status):
        """Terminal Alpaca order states should mark trade as failed_open."""
        trade = _make_trade()
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        alpaca.get_order_by_client_id.return_value = {
            "id": "alpaca-order-1",
            "status": status,
        }

        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()

        assert result.pending_failed == 1
        assert result.pending_resolved == 0
        saved = mock_upsert.call_args[0][0]
        assert saved["status"] == "failed_open"
        assert saved["exit_reason"] == f"alpaca_{status}"


# ===================================================================
# reconcile — order not found (Alpaca returns None)
# ===================================================================

class TestReconcileOrderNotFound:

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_young_trade_left_pending(self, mock_get, mock_upsert, mock_event):
        """Trade younger than threshold should remain pending_open."""
        now = datetime.now(timezone.utc)
        trade = _make_trade(entry_date=(now - timedelta(hours=1)).isoformat())
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        alpaca.get_order_by_client_id.return_value = None

        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()

        assert result.pending_resolved == 0
        assert result.pending_failed == 0
        mock_upsert.assert_not_called()

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_old_trade_marked_failed(self, mock_get, mock_upsert, mock_event):
        """Trade older than threshold with no Alpaca order → failed_open."""
        now = datetime.now(timezone.utc)
        old_date = (now - timedelta(hours=_PENDING_MAX_AGE_HOURS + 1)).isoformat()
        trade = _make_trade(entry_date=old_date)
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        alpaca.get_order_by_client_id.return_value = None

        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()

        assert result.pending_failed == 1
        saved = mock_upsert.call_args[0][0]
        assert saved["status"] == "failed_open"
        assert saved["exit_reason"] == "alpaca_order_not_found"


# ===================================================================
# reconcile — still-live order (submitted, partially_filled, etc.)
# ===================================================================

class TestReconcileLiveOrder:

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_submitted_order_left_pending(self, mock_get, mock_upsert, mock_event):
        """Order still submitted should leave trade as pending_open."""
        trade = _make_trade()
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        alpaca.get_order_by_client_id.return_value = {
            "id": "alpaca-order-1",
            "status": "submitted",
        }

        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()

        assert result.pending_resolved == 0
        assert result.pending_failed == 0
        mock_upsert.assert_not_called()

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_partially_filled_left_pending(self, mock_get, mock_upsert, mock_event):
        """Partially filled order should be left as pending_open."""
        trade = _make_trade()
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        alpaca.get_order_by_client_id.return_value = {
            "id": "alpaca-order-1",
            "status": "partially_filled",
        }

        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()

        assert result.pending_resolved == 0
        assert result.pending_failed == 0


# ===================================================================
# reconcile — multiple trades in one pass
# ===================================================================

class TestReconcileMultiple:

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_multiple_trades_processed(self, mock_get, mock_upsert, mock_event):
        """Should process all pending trades in a single pass."""
        now = datetime.now(timezone.utc)
        trades = [
            _make_trade(trade_id="t-1", client_order_id=None),  # DB-only → resolved
            _make_trade(trade_id="t-2", client_order_id="ord-2"),  # filled → resolved
            _make_trade(trade_id="t-3", client_order_id="ord-3"),  # cancelled → failed
        ]
        mock_get.return_value = trades

        alpaca = _make_alpaca()
        def order_lookup(cid):
            if cid == "ord-2":
                return {"id": "a-2", "status": "filled", "filled_avg_price": "1.50"}
            if cid == "ord-3":
                return {"id": "a-3", "status": "cancelled"}
            return None
        alpaca.get_order_by_client_id.side_effect = order_lookup

        reconciler = PositionReconciler(alpaca)
        result = reconciler.reconcile()

        assert result.pending_resolved == 2  # t-1 (DB-only) + t-2 (filled)
        assert result.pending_failed == 1    # t-3 (cancelled)


# ===================================================================
# reconcile — db_path forwarding
# ===================================================================

class TestDBPathForwarding:

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES, return_value=[])
    def test_db_path_passed_to_get_trades(self, mock_get, mock_upsert, mock_event):
        """Custom db_path should be forwarded to get_trades."""
        alpaca = _make_alpaca()
        reconciler = PositionReconciler(alpaca, db_path="/tmp/test.db")
        reconciler.reconcile()
        mock_get.assert_called_once_with(status="pending_open", path="/tmp/test.db")

    @patch(_INSERT_EVENT)
    @patch(_UPSERT_TRADE)
    @patch(_GET_TRADES)
    def test_db_path_passed_to_upsert_and_event(self, mock_get, mock_upsert, mock_event):
        """Custom db_path should be forwarded to upsert_trade and insert_reconciliation_event."""
        trade = _make_trade(client_order_id=None)
        mock_get.return_value = [trade]

        alpaca = _make_alpaca()
        reconciler = PositionReconciler(alpaca, db_path="/tmp/test.db")
        reconciler.reconcile()

        # upsert_trade should get path kwarg
        _, kwargs = mock_upsert.call_args
        assert kwargs.get("path") == "/tmp/test.db"

        # insert_reconciliation_event should get db_path as positional arg
        event_args = mock_event.call_args[0]
        assert event_args[-1] == "/tmp/test.db"


# ===================================================================
# Terminal order states completeness
# ===================================================================

class TestTerminalStates:

    def test_terminal_states_is_frozenset(self):
        assert isinstance(_TERMINAL_ORDER_STATES, frozenset)

    def test_contains_expected_states(self):
        for s in ("cancelled", "expired", "rejected", "replaced", "done_for_day"):
            assert s in _TERMINAL_ORDER_STATES
