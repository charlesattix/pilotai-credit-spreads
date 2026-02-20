#!/usr/bin/env python3
"""
Credit Spread Trading System
Main entry point for the trading system.

Usage:
    python main.py scan          # Scan for new opportunities
    python main.py scheduler     # Run scans on market-hours schedule (14x/day)
    python main.py backtest      # Run backtest
    python main.py dashboard     # Display P&L dashboard
    python main.py alerts        # Generate alerts only
"""

import os
import sys
import signal
import logging
from datetime import datetime, timedelta, timezone
import argparse
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from shared.types import AppConfig

try:
    import sentry_sdk
    sentry_dsn = os.environ.get('SENTRY_DSN')
    if sentry_dsn:
        sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.1)
except ImportError:
    pass
except Exception as e:
    logging.getLogger(__name__).error(f"Sentry initialization failed: {e}", exc_info=True)

from utils import load_config, setup_logging, validate_config
from strategy import CreditSpreadStrategy, TechnicalAnalyzer, OptionsAnalyzer
from alerts import AlertGenerator, TelegramBot
from backtest import Backtester, HistoricalOptionsData, PerformanceMetrics
from tracker import TradeTracker, PnLDashboard
from paper_trader import PaperTrader
from shared.data_cache import DataCache
from shared.metrics import metrics
from shared.provider_protocol import DataProvider  # noqa: F401 – ARCH-PY-06


logger = logging.getLogger(__name__)

# Defaults for ML/rules blending and event risk — overridable via config.yaml
_DEFAULT_ML_SCORE_WEIGHT = 0.6
_DEFAULT_EVENT_RISK_THRESHOLD = 0.7


class CreditSpreadSystem:
    """
    Main credit spread trading system.
    """

    def __init__(
        self,
        config: AppConfig,
        strategy: Optional[CreditSpreadStrategy] = None,
        technical_analyzer: Optional[TechnicalAnalyzer] = None,
        options_analyzer: Optional[OptionsAnalyzer] = None,
        alert_generator: Optional[AlertGenerator] = None,
        telegram_bot: Optional[TelegramBot] = None,
        tracker: Optional[TradeTracker] = None,
        paper_trader: Optional[PaperTrader] = None,
        data_cache: Optional[DataCache] = None,
        ml_pipeline=None,
    ):
        """
        Initialize the trading system.

        Args:
            config: Configuration dictionary (already loaded & validated).
            strategy: Pre-built CreditSpreadStrategy or None for default.
            technical_analyzer: Pre-built TechnicalAnalyzer or None for default.
            options_analyzer: Pre-built OptionsAnalyzer or None for default.
            alert_generator: Pre-built AlertGenerator or None for default.
            telegram_bot: Pre-built TelegramBot or None for default.
            tracker: Pre-built TradeTracker or None for default.
            paper_trader: Pre-built PaperTrader or None for default.
            data_cache: Pre-built DataCache or None for default.
            ml_pipeline: Pre-built ML pipeline or None for default.
        """
        self.config = config

        logger.info("=" * 80)
        logger.info("Credit Spread Trading System Starting")
        logger.info("=" * 80)

        # Initialize components — use injected instances when provided
        self.data_cache = data_cache or DataCache()
        self.strategy = strategy or CreditSpreadStrategy(self.config)
        self.technical_analyzer = technical_analyzer or TechnicalAnalyzer(self.config)
        self.options_analyzer = options_analyzer or OptionsAnalyzer(self.config, data_cache=self.data_cache)
        self.alert_generator = alert_generator or AlertGenerator(self.config)
        self.telegram_bot = telegram_bot or TelegramBot(self.config)
        self.tracker = tracker or TradeTracker(self.config)
        self.dashboard = PnLDashboard(self.config, self.tracker)
        self.paper_trader = paper_trader or PaperTrader(self.config)

        # ML pipeline: use injected instance, or try to build one
        if ml_pipeline is not None:
            self.ml_pipeline = ml_pipeline
        else:
            self.ml_pipeline = None
            try:
                from ml.ml_pipeline import MLPipeline
                self.ml_pipeline = MLPipeline(self.config, data_cache=self.data_cache)
                self.ml_pipeline.initialize()
                logger.info("ML pipeline initialized successfully")
            except Exception as e:
                logger.warning(f"ML pipeline not available, using rules-based scoring: {e}")

        # ML/rules blending weights (configurable via config.yaml strategy section)
        strategy_cfg = self.config.get('strategy', {})
        self.ml_score_weight = strategy_cfg.get('ml_score_weight', _DEFAULT_ML_SCORE_WEIGHT)
        self.rules_score_weight = 1.0 - self.ml_score_weight
        self.event_risk_threshold = strategy_cfg.get('event_risk_threshold', _DEFAULT_EVENT_RISK_THRESHOLD)

        logger.info("All components initialized successfully")

    def scan_opportunities(self):
        """
        Scan for credit spread opportunities across all tickers.
        """
        logger.info("Starting opportunity scan")

        all_opportunities = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._analyze_ticker, ticker): ticker
                for ticker in self.config['tickers']
            }
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    opportunities = future.result()
                    all_opportunities.extend(opportunities)
                except Exception as e:
                    logger.error(f"Error analyzing {ticker}: {e}", exc_info=True)

        if not all_opportunities:
            logger.info("No opportunities found")
            return []

        # Sort by score
        all_opportunities.sort(key=lambda x: x.get('score', 0), reverse=True)

        metrics.inc('scans_completed')

        # Display top opportunities
        logger.info(f"Found {len(all_opportunities)} total opportunities")
        logger.info("Top 5 opportunities:")

        for i, opp in enumerate(all_opportunities[:5], 1):
            logger.info(f"{i}. {opp['ticker']} {opp['type']} - Score: {opp['score']:.1f}")

        # Generate alerts
        self._generate_alerts(all_opportunities)

        # Auto paper trade the best signals
        new_trades = self.paper_trader.execute_signals(all_opportunities)
        if new_trades:
            logger.info(f"Paper traded {len(new_trades)} new positions")

        # Check existing positions
        current_prices = {}
        for ticker in self.config['tickers']:
            try:
                hist = self.data_cache.get_history(ticker, period='1y')
                if not hist.empty:
                    current_prices[ticker] = float(hist['Close'].iloc[-1])
            except Exception as e:
                logger.warning(f"Failed to fetch price for {ticker}: {e}")

        if current_prices:
            closed = self.paper_trader.check_positions(current_prices)
            if closed:
                logger.info(f"Closed {len(closed)} paper positions")

        self.paper_trader.print_summary()

        return all_opportunities

    def _analyze_ticker(self, ticker: str) -> list:
        """
        Analyze a single ticker for opportunities.

        Args:
            ticker: Stock ticker symbol

        Returns:
            List of opportunities
        """
        try:
            # Get price data
            price_data = self.data_cache.get_history(ticker, period='1y')

            if price_data.empty:
                logger.warning(f"No price data for {ticker}")
                return []

            current_price = float(price_data['Close'].iloc[-1])

            # Get options chain
            options_chain = self.options_analyzer.get_options_chain(ticker)

            if options_chain.empty:
                logger.warning(f"No options data for {ticker}")
                return []

            # Technical analysis
            technical_signals = self.technical_analyzer.analyze(ticker, price_data)

            # IV analysis
            current_iv = self.options_analyzer.get_current_iv(options_chain)
            iv_data = self.options_analyzer.calculate_iv_rank(ticker, current_iv)

            logger.info(f"{ticker}: Price=${current_price:.2f}, IV Rank={iv_data.get('iv_rank', 0):.1f}%")

            # Evaluate spread opportunities
            opportunities = self.strategy.evaluate_spread_opportunity(
                ticker=ticker,
                option_chain=options_chain,
                technical_signals=technical_signals,
                iv_data=iv_data,
                current_price=current_price
            )

            # Enhance with ML scoring if available
            if self.ml_pipeline and opportunities:
                try:
                    for opp in opportunities:
                        spread_type = 'bull_put' if 'put' in opp.get('type', '') else 'bear_call'
                        ml_result = self.ml_pipeline.analyze_trade(
                            ticker=ticker,
                            current_price=current_price,
                            options_chain=options_chain,
                            spread_type=spread_type,
                            technical_signals=technical_signals,
                        )
                        # Blend ML score with rules-based score (60% ML, 40% rules)
                        rules_score = opp.get('score', 50)
                        ml_score = ml_result.get('enhanced_score', rules_score)
                        opp['rules_score'] = rules_score
                        opp['ml_score'] = ml_score
                        opp['score'] = self.ml_score_weight * ml_score + self.rules_score_weight * rules_score
                        opp['regime'] = ml_result.get('regime', {}).get('regime', 'unknown')
                        opp['regime_confidence'] = ml_result.get('regime', {}).get('confidence', 0)
                        opp['event_risk'] = ml_result.get('event_risk', {}).get('event_risk_score', 0)
                        opp['ml_position_size'] = ml_result.get('position_sizing', {})

                        # Skip if high event risk
                        if opp['event_risk'] > self.event_risk_threshold:
                            logger.warning(f"Skipping {ticker} {opp['type']} due to high event risk: {opp['event_risk']:.2f}")
                            opp['score'] = 0  # Zero out to filter

                except Exception as e:
                    logger.warning(f"ML scoring failed for {ticker}, using rules-based: {e}")

            return opportunities

        except Exception as e:
            logger.error(f"Error analyzing {ticker}: {e}", exc_info=True)
            return []

    def _generate_alerts(self, opportunities: list):
        """
        Generate and send alerts.

        Args:
            opportunities: List of opportunities
        """
        logger.info("Generating alerts...")

        # Generate alert outputs
        outputs = self.alert_generator.generate_alerts(opportunities)

        for output_type, output_path in outputs.items():
            logger.info(f"{output_type.upper()} alerts: {output_path}")

        # Send Telegram alerts if enabled
        if self.telegram_bot.enabled:
            top_opportunities = [
                opp for opp in opportunities
                if opp.get('score', 0) >= 60
            ][:5]

            sent = self.telegram_bot.send_alerts(top_opportunities, self.alert_generator)
            logger.info(f"Sent {sent} Telegram alerts")

    def run_backtest(self, ticker: str = 'SPY', lookback_days: int = 365, clear_cache: bool = False):
        """
        Run backtest on historical data.

        Args:
            ticker: Ticker to backtest
            lookback_days: Days of history to test
            clear_cache: If True, clear the options price cache before running
        """
        logger.info(f"Starting backtest for {ticker}")

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=lookback_days)

        # Build HistoricalOptionsData if Polygon API key is available
        historical_data = None
        polygon_key = os.environ.get('POLYGON_API_KEY', '')
        if not polygon_key:
            polygon_cfg = self.config.get('data', {}).get('polygon', {})
            polygon_key = polygon_cfg.get('api_key', '')
            # Resolve env var references like "${POLYGON_API_KEY}"
            if polygon_key.startswith('${') and polygon_key.endswith('}'):
                polygon_key = os.environ.get(polygon_key[2:-1], '')

        if polygon_key:
            historical_data = HistoricalOptionsData(polygon_key)
            if clear_cache:
                historical_data.clear_cache()
            logger.info("Using real Polygon historical options data")
        else:
            logger.warning("No POLYGON_API_KEY — falling back to heuristic backtester")

        backtester = Backtester(self.config, historical_data=historical_data)
        results = backtester.run_backtest(ticker, start_date, end_date)

        if historical_data:
            historical_data.close()

        if not results:
            logger.error("Backtest failed")
            return

        # Display results
        perf = PerformanceMetrics(self.config)
        perf.print_summary(results)

        # Generate report
        report_file = perf.generate_report(results)
        logger.info(f"Backtest report saved to: {report_file}")

        # Write to canonical path for web dashboard API
        import json
        from shared.constants import OUTPUT_DIR
        canonical_path = os.path.join(OUTPUT_DIR, 'backtest_results.json')
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        try:
            with open(canonical_path, 'w') as f:
                json.dump(results, f, indent=2, default=str)
        except OSError as e:
            logger.warning(f"Failed to write canonical backtest results: {e}")

        return results

    def show_dashboard(self):
        """
        Display P&L dashboard.
        """
        self.dashboard.display_dashboard()

    def generate_alerts_only(self):
        """
        Generate and send alerts from stored alert data in the database.
        Does NOT run a new scan — reads previously saved alerts.
        """
        from shared.database import get_latest_alerts

        logger.info("Generating alerts from stored data")

        stored_alerts = get_latest_alerts(limit=50)
        if not stored_alerts:
            logger.info("No stored alerts found. Run a scan first.")
            return

        logger.info(f"Found {len(stored_alerts)} stored alerts")
        self._generate_alerts(stored_alerts)


def create_system(config_file: str = 'config.yaml') -> CreditSpreadSystem:
    """Factory function that loads config and builds a CreditSpreadSystem.

    This preserves the original single-argument construction workflow:
    load config, validate, set up logging, then instantiate all components
    via the default ``None`` paths inside ``CreditSpreadSystem.__init__``.

    Args:
        config_file: Path to the YAML configuration file.

    Returns:
        A fully initialised CreditSpreadSystem.
    """
    config = load_config(config_file)
    validate_config(config)
    setup_logging(config)

    system = CreditSpreadSystem(config=config)

    # Pre-warm the data cache with commonly used tickers
    system.data_cache.pre_warm(['SPY', '^VIX', 'TLT'])

    return system


def main():
    """
    Main entry point.
    """
    parser = argparse.ArgumentParser(
        description='Credit Spread Trading System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py scan              # Run one scan now
  python main.py scheduler         # Run scans on market-hours schedule (14x/day)
  python main.py backtest          # Run backtest on SPY
  python main.py backtest --ticker QQQ --days 180
  python main.py dashboard         # Show P&L dashboard
  python main.py alerts            # Generate alerts only
        """
    )

    parser.add_argument(
        'command',
        choices=['scan', 'scheduler', 'backtest', 'dashboard', 'alerts', 'paper'],
        help='Command to run'
    )

    parser.add_argument(
        '--ticker',
        default='SPY',
        help='Ticker for backtest (default: SPY)'
    )

    parser.add_argument(
        '--days',
        type=int,
        default=365,
        help='Lookback days for backtest (default: 365)'
    )

    parser.add_argument(
        '--clear-cache',
        action='store_true',
        default=False,
        help='Clear options price cache before backtesting'
    )

    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Config file path (default: config.yaml)'
    )

    args = parser.parse_args()

    # Register graceful shutdown handlers
    def _shutdown_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logging.getLogger(__name__).info(
            f"Received shutdown signal ({sig_name}), exiting gracefully..."
        )
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    try:
        # Initialize system
        system = create_system(config_file=args.config)

        # Execute command
        if args.command == 'scan':
            system.scan_opportunities()

        elif args.command == 'scheduler':
            from shared.scheduler import ScanScheduler

            def scan_and_sync():
                system.scan_opportunities()
                system.paper_trader.sync_alpaca_orders()

            scheduler = ScanScheduler(scan_fn=scan_and_sync)

            # Let SIGTERM/SIGINT stop the scheduler cleanly
            def _stop_scheduler(signum, frame):
                sig_name = signal.Signals(signum).name
                logger.info("Received %s — stopping scheduler", sig_name)
                scheduler.stop()

            signal.signal(signal.SIGTERM, _stop_scheduler)
            signal.signal(signal.SIGINT, _stop_scheduler)

            logger.info("Starting scan scheduler (14 scans/day, ET weekdays)")
            scheduler.run_forever()

        elif args.command == 'backtest':
            system.run_backtest(ticker=args.ticker, lookback_days=args.days, clear_cache=args.clear_cache)

        elif args.command == 'dashboard':
            system.show_dashboard()

        elif args.command == 'alerts':
            system.generate_alerts_only()

        elif args.command == 'paper':
            system.paper_trader.print_summary()

        logger.info("Command completed successfully")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
