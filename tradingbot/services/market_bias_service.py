import asyncio
from datetime import datetime, timezone
from typing import Optional, Tuple
import pandas as pd
from tradingbot.core.config import MarketBiasConfig
from tradingbot.utils.logger import log

class BTCMarketBiasFilter:
    """
    Filtro de Tendencia Macro de Mercado (BTC Market Bias Filter).
    Evalúa la tendencia de Bitcoin (BTC/USDT) en timeframe macro (1h) para autorizar o bloquear
    compras en altcoins.
    
    Condición BULLISH:
        BTC 1h close >= EMA 50
    Condición BEARISH:
        BTC 1h close < EMA 50
    """
    def __init__(self, config: Optional[MarketBiasConfig] = None):
        self.config = config or MarketBiasConfig()
        self.btc_symbol = getattr(self.config, "btc_symbol", "BTC/USDT")
        self.timeframe = getattr(self.config, "timeframe", "1h")
        self.ema_period = getattr(self.config, "ema_period", 50)
        self.ttl_seconds = getattr(self.config, "cache_ttl_seconds", 60)
        self.enabled = getattr(self.config, "enabled", True)

        self._cached_bias: str = "BULLISH"
        self._cached_reason: str = "Initial default"
        self._last_checked: Optional[datetime] = None
        self._last_btc_price: float = 0.0
        self._last_btc_ema: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def cached_bias(self) -> str:
        return self._cached_bias

    @property
    def cached_reason(self) -> str:
        return self._cached_reason

    def is_cache_valid(self) -> bool:
        if self._last_checked is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self._last_checked).total_seconds()
        return elapsed < self.ttl_seconds

    async def get_btc_bias(self, data_collector) -> Tuple[str, str]:
        """
        Retorna (bias, reason), donde bias es 'BULLISH' o 'BEARISH'.
        Utiliza caché en memoria para minimizar peticiones HTTP a Binance.
        """
        if not self.enabled:
            return "BULLISH", "BTC Market Bias Filter disabled in config"

        if self.is_cache_valid():
            return self._cached_bias, self._cached_reason

        async with self._lock:
            # Doble verificación dentro del lock
            if self.is_cache_valid():
                return self._cached_bias, self._cached_reason

            try:
                limit = max(60, self.ema_period + 15)
                df = await data_collector.get_historical_data(
                    symbol=self.btc_symbol,
                    timeframe=self.timeframe,
                    limit=limit
                )

                if df.empty or len(df) < self.ema_period:
                    log.warning(f"[BTCBiasFilter] Velas insuficientes para {self.btc_symbol} ({len(df)}/{self.ema_period}). Fallback BULLISH.")
                    return "BULLISH", f"Insufficient BTC candles ({len(df)})"

                # Calcular EMA
                ema_series = df['close'].ewm(span=self.ema_period, adjust=False).mean()
                last_close = float(df['close'].iloc[-1])
                last_ema = float(ema_series.iloc[-1])
                prev_ema = float(ema_series.iloc[-2]) if len(ema_series) >= 2 else last_ema

                self._last_btc_price = last_close
                self._last_btc_ema = last_ema
                self._last_checked = datetime.now(timezone.utc)

                if last_close >= last_ema:
                    self._cached_bias = "BULLISH"
                    self._cached_reason = f"BTC 1h ${last_close:,.2f} >= EMA{self.ema_period} ${last_ema:,.2f}"
                else:
                    self._cached_bias = "BEARISH"
                    self._cached_reason = f"BTC 1h ${last_close:,.2f} < EMA{self.ema_period} ${last_ema:,.2f}"

                log.info(f"[BTCBiasFilter] Estado actualizado: {self._cached_bias} ({self._cached_reason})")
                return self._cached_bias, self._cached_reason

            except Exception as e:
                log.warning(f"[BTCBiasFilter] Error consultando tendencia BTC: {e}. Manteniendo último sesgo ({self._cached_bias}).")
                return self._cached_bias, f"Fallback due to error: {e}"
