import ccxt.async_support as ccxt
from typing import Any, Dict, List, Optional
from tradingbot.market.connector import ExchangeConnector
from tradingbot.core.config import get_settings
from tradingbot.utils.logger import log

class CCXTConnector(ExchangeConnector):
    """
    CCXT-based implementation of the ExchangeConnector.
    """
    
    def __init__(self):
        settings = get_settings()
        exchange_id = settings.exchange_id
        
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Exchange '{exchange_id}' is not supported by CCXT.")
            
        exchange_class = getattr(ccxt, exchange_id)
        
        exchange_config = {
            'apiKey': settings.exchange_api_key,
            'secret': settings.exchange_api_secret,
            'enableRateLimit': True,
        }
        
        self.exchange: ccxt.Exchange = exchange_class(exchange_config)
        
        # Enable testnet/sandbox mode if configured
        if settings.exchange_testnet:
            try:
                self.exchange.set_sandbox_mode(True)
                log.info(f"Sandbox mode (testnet) enabled for {exchange_id}")
            except Exception as e:
                log.error(f"Could not enable sandbox mode for {exchange_id}: {e}")
                
        log.info(f"Initialized CCXTConnector with exchange: {exchange_id}")

    async def fetch_balance(self) -> Dict[str, Any]:
        log.info("Fetching balance")
        try:
            return await self.exchange.fetch_balance()
        except Exception as e:
            log.error(f"Error fetching balance: {e}")
            raise

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        log.info(f"Fetching ticker for {symbol}")
        try:
            return await self.exchange.fetch_ticker(symbol)
        except Exception as e:
            log.error(f"Error fetching ticker for {symbol}: {e}")
            raise

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: Optional[int] = None, limit: Optional[int] = None
    ) -> List[List[Any]]:
        log.info(f"Fetching OHLCV for {symbol} (timeframe: {timeframe})")
        try:
            return await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
        except Exception as e:
            log.error(f"Error fetching OHLCV for {symbol}: {e}")
            raise

    async def create_order(
        self, symbol: str, type: str, side: str, amount: float, price: Optional[float] = None
    ) -> Dict[str, Any]:
        log.info(f"Creating order: {symbol} | Type: {type} | Side: {side} | Amount: {amount} | Price: {price}")
        try:
            return await self.exchange.create_order(symbol, type, side, amount, price)
        except Exception as e:
            log.error(f"Error creating order for {symbol}: {e}")
            raise

    async def cancel_order(self, id: str, symbol: str) -> Dict[str, Any]:
        log.info(f"Canceling order {id} for {symbol}")
        try:
            return await self.exchange.cancel_order(id, symbol)
        except Exception as e:
            log.error(f"Error canceling order {id} for {symbol}: {e}")
            raise

    async def close(self):
        log.info("Closing CCXT connector session")
        if self.exchange:
            await self.exchange.close()
