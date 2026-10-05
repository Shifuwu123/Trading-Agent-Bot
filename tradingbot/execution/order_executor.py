import uuid
import time
from typing import Dict, Any, Optional

from tradingbot.market.connector import ExchangeConnector
from tradingbot.core.config import get_settings
from tradingbot.utils.logger import log

class OrderExecutor:
    """
    Handles placing orders through the ExchangeConnector or mocking them
    for paper trading based on the configuration.
    """
    def __init__(self, connector: ExchangeConnector):
        self.connector = connector
        self.settings = get_settings()
        self.paper_trading = self.settings.paper_trading

    async def execute_order(
        self, 
        symbol: str, 
        side: str, 
        amount: float, 
        order_type: str = "MARKET", 
        price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Executes an order. Returns a standardized execution result dictionary.
        """
        log.info(f"Preparing to execute {side} order for {amount} of {symbol} (Type: {order_type}, Price: {price}, Paper: {self.paper_trading})")

        if self.paper_trading:
            return await self._mock_execution(symbol, side, amount, order_type, price)
        else:
            return await self._real_execution(symbol, side, amount, order_type, price)

    async def _mock_execution(
        self, 
        symbol: str, 
        side: str, 
        amount: float, 
        order_type: str, 
        price: Optional[float]
    ) -> Dict[str, Any]:
        """
        Mocks the execution of an order.
        """
        # In a real paper trading scenario, we'd want to fetch current market price
        # if the price is not specified (e.g. for a market order).
        execution_price = price
        if execution_price is None:
            try:
                ticker = await self.connector.fetch_ticker(symbol)
                execution_price = ticker.get('last') or ticker.get('close')
            except Exception as e:
                log.warning(f"Could not fetch live ticker for mock execution: {e}. Trying portfolio fallback.")
            
            if execution_price is None:
                try:
                    from tradingbot.execution.portfolio_manager import DatabaseSession
                    from tradingbot.database.models import Portfolio
                    session = DatabaseSession.get_session()
                    base_sym = symbol.split('/')[0]
                    p_entry = session.query(Portfolio).filter(Portfolio.asset == base_sym, Portfolio.is_paper == True).first()
                    if p_entry and p_entry.current_price and float(p_entry.current_price) > 0:
                        execution_price = float(p_entry.current_price)
                    session.close()
                except Exception as fe:
                    log.warning(f"Fallback portfolio price failed: {fe}")

            if execution_price is None:
                raise ValueError("Cannot mock execution without a valid market price")
                
        fake_id = f"mock_{uuid.uuid4().hex[:8]}"
        
        log.info(f"Mock execution successful: {fake_id} | {side} {amount} {symbol} @ {execution_price}")
        
        return {
            "order_id": fake_id,
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "amount": amount,
            "price": execution_price,
            "status": "closed",
            "timestamp": int(time.time() * 1000),
            "is_paper": True
        }

    async def _real_execution(
        self, 
        symbol: str, 
        side: str, 
        amount: float, 
        order_type: str, 
        price: Optional[float]
    ) -> Dict[str, Any]:
        """
        Performs a real execution via the ExchangeConnector.
        """
        try:
            result = await self.connector.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price
            )
            
            # Standardize output assuming ccxt-like format
            exec_result = {
                "order_id": str(result.get("id")),
                "symbol": result.get("symbol", symbol),
                "side": result.get("side", side).upper(),
                "type": result.get("type", order_type).upper(),
                "amount": float(result.get("amount", amount)),
                "price": float(result.get("average", result.get("price", price))),
                "status": result.get("status", "open"),
                "timestamp": int(result.get("timestamp", int(time.time() * 1000))),
                "is_paper": False
            }
            log.info(f"Real execution successful: {exec_result['order_id']} | {side} {amount} {symbol} @ {exec_result['price']}")
            return exec_result
            
        except Exception as e:
            log.error(f"Error during real order execution: {e}")
            raise
