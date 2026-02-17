"""
Credit Spread Strategy Engine
Implements bull put spreads and bear call spreads with high probability setups.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List
import pandas as pd

from shared.types import ScoredSpreadOpportunity, SpreadOpportunity

logger = logging.getLogger(__name__)

# Scoring weights and thresholds for _score_opportunities
SCORING_WEIGHTS = {
    "credit_max": 25,           # Max points for credit component
    "credit_scale": 0.5,        # Scalar: credit_pct * this value
    "risk_reward_max": 25,      # Max points for risk/reward component
    "risk_reward_scale": 8,     # Scalar: risk_reward * this value
    "pop_max": 25,              # Max points for probability-of-profit component
    "pop_baseline": 85,         # POP % that earns full points
    "technical_max": 15,        # Max points for technical alignment component
    "tech_strong_signal": 10,   # Points for strong directional alignment
    "tech_neutral_signal": 5,   # Points for neutral alignment
    "tech_support_resistance": 5,  # Bonus for near support/resistance
    "iv_max": 10,               # Max points for IV component
    "iv_divisor": 10,           # Divisor applied to iv_rank
}


class CreditSpreadStrategy:
    """
    Main strategy class for credit spreads.
    Handles both bull put spreads and bear call spreads.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize strategy with configuration.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.strategy_params = config['strategy']
        self.risk_params = config['risk']
        
        logger.info("CreditSpreadStrategy initialized")
    
    def evaluate_spread_opportunity(
        self,
        ticker: str,
        option_chain: pd.DataFrame,
        technical_signals: Dict,
        iv_data: Dict,
        current_price: float
    ) -> List[Dict]:
        """
        Evaluate potential credit spread opportunities.
        
        Args:
            ticker: Stock ticker symbol
            option_chain: Options chain data
            technical_signals: Technical analysis signals
            iv_data: IV rank and percentile data
            current_price: Current underlying price
            
        Returns:
            List of scored spread opportunities
        """
        opportunities: List[ScoredSpreadOpportunity] = []
        
        # Filter by DTE
        valid_expirations = self._filter_by_dte(option_chain)
        
        for expiration in valid_expirations:
            exp_chain = option_chain[option_chain['expiration'] == expiration]
            
            # Evaluate bull put spreads (bullish/neutral)
            if self._check_bullish_conditions(technical_signals, iv_data):
                bull_puts = self._find_bull_put_spreads(
                    ticker, exp_chain, current_price, expiration
                )
                opportunities.extend(bull_puts)
            
            # Evaluate bear call spreads (bearish/neutral)
            if self._check_bearish_conditions(technical_signals, iv_data):
                bear_calls = self._find_bear_call_spreads(
                    ticker, exp_chain, current_price, expiration
                )
                opportunities.extend(bear_calls)
        
        # Score and rank opportunities
        scored_opportunities = self._score_opportunities(
            opportunities, technical_signals, iv_data
        )
        
        return scored_opportunities
    
    def _filter_by_dte(self, option_chain: pd.DataFrame) -> List[datetime]:
        """Filter expirations by DTE range."""
        today = datetime.now()
        valid_expirations = []
        
        for exp in option_chain['expiration'].unique():
            dte = (exp - today).days
            if self.strategy_params['min_dte'] <= dte <= self.strategy_params['max_dte']:
                valid_expirations.append(exp)
        
        return valid_expirations
    
    def _check_bullish_conditions(
        self,
        technical_signals: Dict,
        iv_data: Dict
    ) -> bool:
        """
        Check if conditions favor bull put spreads.
        
        Args:
            technical_signals: Technical analysis signals
            iv_data: IV rank/percentile data
            
        Returns:
            True if conditions are favorable
        """
        # IV must be elevated
        iv_check = (
            iv_data.get('iv_rank', 0) >= self.strategy_params['min_iv_rank'] or
            iv_data.get('iv_percentile', 0) >= self.strategy_params['min_iv_percentile']
        )
        
        if not iv_check:
            return False
        
        # Technical conditions for bull put spreads
        tech_params = self.strategy_params['technical']
        
        bullish = True
        
        if tech_params['use_trend_filter']:
            # Price above moving averages or uptrend
            bullish = bullish and technical_signals.get('trend', '') in ['bullish', 'neutral']
        
        if tech_params['use_rsi_filter']:
            # RSI not overbought
            rsi = technical_signals.get('rsi', 50)
            bullish = bullish and rsi < tech_params['rsi_overbought']
        
        return bullish
    
    def _check_bearish_conditions(
        self,
        technical_signals: Dict,
        iv_data: Dict
    ) -> bool:
        """Check if conditions favor bear call spreads."""
        # IV must be elevated
        iv_check = (
            iv_data.get('iv_rank', 0) >= self.strategy_params['min_iv_rank'] or
            iv_data.get('iv_percentile', 0) >= self.strategy_params['min_iv_percentile']
        )
        
        if not iv_check:
            return False
        
        tech_params = self.strategy_params['technical']
        
        bearish = True
        
        if tech_params['use_trend_filter']:
            bearish = bearish and technical_signals.get('trend', '') in ['bearish', 'neutral']
        
        if tech_params['use_rsi_filter']:
            rsi = technical_signals.get('rsi', 50)
            bearish = bearish and rsi > tech_params['rsi_oversold']
        
        return bearish
    
    def _find_bull_put_spreads(
        self,
        ticker: str,
        option_chain: pd.DataFrame,
        current_price: float,
        expiration: datetime
    ) -> List[Dict]:
        """Find bull put spread opportunities (thin wrapper)."""
        return self._find_spreads(ticker, option_chain, current_price, expiration, 'bull_put')

    def _find_bear_call_spreads(
        self,
        ticker: str,
        option_chain: pd.DataFrame,
        current_price: float,
        expiration: datetime
    ) -> List[Dict]:
        """Find bear call spread opportunities (thin wrapper)."""
        return self._find_spreads(ticker, option_chain, current_price, expiration, 'bear_call')

    def _find_spreads(
        self,
        ticker: str,
        option_chain: pd.DataFrame,
        current_price: float,
        expiration: datetime,
        spread_type: str,
    ) -> List[SpreadOpportunity]:
        """
        Find credit spread opportunities.

        Args:
            ticker: Stock ticker symbol
            option_chain: Options chain data
            current_price: Current underlying price
            expiration: Option expiration date
            spread_type: 'bull_put' or 'bear_call'

        Returns:
            List of spread opportunity dicts
        """
        spreads: List[SpreadOpportunity] = []

        if spread_type == 'bull_put':
            option_type = 'put'
            spread_label = 'bull_put_spread'
        else:
            option_type = 'call'
            spread_label = 'bear_call_spread'

        # Filter by option type
        legs = option_chain[option_chain['type'] == option_type].copy()

        if legs.empty:
            return spreads

        target_delta_min = self.strategy_params['min_delta']
        target_delta_max = self.strategy_params['max_delta']

        # Delta filtering differs by spread type
        if spread_type == 'bull_put':
            # For puts, delta is negative
            short_candidates = legs[
                (legs['delta'] >= -target_delta_max) &
                (legs['delta'] <= -target_delta_min)
            ]
        else:
            # For calls, delta is positive
            short_candidates = legs[
                (legs['delta'] >= target_delta_min) &
                (legs['delta'] <= target_delta_max)
            ]

        spread_width = self.strategy_params['spread_width']

        for _, short_leg in short_candidates.iterrows():
            short_strike = short_leg['strike']

            # Long strike direction differs
            if spread_type == 'bull_put':
                long_strike = short_strike - spread_width
            else:
                long_strike = short_strike + spread_width

            # Find corresponding long leg
            long_leg = legs[legs['strike'] == long_strike]

            if long_leg.empty:
                continue

            long_leg = long_leg.iloc[0]

            # Calculate credit and risk
            credit = short_leg['bid'] - long_leg['ask']
            max_loss = spread_width - credit

            # Check minimum credit requirement
            min_credit = spread_width * (self.risk_params['min_credit_pct'] / 100)
            if credit < min_credit:
                continue

            dte = (expiration - datetime.now()).days

            # Distance to short strike direction differs
            if spread_type == 'bull_put':
                distance_to_short = short_strike - current_price
            else:
                distance_to_short = current_price - short_strike

            spread = {
                'ticker': ticker,
                'type': spread_label,
                'expiration': expiration,
                'dte': dte,
                'short_strike': short_strike,
                'long_strike': long_strike,
                'short_delta': abs(short_leg['delta']),
                'credit': round(credit, 2),
                'max_loss': round(max_loss, 2),
                'max_profit': round(credit, 2),
                'profit_target': round(credit * 0.5, 2),
                'stop_loss': round(credit * self.risk_params['stop_loss_multiplier'], 2),
                'spread_width': spread_width,
                'current_price': current_price,
                'distance_to_short': distance_to_short,
                'pop': self._calculate_pop(short_leg['delta']),
                'risk_reward': round(credit / max_loss, 2) if max_loss > 0 else 0,
            }

            spreads.append(spread)

        return spreads
    
    def _calculate_pop(self, delta: float) -> float:
        """
        Calculate probability of profit (approximation).
        POP ≈ 1 - |delta|
        """
        return round((1 - abs(delta)) * 100, 2)
    
    def _score_opportunities(
        self,
        opportunities: List[Dict],
        technical_signals: Dict,
        iv_data: Dict
    ) -> List[Dict]:
        """
        Score and rank spread opportunities.
        
        Scoring criteria:
        - Higher credit (better)
        - Better risk/reward ratio
        - Higher probability of profit
        - Technical alignment
        - IV rank/percentile
        """
        w = SCORING_WEIGHTS

        for opp in opportunities:
            score = 0

            # Credit score (0-credit_max points)
            # Higher credit as % of spread width is better
            credit_pct = (opp['credit'] / opp['spread_width']) * 100
            score += min(credit_pct * w["credit_scale"], w["credit_max"])

            # Risk/reward score (0-risk_reward_max points)
            # Better than 1:3 risk/reward gets full points
            rr_score = min(opp['risk_reward'] * w["risk_reward_scale"], w["risk_reward_max"])
            score += rr_score

            # POP score (0-pop_max points)
            # POP > pop_baseline% gets full points
            pop_score = min((opp['pop'] / w["pop_baseline"]) * w["pop_max"], w["pop_max"])
            score += pop_score

            # Technical alignment (0-technical_max points)
            tech_score = 0
            if opp['type'] == 'bull_put_spread':
                if technical_signals.get('trend') == 'bullish':
                    tech_score += w["tech_strong_signal"]
                elif technical_signals.get('trend') == 'neutral':
                    tech_score += w["tech_neutral_signal"]
            else:  # bear_call_spread
                if technical_signals.get('trend') == 'bearish':
                    tech_score += w["tech_strong_signal"]
                elif technical_signals.get('trend') == 'neutral':
                    tech_score += w["tech_neutral_signal"]

            # Support/resistance alignment
            if technical_signals.get('near_support') and opp['type'] == 'bull_put_spread':
                tech_score += w["tech_support_resistance"]
            if technical_signals.get('near_resistance') and opp['type'] == 'bear_call_spread':
                tech_score += w["tech_support_resistance"]

            score += min(tech_score, w["technical_max"])

            # IV score (0-iv_max points)
            iv_rank = iv_data.get('iv_rank', 0)
            iv_score = min(iv_rank / w["iv_divisor"], w["iv_max"])
            score += iv_score

            opp['score'] = round(score, 2)
        
        # Sort by score (highest first)
        opportunities.sort(key=lambda x: x['score'], reverse=True)
        
        return opportunities
    
