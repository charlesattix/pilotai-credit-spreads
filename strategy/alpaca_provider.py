"""
Alpaca Paper Trading Provider
Submits real option spread orders to Alpaca paper trading API.
Uses alpaca-py SDK for multi-leg option orders.
"""

import logging
import uuid
import time
import random
import functools
from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.exceptions import ProviderError
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    GetOrdersRequest,
    GetOptionContractsRequest,
    OptionLegRequest,
)
from alpaca.trading.enums import (
    OrderClass,
    OrderSide,
    TimeInForce,
    QueryOrderStatus,
    ContractType,
    PositionIntent,
)

logger = logging.getLogger(__name__)


def _retry_with_backoff(max_retries: int = 2, base_delay: float = 1.0):
    """Decorator that retries a method with exponential backoff + jitter."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, base_delay)
                        logger.warning(
                            f"{func.__name__} attempt {attempt + 1} failed: {exc}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator


class AlpacaProvider:
    """Submit credit spread orders to Alpaca paper trading."""

    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        self.client = TradingClient(api_key, api_secret, paper=paper)
        self._verify_connection()

    def _verify_connection(self):
        """Verify API connectivity and log account info."""
        try:
            acct = self.client.get_account()
            logger.info(
                f"Alpaca connected | Account: ***{str(acct.account_number)[-4:]} | "
                f"Status: {acct.status} | Cash: ${float(acct.cash):,.2f} | "
                f"Options Level: {acct.options_trading_level}"
            )
        except Exception as e:
            logger.error(f"Alpaca connection failed: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------

    def get_account(self) -> Dict:
        """Get account balance and buying power."""
        try:
            acct = self.client.get_account()
        except Exception as e:
            logger.error(f"Failed to get Alpaca account info: {e}", exc_info=True)
            raise ProviderError(f"Alpaca get_account failed: {e}") from e
        return {
            "account_number": acct.account_number,
            "status": str(acct.status),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
            "options_buying_power": float(acct.options_buying_power),
            "options_level": acct.options_trading_level,
            "equity": float(acct.equity),
        }

    # ------------------------------------------------------------------
    # Option symbol helpers
    # ------------------------------------------------------------------

    def _build_occ_symbol(self, ticker: str, expiration: str, strike: float, option_type: str) -> str:
        """
        Build OCC option symbol: SPY260320C00500000
        ticker (padded to 6), YYMMDD, C/P, strike * 1000 padded to 8.
        """
        # Parse expiration
        if isinstance(expiration, datetime):
            exp_dt = expiration
        else:
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                try:
                    exp_dt = datetime.strptime(expiration.split(" ")[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Cannot parse expiration: {expiration}")

        date_str = exp_dt.strftime("%y%m%d")
        cp = "C" if option_type.lower().startswith("c") else "P"
        strike_int = int(strike * 1000)
        return f"{ticker.upper():<6}{date_str}{cp}{strike_int:08d}".replace(" ", " ").strip()

    def find_option_symbol(self, ticker: str, expiration: str, strike: float, option_type: str) -> Optional[str]:
        """
        Look up the actual Alpaca option contract symbol via the API.
        Falls back to OCC symbol construction if lookup fails.
        """
        try:
            ct = ContractType.CALL if option_type.lower().startswith("c") else ContractType.PUT
            req = GetOptionContractsRequest(
                underlying_symbols=[ticker.upper()],
                expiration_date=expiration.split(" ")[0] if " " in expiration else expiration,
                type=ct,
                strike_price_gte=str(strike),
                strike_price_lte=str(strike),
                limit=5,
            )
            resp = self.client.get_option_contracts(req)
            contracts = resp.option_contracts if hasattr(resp, 'option_contracts') else resp
            if contracts:
                return contracts[0].symbol
        except Exception as e:
            logger.warning(f"Option contract lookup failed, using OCC symbol: {e}")

        return self._build_occ_symbol(ticker, expiration, strike, option_type)

    # ------------------------------------------------------------------
    # Shared MLEG order submission
    # ------------------------------------------------------------------

    def _submit_mleg_order(
        self,
        legs: List[OptionLegRequest],
        contracts: int,
        limit_price: Optional[float],
        client_id: str,
    ) -> "alpaca.trading.models.Order":
        """Build and submit a multi-leg option order.

        Args:
            legs: List of OptionLegRequest objects.
            contracts: Number of spreads.
            limit_price: Limit price (positive = credit). None for market.
            client_id: Client order ID for tracking.

        Returns:
            The Alpaca Order object.
        """
        if limit_price is not None:
            order_req = LimitOrderRequest(
                qty=contracts,
                order_class=OrderClass.MLEG,
                time_in_force=TimeInForce.DAY,
                legs=legs,
                limit_price=round(limit_price, 2),
                client_order_id=client_id,
            )
        else:
            from alpaca.trading.requests import MarketOrderRequest
            order_req = MarketOrderRequest(
                qty=contracts,
                order_class=OrderClass.MLEG,
                time_in_force=TimeInForce.DAY,
                legs=legs,
                client_order_id=client_id,
            )

        return self.client.submit_order(order_req)

    # ------------------------------------------------------------------
    # Submit credit spread
    # ------------------------------------------------------------------

    @_retry_with_backoff(max_retries=2, base_delay=1.0)
    def submit_credit_spread(
        self,
        ticker: str,
        short_strike: float,
        long_strike: float,
        expiration: str,
        spread_type: str,
        contracts: int = 1,
        limit_price: Optional[float] = None,
    ) -> Dict:
        """
        Submit a credit spread as a multi-leg order.

        Args:
            ticker: Underlying symbol (e.g. SPY)
            short_strike: Strike to sell
            long_strike: Strike to buy
            expiration: Expiration date string (YYYY-MM-DD)
            spread_type: 'bear_call' or 'bull_put'
            contracts: Number of spreads
            limit_price: Net credit limit price (positive = credit received).
                         If None, submits as market.

        Returns:
            Dict with order details and status.
        """
        is_call = "call" in spread_type.lower()
        opt_type = "call" if is_call else "put"

        # Resolve option symbols
        short_sym = self.find_option_symbol(ticker, expiration, short_strike, opt_type)
        long_sym = self.find_option_symbol(ticker, expiration, long_strike, opt_type)

        if not short_sym or not long_sym:
            return {"status": "error", "message": "Could not resolve option symbols"}

        logger.info(
            f"Submitting {spread_type} spread: SELL {short_sym} / BUY {long_sym} "
            f"x{contracts} @ limit {limit_price}"
        )

        # Build legs: sell short strike, buy long strike
        # ratio_qty=1 for equal ratio legs, qty on order controls total contracts
        legs = [
            OptionLegRequest(
                symbol=short_sym,
                ratio_qty=1,
                side=OrderSide.SELL,
                position_intent=PositionIntent.SELL_TO_OPEN,
            ),
            OptionLegRequest(
                symbol=long_sym,
                ratio_qty=1,
                side=OrderSide.BUY,
                position_intent=PositionIntent.BUY_TO_OPEN,
            ),
        ]

        client_id = f"cs-{ticker}-{uuid.uuid4().hex[:8]}"

        try:
            order = self._submit_mleg_order(legs, contracts, limit_price, client_id)

            result = {
                "status": "submitted",
                "order_id": str(order.id),
                "client_order_id": order.client_order_id,
                "order_status": str(order.status),
                "ticker": ticker,
                "spread_type": spread_type,
                "short_strike": short_strike,
                "long_strike": long_strike,
                "short_symbol": short_sym,
                "long_symbol": long_sym,
                "contracts": contracts,
                "limit_price": limit_price,
                "submitted_at": str(order.submitted_at),
            }

            logger.info(f"Order submitted: {result['order_id']} status={result['order_status']}")
            return result

        except Exception as e:
            logger.error(f"Order submission failed: {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
                "ticker": ticker,
                "spread_type": spread_type,
            }

    # ------------------------------------------------------------------
    # Close spread position
    # ------------------------------------------------------------------

    @_retry_with_backoff(max_retries=2, base_delay=1.0)
    def close_spread(
        self,
        ticker: str,
        short_strike: float,
        long_strike: float,
        expiration: str,
        spread_type: str,
        contracts: int = 1,
        limit_price: Optional[float] = None,
    ) -> Dict:
        """
        Close an existing credit spread (buy back short, sell long).
        """
        is_call = "call" in spread_type.lower()
        opt_type = "call" if is_call else "put"

        short_sym = self.find_option_symbol(ticker, expiration, short_strike, opt_type)
        long_sym = self.find_option_symbol(ticker, expiration, long_strike, opt_type)

        if not short_sym or not long_sym:
            return {"status": "error", "message": "Could not resolve option symbols for close order"}

        # Reverse legs: buy back short, sell long
        legs = [
            OptionLegRequest(
                symbol=short_sym,
                ratio_qty=1,
                side=OrderSide.BUY,
                position_intent=PositionIntent.BUY_TO_CLOSE,
            ),
            OptionLegRequest(
                symbol=long_sym,
                ratio_qty=1,
                side=OrderSide.SELL,
                position_intent=PositionIntent.SELL_TO_CLOSE,
            ),
        ]

        client_id = f"close-{ticker}-{uuid.uuid4().hex[:8]}"

        try:
            order = self._submit_mleg_order(legs, contracts, limit_price, client_id)
            logger.info(f"Close order submitted: {order.id} status={order.status}")
            return {
                "status": "submitted",
                "order_id": str(order.id),
                "order_status": str(order.status),
            }

        except Exception as e:
            logger.error(f"Close order failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # Query orders & positions
    # ------------------------------------------------------------------

    def get_orders(self, status: str = "all", limit: int = 50) -> List[Dict]:
        """Get recent orders."""
        status_map = {
            "all": QueryOrderStatus.ALL,
            "open": QueryOrderStatus.OPEN,
            "closed": QueryOrderStatus.CLOSED,
        }
        req = GetOrdersRequest(
            status=status_map.get(status, QueryOrderStatus.ALL),
            limit=limit,
        )
        orders = self.client.get_orders(req)
        return [
            {
                "id": str(o.id),
                "client_order_id": o.client_order_id,
                "status": str(o.status),
                "order_class": str(o.order_class),
                "type": str(o.type),
                "side": str(o.side) if o.side else None,
                "symbol": o.symbol,
                "qty": str(o.qty) if o.qty else None,
                "limit_price": str(o.limit_price) if o.limit_price else None,
                "filled_avg_price": str(o.filled_avg_price) if o.filled_avg_price else None,
                "submitted_at": str(o.submitted_at),
                "filled_at": str(o.filled_at) if o.filled_at else None,
                "legs": [
                    {
                        "symbol": leg.symbol,
                        "side": str(leg.side),
                        "qty": str(leg.qty) if leg.qty else None,
                        "status": str(leg.status),
                    }
                    for leg in (o.legs or [])
                ],
            }
            for o in orders
        ]

    def get_order_status(self, order_id: str) -> Dict:
        """Get status of a specific order."""
        order = self.client.get_order_by_id(order_id)
        return {
            "id": str(order.id),
            "status": str(order.status),
            "filled_avg_price": str(order.filled_avg_price) if order.filled_avg_price else None,
            "filled_at": str(order.filled_at) if order.filled_at else None,
        }

    def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        positions = self.client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": str(p.qty),
                "side": str(p.side),
                "avg_entry_price": str(p.avg_entry_price),
                "current_price": str(p.current_price),
                "market_value": str(p.market_value),
                "unrealized_pl": str(p.unrealized_pl),
                "asset_class": str(p.asset_class),
            }
            for p in positions
        ]

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        try:
            self.client.cancel_order_by_id(order_id)
            logger.info(f"Order {order_id} cancelled")
            return True
        except Exception as e:
            logger.error(f"Cancel failed: {e}", exc_info=True)
            return False

    def cancel_all_orders(self):
        """Cancel all open orders."""
        self.client.cancel_orders()
        logger.info("All orders cancelled")
