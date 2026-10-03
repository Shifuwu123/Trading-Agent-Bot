import asyncio
from tradingbot.utils.logger import log

class MarketDataService:
    """
    Centralized Market Data Service.
    Uses a Pub/Sub model to feed OHLCV/Tick data to multiple strategies.
    Ensures that CCXT/Binance API is queried only once per tick, avoiding rate limits.
    (Skeleton implementation for Phase 11)
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(MarketDataService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.subscribers = []
        self._initialized = True
        log.info("MarketDataService initialized (Singleton)")

    def subscribe(self, strategy_callback):
        self.subscribers.append(strategy_callback)
        
    async def start_streaming(self):
        log.info("MarketDataService: Starting WebSocket streams... (Placeholder)")
        # Implement ccxt.pro watch_ticker / watch_ohlcv loops here
        pass
