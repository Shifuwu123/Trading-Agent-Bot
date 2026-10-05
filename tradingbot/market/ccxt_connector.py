import asyncio
import os
import pickle
import time
import threading
from typing import Any, Dict, List, Optional
import ccxt.async_support as ccxt
from tradingbot.market.connector import ExchangeConnector
from tradingbot.core.config import get_settings
from tradingbot.utils.logger import log

class CCXTConnector(ExchangeConnector):
    """
    CCXT-based implementation of the ExchangeConnector.
    Features:
    - Multi-level caching (in-memory & disk) for exchange market metadata.
    - Extended network timeout (45s on testnet / 30s on live).
    - Automatic retry with exponential backoff on transient network and timeout errors.
    """
    _cached_markets: Dict[str, Dict[str, Any]] = {}
    _cached_currencies: Dict[str, Dict[str, Any]] = {}
    _cache_timestamp: Dict[str, float] = {}
    _CACHE_TTL: float = 24 * 3600.0  # 24 horas
    _thread_lock = threading.Lock()
    _cache_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache"))

    def __init__(self):
        settings = get_settings()
        exchange_id = settings.exchange_id
        
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Exchange '{exchange_id}' is not supported by CCXT.")
            
        exchange_class = getattr(ccxt, exchange_id)
        
        is_testnet = bool(settings.exchange_testnet)
        self.cache_key = f"{exchange_id}_{'testnet' if is_testnet else 'live'}"
        timeout_ms = 45000 if is_testnet else 30000

        exchange_config = {
            'apiKey': settings.exchange_api_key,
            'secret': settings.exchange_api_secret,
            'enableRateLimit': True,
            'timeout': timeout_ms,
        }
        
        self.exchange: ccxt.Exchange = exchange_class(exchange_config)
        
        # Enable testnet/sandbox mode if configured
        if is_testnet:
            try:
                self.exchange.set_sandbox_mode(True)
                log.info(f"Sandbox mode (testnet) enabled for {exchange_id} (timeout: {timeout_ms}ms)")
            except Exception as e:
                log.error(f"Could not enable sandbox mode for {exchange_id}: {e}")
                
        # Populate exchange with cached markets if available (avoids 25s HTTP request on load_markets)
        self._apply_cached_markets()

        log.info(f"Initialized CCXTConnector with exchange: {exchange_id} (cache_key: {self.cache_key})")

    def _get_cache_filepath(self) -> str:
        return os.path.join(self._cache_dir, f"markets_{self.cache_key}.pkl")

    def _apply_cached_markets(self) -> bool:
        """Loads cached markets into self.exchange if available in memory or disk."""
        with CCXTConnector._thread_lock:
            # 1. Check in-memory cache
            if self.cache_key in CCXTConnector._cached_markets:
                cached_time = CCXTConnector._cache_timestamp.get(self.cache_key, 0.0)
                if (time.time() - cached_time) < CCXTConnector._CACHE_TTL:
                    try:
                        self.exchange.set_markets(
                            CCXTConnector._cached_markets[self.cache_key],
                            CCXTConnector._cached_currencies.get(self.cache_key)
                        )
                        log.debug(f"Loaded {len(self.exchange.markets)} markets from memory cache for {self.cache_key}")
                        return True
                    except Exception as e:
                        log.warning(f"Error applying in-memory markets cache: {e}")

            # 2. Check disk cache
            cache_file = self._get_cache_filepath()
            if os.path.exists(cache_file):
                try:
                    file_mtime = os.path.getmtime(cache_file)
                    if (time.time() - file_mtime) < CCXTConnector._CACHE_TTL:
                        with open(cache_file, "rb") as f:
                            disk_data = pickle.load(f)
                        markets = disk_data.get("markets", {})
                        currencies = disk_data.get("currencies", {})
                        if markets:
                            CCXTConnector._cached_markets[self.cache_key] = markets
                            CCXTConnector._cached_currencies[self.cache_key] = currencies
                            CCXTConnector._cache_timestamp[self.cache_key] = file_mtime
                            self.exchange.set_markets(markets, currencies)
                            log.info(f"Loaded {len(markets)} markets from disk cache for {self.cache_key}")
                            return True
                except Exception as e:
                    log.warning(f"Error reading disk markets cache: {e}")

        return False

    def _save_to_disk_cache(self, markets: dict, currencies: dict):
        """Saves markets and currencies to disk atomically."""
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            cache_file = self._get_cache_filepath()
            tmp_file = f"{cache_file}.tmp_{os.getpid()}_{int(time.time())}"
            with open(tmp_file, "wb") as f:
                pickle.dump({"markets": markets, "currencies": currencies, "timestamp": time.time()}, f)
            os.replace(tmp_file, cache_file)
            log.info(f"Saved {len(markets)} markets to disk cache: {cache_file}")
        except Exception as e:
            log.warning(f"Failed to save markets to disk cache: {e}")

    async def ensure_markets_loaded(self, reload: bool = False) -> Dict[str, Any]:
        """
        Ensures market data is loaded in the exchange instance.
        If not loaded, fetches once and persists to memory and disk cache.
        """
        if not reload and getattr(self.exchange, "markets", None):
            return self.exchange.markets

        # If cache can be applied, do so
        if not reload and self._apply_cached_markets():
            return self.exchange.markets

        # Fetch from exchange
        log.info(f"Fetching market metadata from exchange for {self.cache_key}...")
        try:
            markets = await self.exchange.load_markets(reload=True)
            currencies = getattr(self.exchange, "currencies", {})
            with CCXTConnector._thread_lock:
                CCXTConnector._cached_markets[self.cache_key] = markets
                CCXTConnector._cached_currencies[self.cache_key] = currencies
                CCXTConnector._cache_timestamp[self.cache_key] = time.time()
            self._save_to_disk_cache(markets, currencies)
            return markets
        except Exception as e:
            log.error(f"Failed to load markets from exchange: {e}")
            raise

    async def fetch_balance(self, max_retries: int = 3) -> Dict[str, Any]:
        log.info("Fetching balance")
        for attempt in range(1, max_retries + 1):
            try:
                return await self.exchange.fetch_balance()
            except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
                if attempt == max_retries:
                    log.error(f"Error fetching balance after {max_retries} attempts: {e}")
                    raise
                backoff = 2 ** attempt
                log.warning(f"Network error fetching balance (attempt {attempt}/{max_retries}), retrying in {backoff}s: {e}")
                await asyncio.sleep(backoff)
            except Exception as e:
                log.error(f"Error fetching balance: {e}")
                raise

    async def fetch_ticker(self, symbol: str, max_retries: int = 3) -> Dict[str, Any]:
        log.info(f"Fetching ticker for {symbol}")
        await self.ensure_markets_loaded()
        for attempt in range(1, max_retries + 1):
            try:
                return await self.exchange.fetch_ticker(symbol)
            except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
                if attempt == max_retries:
                    log.error(f"Error fetching ticker for {symbol} after {max_retries} attempts: {e}")
                    raise
                backoff = 2 ** attempt
                log.warning(f"Network error fetching ticker for {symbol} (attempt {attempt}/{max_retries}), retrying in {backoff}s: {e}")
                await asyncio.sleep(backoff)
            except Exception as e:
                log.error(f"Error fetching ticker for {symbol}: {e}")
                raise

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: Optional[int] = None, limit: Optional[int] = None, max_retries: int = 3
    ) -> List[List[Any]]:
        log.info(f"Fetching OHLCV for {symbol} (timeframe: {timeframe})")
        await self.ensure_markets_loaded()
        for attempt in range(1, max_retries + 1):
            try:
                return await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
                if attempt == max_retries:
                    log.error(f"Error fetching OHLCV for {symbol} after {max_retries} attempts: {e}")
                    raise
                backoff = 2 ** attempt
                log.warning(f"Timeout/Network error fetching OHLCV for {symbol} (attempt {attempt}/{max_retries}), retrying in {backoff}s: {e}")
                await asyncio.sleep(backoff)
            except Exception as e:
                log.error(f"Error fetching OHLCV for {symbol}: {e}")
                raise

    async def create_order(
        self, symbol: str, type: str, side: str, amount: float, price: Optional[float] = None
    ) -> Dict[str, Any]:
        log.info(f"Creating order: {symbol} | Type: {type} | Side: {side} | Amount: {amount} | Price: {price}")
        await self.ensure_markets_loaded()
        try:
            return await self.exchange.create_order(symbol, type, side, amount, price)
        except Exception as e:
            log.error(f"Error creating order for {symbol}: {e}")
            raise

    async def cancel_order(self, id: str, symbol: str) -> Dict[str, Any]:
        log.info(f"Canceling order {id} for {symbol}")
        await self.ensure_markets_loaded()
        try:
            return await self.exchange.cancel_order(id, symbol)
        except Exception as e:
            log.error(f"Error canceling order {id} for {symbol}: {e}")
            raise

    async def close(self):
        log.info("Closing CCXT connector session")
        if self.exchange:
            await self.exchange.close()
