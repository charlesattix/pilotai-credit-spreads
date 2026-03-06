"""Tests for data providers: PolygonProvider, TradierProvider, AlpacaProvider.

All HTTP calls and SDK calls are mocked — no network access needed.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import requests

from shared.exceptions import ProviderError
from strategy.polygon_provider import PolygonProvider, MAX_PAGES
from strategy.tradier_provider import TradierProvider

# AlpacaProvider depends on the alpaca-py SDK which may not be installed.
try:
    from strategy.alpaca_provider import AlpacaProvider, _retry_with_backoff, _NO_RETRY
    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False

alpaca_required = pytest.mark.skipif(
    not _ALPACA_AVAILABLE, reason="alpaca-py SDK not installed",
)


# ===================================================================
# Helpers
# ===================================================================

def _mock_response(json_data, status_ok=True):
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.json.return_value = json_data
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    return resp


def _polygon_option_item(
    strike=440, contract_type="put", bid=3.0, ask=3.5,
    delta=-0.12, iv=0.25, close=3.0, volume=100,
    open_interest=500, underlying_price=450, exp_date="2026-04-10",
):
    """Build a single Polygon snapshot item."""
    return {
        "details": {
            "strike_price": strike,
            "contract_type": contract_type,
            "expiration_date": exp_date,
            "ticker": f"O:SPY{exp_date.replace('-','')}{contract_type[0].upper()}{int(strike*1000):08d}",
        },
        "greeks": {"delta": delta, "iv": iv, "gamma": 0.01, "theta": -0.05, "vega": 0.15},
        "day": {"close": close, "volume": volume},
        "last_quote": {"bid": bid, "ask": ask},
        "open_interest": open_interest,
        "underlying_asset": {"price": underlying_price},
    }


# ===================================================================
# 1. PolygonProvider
# ===================================================================

class TestPolygonInit:

    def test_empty_api_key_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            PolygonProvider(api_key="")

    def test_valid_key_sets_attributes(self):
        p = PolygonProvider(api_key="test-key")
        assert p.api_key == "test-key"
        assert p.base_url == "https://api.polygon.io"


class TestPolygonBuildOptionTicker:

    def test_call_format(self):
        exp = datetime(2024, 1, 19, tzinfo=timezone.utc)
        assert PolygonProvider.build_option_ticker("SPY", exp, "call", 450.0) == \
            "O:SPY240119C00450000"

    def test_put_format(self):
        exp = datetime(2026, 3, 20, tzinfo=timezone.utc)
        assert PolygonProvider.build_option_ticker("SPY", exp, "put", 500.0) == \
            "O:SPY260320P00500000"

    def test_fractional_strike(self):
        exp = datetime(2026, 6, 15, tzinfo=timezone.utc)
        assert PolygonProvider.build_option_ticker("AAPL", exp, "call", 182.50) == \
            "O:AAPL260615C00182500"


class TestPolygonBuildOptionRow:

    def test_complete_item(self):
        item = _polygon_option_item(
            strike=440, contract_type="put", bid=3.0, ask=3.5,
            delta=-0.12, underlying_price=450,
        )
        exp_dt = datetime(2026, 4, 10, tzinfo=timezone.utc)
        row = PolygonProvider._build_option_row(item, exp_dt)

        assert row["strike"] == 440
        assert row["type"] == "put"
        assert row["bid"] == 3.0
        assert row["ask"] == 3.5
        assert row["delta"] == -0.12
        assert row["iv"] == 0.25
        assert row["volume"] == 100
        assert row["open_interest"] == 500
        assert row["expiration"] == exp_dt
        assert row["mid"] == pytest.approx(3.25)
        # Put strike 440 < underlying 450 → OTM
        assert row["itm"] is False

    def test_after_hours_fallback_to_day_close(self):
        """bid=0 and ask=0 → use day.close as fallback pricing."""
        item = _polygon_option_item(bid=0, ask=0, close=5.0, contract_type="call")
        row = PolygonProvider._build_option_row(
            item, datetime(2026, 4, 10, tzinfo=timezone.utc),
        )
        assert row["bid"] == 5.0
        assert row["ask"] == 5.0
        assert row["mid"] == 5.0


class TestPolygonGet:

    def test_successful_get_includes_api_key(self):
        p = PolygonProvider(api_key="test-key")
        p.session.get = MagicMock(
            return_value=_mock_response({"status": "OK", "results": []}),
        )

        result = p._get("/v2/test")
        assert result["status"] == "OK"
        # apiKey must be in the query params
        _, kwargs = p.session.get.call_args
        assert kwargs["params"]["apiKey"] == "test-key"

    def test_http_error_raises_provider_error(self):
        p = PolygonProvider(api_key="test-key")
        p.session.get = MagicMock(
            return_value=_mock_response({}, status_ok=False),
        )

        with pytest.raises(ProviderError, match="Polygon API request failed"):
            p._get("/v2/test")


class TestPolygonPagination:

    def test_single_page_no_next_url(self):
        p = PolygonProvider(api_key="test-key")
        p._get = MagicMock(return_value={"results": [{"id": 1}, {"id": 2}]})

        results = p._paginate("/v3/test")
        assert len(results) == 2
        p._get.assert_called_once()

    def test_follows_next_url(self):
        p = PolygonProvider(api_key="test-key")
        p._get = MagicMock(return_value={
            "results": [{"id": 1}],
            "next_url": "https://api.polygon.io/v3/test?cursor=abc",
        })
        p._get_next_page = MagicMock(return_value={
            "results": [{"id": 2}],
            # No next_url → stop
        })

        results = p._paginate("/v3/test")
        assert len(results) == 2
        assert results[0]["id"] == 1
        assert results[1]["id"] == 2

    def test_stops_at_max_pages(self):
        """Pagination stops after MAX_PAGES even with more next_url links."""
        p = PolygonProvider(api_key="test-key")
        always_more = {"results": [{"x": 1}], "next_url": "https://next"}
        p._get = MagicMock(return_value=always_more)
        p._get_next_page = MagicMock(return_value=always_more)

        results = p._paginate("/v3/test", caller="test")
        # 1 initial page + MAX_PAGES follow-up pages
        assert len(results) == MAX_PAGES + 1
        assert p._get_next_page.call_count == MAX_PAGES


class TestPolygonGetQuote:

    def test_response_parsing(self):
        p = PolygonProvider(api_key="test-key")
        p.session.get = MagicMock(return_value=_mock_response({
            "ticker": {
                "day": {"o": 500, "h": 510, "l": 495, "c": 505, "v": 1_000_000},
                "lastQuote": {"p": 504.50, "P": 505.00},
                "lastTrade": {"p": 504.75},
                "prevDay": {"c": 500.00},
            },
        }))

        q = p.get_quote("SPY")
        assert q["symbol"] == "SPY"
        assert q["last"] == 504.75
        assert q["bid"] == 504.50
        assert q["ask"] == 505.00
        assert q["volume"] == 1_000_000
        assert q["prevClose"] == 500.00


class TestPolygonGetOptionsChain:

    def test_filters_expiration_and_zero_bid_ask(self):
        p = PolygonProvider(api_key="test-key")
        p._paginate = MagicMock(return_value=[
            _polygon_option_item(strike=440, bid=3.0, ask=3.5, exp_date="2026-04-10"),
            _polygon_option_item(strike=445, bid=2.0, ask=2.5, exp_date="2026-05-15"),  # wrong exp
            _polygon_option_item(strike=460, bid=0, ask=0, close=0, exp_date="2026-04-10"),  # zero pricing
        ])

        df = p.get_options_chain("SPY", "2026-04-10")
        assert len(df) == 1
        assert df.iloc[0]["strike"] == 440

    def test_empty_results_returns_empty_df(self):
        p = PolygonProvider(api_key="test-key")
        p._paginate = MagicMock(return_value=[])

        df = p.get_options_chain("SPY", "2026-04-10")
        assert df.empty


class TestPolygonGetHistorical:

    def test_column_rename(self):
        p = PolygonProvider(api_key="test-key")
        p.session.get = MagicMock(return_value=_mock_response({
            "results": [
                {"o": 500, "h": 510, "l": 495, "c": 505, "v": 1_000_000, "t": 1709769600000},
                {"o": 505, "h": 515, "l": 500, "c": 510, "v": 900_000, "t": 1709856000000},
            ],
        }))

        df = p.get_historical("SPY", days=10)
        assert list(df.columns[:5]) == ["Open", "High", "Low", "Close", "Volume"]
        assert len(df) == 2
        assert df.iloc[0]["Close"] == 505

    def test_empty_results_returns_empty_df(self):
        p = PolygonProvider(api_key="test-key")
        p.session.get = MagicMock(return_value=_mock_response({"results": []}))

        assert p.get_historical("SPY", days=10).empty


class TestPolygonRateLimit:

    def test_sleeps_when_calls_too_fast(self):
        p = PolygonProvider(api_key="test-key")
        with patch("strategy.polygon_provider.time.monotonic") as mock_mono, \
             patch("strategy.polygon_provider.time.sleep") as mock_sleep:
            p._last_call_time = 1.0
            # now=1.05 → only 50ms elapsed, need 150ms more (interval=200ms)
            mock_mono.side_effect = [1.05, 1.25]

            p._rate_limit()

            mock_sleep.assert_called_once()
            assert mock_sleep.call_args[0][0] == pytest.approx(0.15)

    def test_no_sleep_when_enough_elapsed(self):
        p = PolygonProvider(api_key="test-key")
        with patch("strategy.polygon_provider.time.monotonic") as mock_mono, \
             patch("strategy.polygon_provider.time.sleep") as mock_sleep:
            p._last_call_time = 1.0
            mock_mono.side_effect = [1.5, 1.5]  # 500ms elapsed

            p._rate_limit()

            mock_sleep.assert_not_called()


# ===================================================================
# 2. TradierProvider
# ===================================================================

class TestTradierInit:

    def test_empty_api_key_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            TradierProvider(api_key="")

    def test_sandbox_url(self):
        p = TradierProvider(api_key="test-key", sandbox=True)
        assert "sandbox" in p.base_url

    def test_prod_url(self):
        p = TradierProvider(api_key="test-key", sandbox=False)
        assert p.base_url == "https://api.tradier.com/v1"


class TestTradierGetQuote:

    def test_parsing(self):
        p = TradierProvider(api_key="test-key")
        p.session.get = MagicMock(return_value=_mock_response({
            "quotes": {
                "quote": {"symbol": "SPY", "last": 505.0, "bid": 504.90, "ask": 505.10},
            },
        }))

        q = p.get_quote("SPY")
        assert q["symbol"] == "SPY"
        assert q["last"] == 505.0

    def test_http_error_raises_provider_error(self):
        p = TradierProvider(api_key="test-key")
        p.session.get = MagicMock(return_value=_mock_response({}, status_ok=False))

        with pytest.raises(ProviderError, match="Tradier quote"):
            p.get_quote("SPY")


class TestTradierGetExpirations:

    def test_normal_list(self):
        p = TradierProvider(api_key="test-key")
        p.session.get = MagicMock(return_value=_mock_response({
            "expirations": {"date": ["2026-04-10", "2026-05-15", "2026-06-19"]},
        }))

        result = p.get_expirations("SPY")
        assert len(result) == 3

    def test_single_string_wrapped_to_list(self):
        """API sometimes returns a single string instead of a list."""
        p = TradierProvider(api_key="test-key")
        p.session.get = MagicMock(return_value=_mock_response({
            "expirations": {"date": "2026-04-10"},
        }))

        assert p.get_expirations("SPY") == ["2026-04-10"]

    def test_none_returns_empty_list(self):
        p = TradierProvider(api_key="test-key")
        p.session.get = MagicMock(return_value=_mock_response({
            "expirations": None,
        }))

        assert p.get_expirations("SPY") == []


class TestTradierGetOptionsChain:

    def _setup_chain_call(self, provider, options_data, underlying_price=450.0):
        """Configure mock responses for get_quote + get_options_chain."""
        quote_resp = _mock_response(
            {"quotes": {"quote": {"last": underlying_price}}},
        )
        chain_resp = _mock_response({"options": {"option": options_data}})
        provider.session.get = MagicMock(side_effect=[quote_resp, chain_resp])

    def test_parses_options_with_greeks(self):
        p = TradierProvider(api_key="test-key")
        self._setup_chain_call(p, [
            {
                "symbol": "SPY260410P00440000", "strike": 440.0,
                "option_type": "put", "bid": 3.0, "ask": 3.5, "last": 3.2,
                "volume": 100, "open_interest": 500,
                "greeks": {"delta": -0.12, "mid_iv": 0.25, "gamma": 0.01,
                           "theta": -0.05, "vega": 0.15},
            },
        ])

        df = p.get_options_chain("SPY", "2026-04-10")
        assert len(df) == 1
        row = df.iloc[0]
        assert row["strike"] == 440.0
        assert row["type"] == "put"
        assert row["delta"] == -0.12
        assert row["iv"] == 0.25
        assert row["mid"] == pytest.approx(3.25)

    def test_filters_zero_bid_ask(self):
        p = TradierProvider(api_key="test-key")
        self._setup_chain_call(p, [
            {"symbol": "A", "strike": 440.0, "option_type": "put",
             "bid": 3.0, "ask": 3.5, "greeks": {"delta": -0.12}},
            {"symbol": "B", "strike": 460.0, "option_type": "call",
             "bid": 0, "ask": 0, "greeks": {"delta": 0.05}},
        ])

        df = p.get_options_chain("SPY", "2026-04-10")
        assert len(df) == 1
        assert df.iloc[0]["strike"] == 440.0

    def test_single_option_dict_wrapped_to_list(self):
        """API sometimes returns a single dict instead of a list."""
        p = TradierProvider(api_key="test-key")
        self._setup_chain_call(p, {
            "symbol": "SPY260410P00440000", "strike": 440.0,
            "option_type": "put", "bid": 3.0, "ask": 3.5,
            "greeks": {"delta": -0.12, "mid_iv": 0.25},
        })

        df = p.get_options_chain("SPY", "2026-04-10")
        assert len(df) == 1


# ===================================================================
# 3. AlpacaProvider
# ===================================================================

@alpaca_required
class TestAlpacaOCCSymbol:

    def _make_provider(self, MockClient):
        """Create a provider with mocked SDK client."""
        acct = MagicMock()
        acct.account_number = "12345"
        acct.status = "ACTIVE"
        acct.cash = "100000"
        acct.options_trading_level = "2"
        MockClient.return_value.get_account.return_value = acct
        return AlpacaProvider(api_key="key", api_secret="secret")

    @patch("strategy.alpaca_provider.TradingClient")
    def test_put_format(self, MockClient):
        p = self._make_provider(MockClient)
        result = p._build_occ_symbol("SPY", "2026-03-20", 500.0, "put")
        assert result == "SPY260320P00500000"

    @patch("strategy.alpaca_provider.TradingClient")
    def test_call_format(self, MockClient):
        p = self._make_provider(MockClient)
        result = p._build_occ_symbol("AAPL", "2026-06-19", 185.0, "call")
        assert result == "AAPL260619C00185000"

    @patch("strategy.alpaca_provider.TradingClient")
    def test_accepts_datetime_expiration(self, MockClient):
        p = self._make_provider(MockClient)
        exp = datetime(2026, 3, 20, tzinfo=timezone.utc)
        result = p._build_occ_symbol("SPY", exp, 500.0, "put")
        assert result == "SPY260320P00500000"


@alpaca_required
class TestAlpacaRetryDecorator:

    @patch("strategy.alpaca_provider.random.uniform", return_value=0)
    @patch("strategy.alpaca_provider.time.sleep")
    def test_retries_transient_error_then_succeeds(self, mock_sleep, _):
        call_count = 0

        @_retry_with_backoff(max_retries=2, base_delay=0.01)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        assert flaky() == "ok"
        assert call_count == 3
        assert mock_sleep.call_count == 2

    def test_no_retry_on_valueerror(self):
        @_retry_with_backoff(max_retries=2, base_delay=0.01)
        def bad():
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            bad()
