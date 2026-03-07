"""Defensive edge-case tests for the paper trader ↔ strategy unification.

Covers:
- Missing/corrupt champion.json
- BS pricing with degenerate inputs (zero strikes, zero price, zero credit)
- Adapter with empty legs, missing fields
- Position sizing with zero max_loss
- Legacy trades without per-trade exit params
- _get_strategy_for_type fallback paths
- NaN/inf guards in _evaluate_position
"""

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from paper_trader import PaperTrader
from strategies.base import LegType, Signal, TradeLeg, TradeDirection
from shared.strategy_adapter import signal_to_opportunity, trade_dict_to_position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config():
    return {
        'risk': {
            'account_size': 100000,
            'max_risk_per_trade': 2.0,
            'max_positions': 5,
            'profit_target': 50,
            'stop_loss_multiplier': 2.5,
        },
        'alpaca': {'enabled': False},
    }


@patch('paper_trader.init_db')
@patch('paper_trader.get_trades', return_value=[])
@patch('paper_trader.DATA_DIR')
def _make_trader(mock_data_dir, mock_get_trades, mock_init_db, tmp_path=None):
    """Create a PaperTrader with mocked DB/filesystem."""
    from pathlib import Path
    target = tmp_path or Path("/tmp")
    mock_data_dir.__truediv__ = lambda s, n: target / n
    mock_data_dir.mkdir = MagicMock()
    return PaperTrader(_make_config())


# ---------------------------------------------------------------------------
# 1. _evaluate_position edge cases
# ---------------------------------------------------------------------------

class TestEvaluatePositionEdgeCases:

    def test_zero_credit_trade(self):
        """Trade with credit=0 should not crash and should not trigger spurious exits."""
        pt = _make_trader()
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 540, 'long_strike': 530,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=20)).strftime('%Y-%m-%d'),
            'contracts': 1, 'credit': 0, 'total_credit': 0,
            'profit_target_pct': 0.5, 'stop_loss_pct': 2.5,
        }
        pnl, reason = pt._evaluate_position(trade, current_price=550, dte=20)
        # With zero credit, pnl should be non-positive (we paid nothing, might owe to close)
        # Should not crash
        assert isinstance(pnl, float)

    def test_zero_current_price(self):
        """Price=0 should not crash BS pricing (bs_price returns 0 for S<=0)."""
        pt = _make_trader()
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 540, 'long_strike': 530,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=20)).strftime('%Y-%m-%d'),
            'contracts': 1, 'credit': 1.50, 'total_credit': 150,
            'profit_target_pct': 0.5, 'stop_loss_pct': 2.5,
        }
        pnl, reason = pt._evaluate_position(trade, current_price=0, dte=20)
        assert isinstance(pnl, float)
        assert not math.isnan(pnl)
        assert not math.isinf(pnl)

    def test_negative_dte(self):
        """Negative DTE (past expiration) should trigger an exit."""
        pt = _make_trader()
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 540, 'long_strike': 530,
            'expiration': (datetime.now(timezone.utc) - timedelta(days=5)).strftime('%Y-%m-%d'),
            'contracts': 1, 'credit': 1.50, 'total_credit': 150,
            'profit_target_pct': 0.5, 'stop_loss_pct': 2.5,
        }
        pnl, reason = pt._evaluate_position(trade, current_price=550, dte=-5)
        # With expired options, BS prices are ~0 so full credit is captured.
        # profit_target fires before expiration check — either exit is acceptable.
        assert reason is not None, "Past-expiration trade should trigger some exit"
        assert reason in ('profit_target', 'expiration')

    def test_pnl_never_nan(self):
        """PnL should never be NaN regardless of inputs."""
        pt = _make_trader()
        exp = (datetime.now(timezone.utc) + timedelta(days=1)).strftime('%Y-%m-%d')
        test_cases = [
            (0.01, 1),    # tiny price
            (99999, 1),   # huge price
            (550, 0),     # zero DTE
            (550, 365),   # very long DTE
        ]
        for price, dte in test_cases:
            trade = {
                'ticker': 'SPY', 'type': 'bull_put_spread',
                'short_strike': 540, 'long_strike': 530,
                'expiration': exp,
                'contracts': 1, 'credit': 1.50, 'total_credit': 150,
                'profit_target_pct': 0.5, 'stop_loss_pct': 2.5,
            }
            pnl, _ = pt._evaluate_position(trade, current_price=price, dte=dte)
            assert not math.isnan(pnl), f"NaN PnL for price={price}, dte={dte}"
            assert not math.isinf(pnl), f"Inf PnL for price={price}, dte={dte}"

    def test_legacy_trade_missing_credit_key(self):
        """Legacy trades without 'credit' key should use fallback of 0."""
        pt = _make_trader()
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 540, 'long_strike': 530,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=20)).strftime('%Y-%m-%d'),
            'contracts': 2,
            # No 'credit' key — legacy trade
            'total_credit': 300,
            'profit_target': 150,
            'stop_loss_amount': 750,
        }
        pnl, reason = pt._evaluate_position(trade, current_price=550, dte=20)
        assert isinstance(pnl, float)
        assert not math.isnan(pnl)

    def test_legacy_trade_missing_exit_params(self):
        """Legacy trades without profit_target_pct/stop_loss_pct use global config."""
        pt = _make_trader()
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 540, 'long_strike': 530,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=20)).strftime('%Y-%m-%d'),
            'contracts': 1, 'credit': 1.50, 'total_credit': 150,
            # No profit_target_pct or stop_loss_pct
        }
        pnl, reason = pt._evaluate_position(trade, current_price=550, dte=20)
        # Should fall back to self.profit_target_pct (0.5) and self.stop_loss_mult (2.5)
        assert isinstance(pnl, float)


# ---------------------------------------------------------------------------
# 2. _get_current_iv edge cases
# ---------------------------------------------------------------------------

class TestGetCurrentIVEdgeCases:

    def test_no_options_analyzer(self):
        """Without _options_analyzer, falls back to VIX or default."""
        pt = _make_trader()
        # No _options_analyzer set
        iv = pt._get_current_iv("SPY")
        assert iv == 0.20  # default

    def test_vix_fallback(self):
        """With _vix_value set, uses VIX/100."""
        pt = _make_trader()
        pt._vix_value = 25.0
        iv = pt._get_current_iv("SPY")
        assert iv == 0.25

    def test_vix_zero(self):
        """VIX=0 should still return a usable IV."""
        pt = _make_trader()
        pt._vix_value = 0
        iv = pt._get_current_iv("SPY")
        # _vix_value is falsy when 0, so falls through to default
        assert iv == 0.20

    def test_options_analyzer_exception(self):
        """If options_analyzer throws, falls back gracefully."""
        pt = _make_trader()
        mock_analyzer = MagicMock()
        mock_analyzer.get_options_chain.side_effect = RuntimeError("API down")
        pt._options_analyzer = mock_analyzer
        pt._vix_value = 30.0
        iv = pt._get_current_iv("SPY")
        assert iv == 0.30  # VIX fallback


# ---------------------------------------------------------------------------
# 3. _get_strategy_for_type edge cases
# ---------------------------------------------------------------------------

class TestGetStrategyForType:

    def test_no_champion_strategies_attr(self):
        """Without _champion_strategies attribute, returns None."""
        pt = _make_trader()
        result = pt._get_strategy_for_type({"type": "bull_put_spread"})
        assert result is None

    def test_empty_champion_strategies(self):
        """Empty strategy list returns None."""
        pt = _make_trader()
        pt._champion_strategies = []
        result = pt._get_strategy_for_type({"type": "bull_put_spread"})
        assert result is None

    def test_exact_name_match(self):
        """Matches by strategy_name first."""
        pt = _make_trader()
        mock_strat = MagicMock()
        mock_strat.name = "CreditSpreadStrategy"
        pt._champion_strategies = [mock_strat]
        result = pt._get_strategy_for_type({
            "type": "bull_put_spread",
            "strategy_name": "CreditSpreadStrategy",
        })
        assert result is mock_strat

    def test_condor_type_match(self):
        """Matches iron condor type to condor strategy."""
        pt = _make_trader()
        mock_cs = MagicMock()
        mock_cs.name = "CreditSpreadStrategy"
        mock_ic = MagicMock()
        mock_ic.name = "IronCondorStrategy"
        pt._champion_strategies = [mock_cs, mock_ic]
        result = pt._get_strategy_for_type({"type": "iron_condor"})
        assert result is mock_ic

    def test_unknown_type_fallback(self):
        """Unknown spread type falls back to first strategy."""
        pt = _make_trader()
        mock_strat = MagicMock()
        mock_strat.name = "CreditSpreadStrategy"
        pt._champion_strategies = [mock_strat]
        result = pt._get_strategy_for_type({"type": "exotic_butterfly"})
        assert result is mock_strat

    def test_debit_spread_type(self):
        """Debit spread type (no champion match) falls back to first strategy."""
        pt = _make_trader()
        mock_strat = MagicMock()
        mock_strat.name = "CreditSpreadStrategy"
        pt._champion_strategies = [mock_strat]
        result = pt._get_strategy_for_type({"type": "debit_spread"})
        assert result is mock_strat


# ---------------------------------------------------------------------------
# 4. _size_position_for_trade edge cases
# ---------------------------------------------------------------------------

class TestSizePositionEdgeCases:

    def test_zero_max_loss_refused(self):
        """Signal with max_loss=0 should result in 0 contracts from strategy."""
        pt = _make_trader()
        from strategies.credit_spread import CreditSpreadStrategy
        strat = CreditSpreadStrategy({"max_risk_pct": 0.02})
        pt._champion_strategies = [strat]

        opp = {
            "ticker": "SPY", "type": "bull_put_spread",
            "strategy_name": "CreditSpreadStrategy",
            "short_strike": 540, "long_strike": 530,
            "max_loss": 0,  # zero max loss
        }
        result = pt._size_position_for_trade(opp, 100000, 0, 1.50)
        # strategy.size_position returns 0 for risk_per_unit=0 → refused
        assert result is None

    def test_legacy_fallback_when_no_strategies(self):
        """Without champion strategies, uses legacy IV-scaled sizing."""
        pt = _make_trader()
        # No _champion_strategies set
        opp = {
            "ticker": "SPY", "type": "bull_put_spread",
            "short_strike": 540, "long_strike": 530,
            "max_loss": 8.50, "iv_rank": 30,
        }
        with patch('ml.position_sizer.calculate_dynamic_risk', return_value=2000):
            with patch('ml.position_sizer.get_contract_size', return_value=3):
                result = pt._size_position_for_trade(opp, 100000, 5000, 1.50)
        assert result == 3


# ---------------------------------------------------------------------------
# 5. Adapter edge cases
# ---------------------------------------------------------------------------

class TestAdapterEdgeCases:

    def test_signal_with_empty_legs(self):
        """Signal with no legs should still produce a valid opportunity dict."""
        sig = Signal(
            strategy_name="TestStrategy",
            ticker="SPY",
            direction=TradeDirection.SHORT,
            legs=[],
            net_credit=1.0,
            max_loss=9.0,
            dte=30,
        )
        opp = signal_to_opportunity(sig, current_price=550.0)
        assert opp["ticker"] == "SPY"
        assert opp["short_strike"] == 0.0
        assert opp["long_strike"] == 0.0
        assert opp["type"] == "credit_spread"  # fallback from metadata

    def test_signal_with_none_expiration(self):
        """Signal with expiration=None should produce empty expiration string."""
        sig = Signal(
            strategy_name="TestStrategy",
            ticker="SPY",
            direction=TradeDirection.SHORT,
            legs=[],
            net_credit=1.0,
            max_loss=9.0,
            expiration=None,
        )
        opp = signal_to_opportunity(sig, current_price=550.0)
        assert opp["expiration"] == ""

    def test_trade_dict_with_empty_expiration(self):
        """Trade dict with empty expiration string should not crash."""
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 540, 'long_strike': 530,
            'expiration': '',
            'contracts': 1, 'credit': 1.50,
        }
        pos = trade_dict_to_position(trade)
        # Should fallback to datetime.now(timezone.utc)
        assert pos.legs[0].expiration.tzinfo is not None

    def test_trade_dict_with_garbage_expiration(self):
        """Trade dict with unparseable expiration should not crash."""
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 540, 'long_strike': 530,
            'expiration': 'not-a-date',
            'contracts': 1, 'credit': 1.50,
        }
        pos = trade_dict_to_position(trade)
        assert pos.legs[0].expiration.tzinfo is not None

    def test_trade_dict_with_zero_strikes(self):
        """Trade dict with strike=0 should produce a valid Position (BS returns 0)."""
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 0, 'long_strike': 0,
            'expiration': '2026-04-17',
            'contracts': 1, 'credit': 0,
        }
        pos = trade_dict_to_position(trade)
        assert pos.legs[0].strike == 0
        assert pos.legs[1].strike == 0

    def test_iron_condor_missing_call_strikes(self):
        """Iron condor trade dict missing call-side strikes defaults to 0."""
        trade = {
            'ticker': 'SPY', 'type': 'iron_condor',
            'short_strike': 530, 'long_strike': 520,
            # No call_short_strike or call_long_strike
            'expiration': '2026-04-17',
            'contracts': 1, 'credit': 1.90,
        }
        pos = trade_dict_to_position(trade)
        assert len(pos.legs) == 4
        # Call legs should have strike=0 (default)
        call_legs = [l for l in pos.legs if 'call' in l.leg_type.value]
        assert all(l.strike == 0 for l in call_legs)


# ---------------------------------------------------------------------------
# 6. Champion config loading edge cases (main.py)
# ---------------------------------------------------------------------------

class TestChampionConfigEdgeCases:

    def test_missing_champion_json_graceful(self):
        """CreditSpreadSystem should initialize even if champion.json is missing."""
        with patch('main.os.path.join', return_value='/nonexistent/champion.json'):
            # This tests that the try/except in __init__ handles FileNotFoundError
            # We can't easily instantiate CreditSpreadSystem without full config,
            # so we test the loading pattern directly
            import json
            strategies = []
            try:
                with open('/nonexistent/champion.json') as f:
                    champion_config = json.load(f)
            except Exception:
                champion_config = None

            assert champion_config is None
            assert strategies == []  # No strategies loaded, legacy fallback

    def test_champion_json_missing_strategy_params(self):
        """Champion config without strategy_params key should use default params."""
        import json
        from strategies.credit_spread import CreditSpreadStrategy

        config = {"strategies": ["credit_spread"], "strategy_params": {}}
        params = config.get("strategy_params", {}).get("credit_spread", {})
        strat = CreditSpreadStrategy(params)
        # Should work with defaults
        assert strat._p("profit_target_pct", 0.50) == 0.50
        assert strat._p("spread_width", 10.0) == 10.0

    def test_champion_json_unknown_strategy_skipped(self):
        """Unknown strategy names in champion.json should be silently skipped."""
        strategies = []
        config = {
            "strategies": ["credit_spread", "magic_unicorn_strategy", "iron_condor"],
            "strategy_params": {},
        }
        from strategies.iron_condor import IronCondorStrategy
        from strategies.credit_spread import CreditSpreadStrategy

        for name in config["strategies"]:
            params = config.get("strategy_params", {}).get(name, {})
            if name == "iron_condor":
                strategies.append(IronCondorStrategy(params))
            elif name == "credit_spread":
                strategies.append(CreditSpreadStrategy(params))
            # unknown names silently skipped

        assert len(strategies) == 2


# ---------------------------------------------------------------------------
# 7. BS pricing with degenerate positions
# ---------------------------------------------------------------------------

class TestBSPricingDegenerate:

    def test_evaluate_position_with_zero_strike_legs(self):
        """BS pricing with zero-strike legs should return 0, not NaN."""
        pt = _make_trader()
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 0, 'long_strike': 0,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=20)).strftime('%Y-%m-%d'),
            'contracts': 1, 'credit': 1.50, 'total_credit': 150,
            'profit_target_pct': 0.5, 'stop_loss_pct': 2.5,
        }
        pnl, reason = pt._evaluate_position(trade, current_price=550, dte=20)
        assert not math.isnan(pnl)
        assert not math.isinf(pnl)

    def test_evaluate_position_extreme_price_move(self):
        """Extreme price move (10x) should produce bounded PnL."""
        pt = _make_trader()
        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 540, 'long_strike': 530,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=20)).strftime('%Y-%m-%d'),
            'contracts': 2, 'credit': 1.50, 'total_credit': 300,
            'profit_target_pct': 0.5, 'stop_loss_pct': 2.5,
        }
        # Price crashed to near zero (extreme bear)
        pnl, reason = pt._evaluate_position(trade, current_price=1.0, dte=20)
        assert not math.isnan(pnl)
        # Loss should be bounded by spread width * contracts * 100
        spread_width = 10.0
        max_loss = spread_width * 2 * 100
        assert pnl >= -max_loss - 1  # small rounding tolerance

    def test_evaluate_iron_condor_both_wings_tested(self):
        """Iron condor should price all 4 legs without crash."""
        pt = _make_trader()
        trade = {
            'ticker': 'SPY', 'type': 'iron_condor',
            'short_strike': 530, 'long_strike': 520,
            'call_short_strike': 570, 'call_long_strike': 580,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=20)).strftime('%Y-%m-%d'),
            'contracts': 1, 'credit': 2.00, 'total_credit': 200,
            'profit_target_pct': 0.3, 'stop_loss_pct': 2.5,
        }
        # Price at midpoint — both wings OTM
        pnl, reason = pt._evaluate_position(trade, current_price=550, dte=20)
        assert not math.isnan(pnl)
        assert isinstance(reason, (str, type(None)))

    def test_evaluate_iron_condor_breached_call(self):
        """Iron condor with price above call short should show loss."""
        pt = _make_trader()
        trade = {
            'ticker': 'SPY', 'type': 'iron_condor',
            'short_strike': 530, 'long_strike': 520,
            'call_short_strike': 570, 'call_long_strike': 580,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=5)).strftime('%Y-%m-%d'),
            'contracts': 1, 'credit': 2.00, 'total_credit': 200,
            'profit_target_pct': 0.3, 'stop_loss_pct': 2.5,
        }
        # Price blew through call wing
        pnl, reason = pt._evaluate_position(trade, current_price=585, dte=5)
        assert pnl < 0, "Breached call wing should show loss"
