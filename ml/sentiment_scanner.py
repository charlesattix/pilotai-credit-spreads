"""
Sentiment and Event Risk Scanner

Scans for upcoming events that could impact credit spread trades:
- Earnings announcements
- FOMC meetings
- CPI releases
- News sentiment (optional)

Based on research:
- Savor & Wilson (2013): "How Much Do Investors Care About Macroeconomic Risk?"
- Lucca & Moench (2015): "The Pre-FOMC Announcement Drift"
"""

import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging
import yfinance as yf
from shared.constants import FOMC_DATES as _SHARED_FOMC_DATES
from shared.constants import CPI_RELEASE_DAYS as _SHARED_CPI_RELEASE_DAYS

logger = logging.getLogger(__name__)


class SentimentScanner:
    """
    Event risk and sentiment scanner for options trading.
    
    Scans:
    1. Earnings dates (high-risk for credit spreads)
    2. FOMC meetings (market-wide volatility)
    3. CPI releases (inflation data)
    4. Other economic events
    5. Optional: news sentiment
    """

    # Known FOMC meeting dates 2025-2026
    FOMC_DATES = _SHARED_FOMC_DATES

    # CPI release dates (typically 2nd Tuesday-Thursday of month)
    # These are approximate - actual dates vary
    CPI_RELEASE_DAYS = _SHARED_CPI_RELEASE_DAYS

    def __init__(self, data_cache=None):
        """
        Initialize sentiment scanner.

        Args:
            data_cache: Optional DataCache instance for shared data retrieval.
        """
        self.data_cache = data_cache
        self.earnings_cache = {}
        self.cache_timestamps = {}

        logger.info("SentimentScanner initialized")

    def scan(
        self,
        ticker: str,
        expiration_date: Optional[datetime] = None,
        lookahead_days: int = 7
    ) -> Dict:
        """
        Comprehensive event risk scan for a ticker.

        Args:
            ticker: Stock ticker
            expiration_date: Option expiration date
            lookahead_days: Days to look ahead for events

        Returns:
            Dictionary with event risk assessment
        """
        try:
            now = datetime.now()

            # Determine scan window
            if expiration_date:
                scan_end = expiration_date
            else:
                scan_end = now + timedelta(days=lookahead_days)

            result = {
                'ticker': ticker,
                'scan_date': now.isoformat(),
                'scan_window_days': (scan_end - now).days,
                'events': [],
                'event_risk_score': 0.0,
                'highest_risk_event': None,
                'recommendation': 'proceed',
            }

            # 1. Check earnings
            earnings_data = self._check_earnings(ticker, now, scan_end)
            if earnings_data:
                result['events'].append(earnings_data)

            # 2. Check FOMC
            fomc_data = self._check_fomc(now, scan_end)
            if fomc_data:
                result['events'].append(fomc_data)

            # 3. Check CPI
            cpi_data = self._check_cpi(now, scan_end)
            if cpi_data:
                result['events'].append(cpi_data)

            # 4. Calculate overall risk score
            if result['events']:
                risk_scores = [e.get('risk_score', 0) for e in result['events']]
                result['event_risk_score'] = max(risk_scores)
                result['highest_risk_event'] = max(
                    result['events'],
                    key=lambda e: e.get('risk_score', 0)
                )['event_type']

            # 5. Generate recommendation
            result['recommendation'] = self._generate_recommendation(
                result['event_risk_score'],
                result['events']
            )

            logger.info(
                f"{ticker} event scan: "
                f"{len(result['events'])} events, "
                f"risk={result['event_risk_score']:.2f}, "
                f"rec={result['recommendation']}"
            )

            return result

        except Exception as e:
            logger.error(f"Error scanning {ticker}: {e}", exc_info=True)
            return self._get_default_scan()

    def _check_earnings(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[Dict]:
        """
        Check for earnings announcements.
        """
        try:
            # Check cache first
            if ticker in self.earnings_cache:
                cache_age = (datetime.now() - self.cache_timestamps.get(ticker, datetime.min)).total_seconds()
                if cache_age < 86400:  # 24 hours
                    earnings_date = self.earnings_cache[ticker]
                    if earnings_date and start_date <= earnings_date <= end_date:
                        return self._format_earnings_event(earnings_date, ticker)
                    return None

            # Fetch earnings date
            stock = self.data_cache.get_ticker_obj(ticker) if self.data_cache else yf.Ticker(ticker)
            calendar = stock.calendar

            if calendar is None or 'Earnings Date' not in calendar:
                self.earnings_cache[ticker] = None
                self.cache_timestamps[ticker] = datetime.now()
                return None

            earnings_date = pd.to_datetime(calendar['Earnings Date'])

            # Handle Series or single value
            if isinstance(earnings_date, pd.Series):
                if len(earnings_date) > 0:
                    earnings_date = earnings_date.iloc[0]
                else:
                    earnings_date = None

            # Cache result
            self.earnings_cache[ticker] = earnings_date
            self.cache_timestamps[ticker] = datetime.now()

            # Check if in window
            if earnings_date and start_date <= earnings_date <= end_date:
                return self._format_earnings_event(earnings_date, ticker)

            return None

        except Exception as e:
            logger.warning(f"Could not fetch earnings for {ticker}: {e}")
            return None

    def _format_earnings_event(self, earnings_date: datetime, ticker: str) -> Dict:
        """
        Format earnings event data.
        """
        days_until = (earnings_date - datetime.now()).days

        # Risk score based on days until earnings
        if days_until < 0:
            risk_score = 0.0  # Past earnings
        elif days_until <= 2:
            risk_score = 0.95  # Very high risk
        elif days_until <= 5:
            risk_score = 0.80  # High risk
        elif days_until <= 10:
            risk_score = 0.50  # Moderate risk
        else:
            risk_score = 0.20  # Low risk

        return {
            'event_type': 'earnings',
            'ticker': ticker,
            'event_date': earnings_date.isoformat(),
            'days_until': days_until,
            'risk_score': risk_score,
            'description': f"{ticker} earnings on {earnings_date.strftime('%Y-%m-%d')}",
            'impact': 'High volatility expected, credit spreads at risk',
        }

    def _check_fomc(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[Dict]:
        """
        Check for FOMC meetings.
        """
        try:
            # Find next FOMC meeting in window
            upcoming_fomc = [
                date for date in self.FOMC_DATES
                if start_date <= date <= end_date
            ]

            if not upcoming_fomc:
                return None

            fomc_date = min(upcoming_fomc)
            days_until = (fomc_date - datetime.now()).days

            # Risk score
            if days_until < 0:
                risk_score = 0.0
            elif days_until == 0:
                risk_score = 0.90
            elif days_until <= 2:
                risk_score = 0.70
            elif days_until <= 7:
                risk_score = 0.40
            else:
                risk_score = 0.20

            return {
                'event_type': 'fomc',
                'event_date': fomc_date.isoformat(),
                'days_until': days_until,
                'risk_score': risk_score,
                'description': f"FOMC meeting on {fomc_date.strftime('%Y-%m-%d')}",
                'impact': 'Market-wide volatility, all trades affected',
            }

        except Exception as e:
            logger.error(f"Error checking FOMC: {e}", exc_info=True)
            return None

    def _check_cpi(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[Dict]:
        """
        Check for CPI releases (approximate dates).
        """
        try:
            # Look for CPI release days in the window
            cpi_dates = []

            current = start_date
            while current <= end_date:
                if current.day in self.CPI_RELEASE_DAYS:
                    cpi_dates.append(current)
                current += timedelta(days=1)

            if not cpi_dates:
                return None

            cpi_date = min(cpi_dates)
            days_until = (cpi_date - datetime.now()).days

            # Risk score (slightly lower than FOMC)
            if days_until < 0:
                risk_score = 0.0
            elif days_until == 0:
                risk_score = 0.80
            elif days_until <= 2:
                risk_score = 0.60
            elif days_until <= 5:
                risk_score = 0.35
            else:
                risk_score = 0.15

            return {
                'event_type': 'cpi',
                'event_date': cpi_date.isoformat(),
                'days_until': days_until,
                'risk_score': risk_score,
                'description': f"CPI release ~{cpi_date.strftime('%Y-%m-%d')}",
                'impact': 'Inflation data, market volatility likely',
            }

        except Exception as e:
            logger.error(f"Error checking CPI: {e}", exc_info=True)
            return None

    def _generate_recommendation(
        self,
        risk_score: float,
        events: List[Dict]
    ) -> str:
        """
        Generate trading recommendation based on event risk.
        """
        if risk_score >= 0.80:
            return 'avoid'  # Very high risk
        elif risk_score >= 0.60:
            return 'caution'  # High risk, reduce size
        elif risk_score >= 0.40:
            return 'proceed_reduced'  # Moderate risk, smaller position
        else:
            return 'proceed'  # Low risk, normal sizing

    def get_earnings_calendar(
        self,
        tickers: List[str],
        days_ahead: int = 30
    ) -> pd.DataFrame:
        """
        Get earnings calendar for multiple tickers.
        
        Args:
            tickers: List of tickers
            days_ahead: Days to look ahead
            
        Returns:
            DataFrame with earnings dates
        """
        try:
            now = datetime.now()
            end_date = now + timedelta(days=days_ahead)

            earnings_data = []

            for ticker in tickers:
                earnings_event = self._check_earnings(ticker, now, end_date)

                if earnings_event:
                    earnings_data.append({
                        'ticker': ticker,
                        'earnings_date': earnings_event['event_date'],
                        'days_until': earnings_event['days_until'],
                        'risk_score': earnings_event['risk_score'],
                    })

            if not earnings_data:
                return pd.DataFrame()

            df = pd.DataFrame(earnings_data)
            df = df.sort_values('days_until')

            logger.info(f"Found {len(df)} upcoming earnings in next {days_ahead} days")

            return df

        except Exception as e:
            logger.error(f"Error getting earnings calendar: {e}", exc_info=True)
            return pd.DataFrame()

    def get_economic_calendar(self, days_ahead: int = 30) -> List[Dict]:
        """
        Get calendar of major economic events.
        
        Args:
            days_ahead: Days to look ahead
            
        Returns:
            List of economic events
        """
        try:
            now = datetime.now()
            end_date = now + timedelta(days=days_ahead)

            events = []

            # FOMC meetings
            fomc_event = self._check_fomc(now, end_date)
            if fomc_event:
                events.append(fomc_event)

            # CPI releases
            cpi_event = self._check_cpi(now, end_date)
            if cpi_event:
                events.append(cpi_event)

            # Sort by date
            events.sort(key=lambda e: e['event_date'])

            logger.info(f"Found {len(events)} economic events in next {days_ahead} days")

            return events

        except Exception as e:
            logger.error(f"Error getting economic calendar: {e}", exc_info=True)
            return []

    def should_avoid_trade(
        self,
        ticker: str,
        expiration_date: datetime,
        max_risk_score: float = 0.70
    ) -> Tuple[bool, str]:
        """
        Determine if a trade should be avoided due to event risk.
        
        Args:
            ticker: Stock ticker
            expiration_date: Option expiration date
            max_risk_score: Maximum acceptable risk score
            
        Returns:
            Tuple of (should_avoid, reason)
        """
        try:
            scan_result = self.scan(ticker, expiration_date)

            risk_score = scan_result['event_risk_score']

            if risk_score >= max_risk_score:
                events_str = ', '.join([
                    e['event_type'] for e in scan_result['events']
                ])

                reason = f"High event risk ({risk_score:.2f}): {events_str}"
                return True, reason

            return False, "Acceptable event risk"

        except Exception as e:
            logger.error(f"Error checking if should avoid trade: {e}", exc_info=True)
            return False, "Error checking event risk"

    def adjust_position_for_events(
        self,
        base_position_size: float,
        event_risk_score: float
    ) -> float:
        """
        Adjust position size based on event risk.
        
        Args:
            base_position_size: Base position size (0-1)
            event_risk_score: Event risk score (0-1)
            
        Returns:
            Adjusted position size
        """
        try:
            # Reduce position size proportionally to risk
            if event_risk_score >= 0.80:
                multiplier = 0.0  # No position
            elif event_risk_score >= 0.60:
                multiplier = 0.25  # 75% reduction
            elif event_risk_score >= 0.40:
                multiplier = 0.50  # 50% reduction
            elif event_risk_score >= 0.20:
                multiplier = 0.75  # 25% reduction
            else:
                multiplier = 1.0  # No adjustment

            adjusted_size = base_position_size * multiplier

            if multiplier < 1.0:
                logger.info(
                    f"Position size adjusted from {base_position_size:.2%} "
                    f"to {adjusted_size:.2%} due to event risk ({event_risk_score:.2f})"
                )

            return adjusted_size

        except Exception as e:
            logger.error(f"Error adjusting position for events: {e}", exc_info=True)
            return base_position_size

    def _get_default_scan(self) -> Dict:
        """
        Return default scan result when error occurs.
        """
        return {
            'scan_date': datetime.now().isoformat(),
            'scan_window_days': 0,
            'events': [],
            'event_risk_score': 0.5,
            'highest_risk_event': None,
            'recommendation': 'proceed',
            'error': True,
        }

    def get_summary_text(self, scan_result: Dict) -> str:
        """
        Get human-readable summary of scan results.
        
        Args:
            scan_result: Result from scan()
            
        Returns:
            Summary text
        """
        ticker = scan_result.get('ticker', '')
        events = scan_result.get('events', [])
        risk_score = scan_result.get('event_risk_score', 0)
        recommendation = scan_result.get('recommendation', 'proceed')

        if not events:
            return f"{ticker}: No significant events detected. Proceed normally."

        text = f"{ticker} Event Risk Analysis:\n"
        text += f"Overall Risk Score: {risk_score:.2f}\n"
        text += f"Recommendation: {recommendation.upper()}\n\n"
        text += "Upcoming Events:\n"

        for event in events:
            text += f"  - {event['event_type'].upper()}: "
            text += f"{event['description']} "
            text += f"(Risk: {event['risk_score']:.2f})\n"

        return text
